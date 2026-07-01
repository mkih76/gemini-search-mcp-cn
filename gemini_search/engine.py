"""Lightweight engine for Google Search AI Overview (DOM-scraped).

Forked from gemini-search-mcp by Sophomoresty.
Original used Google AI Mode via folwr token endpoint, which:
  - Only works on US-region IPs with full AI Mode rollout
  - Broke when Google changed the page structure (data-srtst no longer in HTML)
  - Forced a redirect to google.com.hk which disabled AI Mode for non-US users

This fork uses Google Search AI Overview directly:
  - Loads https://www.google.com/search?q=... (Google handles redirect naturally)
  - Waits for the AI Overview container (#m-x-content, class D5ad8b) to render
  - Extracts synthesized answer + sources from the rendered DOM
  - Falls back to top organic results if AI Overview is not available

Compatible with the original MCP server entry points (gemini_search_mcp, gemini-search).
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

try:
    import websockets
except ImportError:  # pragma: no cover - surfaced at runtime by _connect_cdp
    websockets = None


# JavaScript that:
#   1. waits for #m-x-content (AI Overview container) to render, with timeout
#   2. extracts the visible text + sources
#   3. falls back to top organic results if AI Overview is absent
_ASK_JS = """
(async (q) => {
    const wait = (ms) => new Promise(r => setTimeout(r, ms));
    const t0 = Date.now();
    const TIMEOUT_MS = 15000;

    // Helper: clean Google SERP noise
    const clean = (s) => {
        if (!s) return '';
        return s
            .replace(/\\s+/g, ' ')
            .replace(/AI Overview\\s*\\+\\d+\\s*/g, '')
            .replace(/Show more/gi, '')
            .trim();
    };

    // Try to find AI Overview (container with class D5ad8b or id m-x-content)
    let aiContainer = null;
    while (Date.now() - t0 < TIMEOUT_MS) {
        aiContainer = document.querySelector('#m-x-content')
                   || document.querySelector('.D5ad8b')
                   || document.querySelector('[data-attrid="AIOverview"]');
        if (aiContainer && aiContainer.innerText && aiContainer.innerText.length > 100) {
            break;
        }
        aiContainer = null;
        await wait(500);
    }

    if (aiContainer) {
        // Extract the main synthesized answer text
        // AI Overview structure: header + multiple <p> or list items + sources
        const mainBlocks = [];
        aiContainer.querySelectorAll('p, li').forEach(el => {
            const t = clean(el.innerText);
            if (t && t.length > 30 && !t.startsWith('AI Overview')) {
                mainBlocks.push(t);
            }
        });
        // De-dupe consecutive identicals
        const seen = new Set();
        const unique = [];
        for (const b of mainBlocks) {
            if (!seen.has(b)) { seen.add(b); unique.push(b); }
        }

        // Extract source citations
        const sources = [];
        aiContainer.querySelectorAll('a[href^="http"]').forEach(a => {
            const href = a.href;
            const title = clean(a.innerText);
            if (href && !href.includes('google.com') && title) {
                sources.push({title, url: href});
            }
        });

        return {
            ok: true,
            source: 'ai_overview',
            answer: unique.join('\\n\\n'),
            sources: sources.slice(0, 8),
            elapsed_ms: Date.now() - t0,
        };
    }

    // FALLBACK: no AI Overview, return top 5 organic results
    const organic = [];
    document.querySelectorAll('div.g, div[jscontroller][data-hveid]').forEach((el, idx) => {
        if (organic.length >= 5) return;
        const titleEl = el.querySelector('h3');
        const linkEl = el.querySelector('a[href^="http"]');
        const snippetEl = el.querySelector('.VwiC3b, .yXK7lf, [data-content-feature]');
        if (titleEl && linkEl && snippetEl) {
            organic.push({
                title: clean(titleEl.innerText),
                url: linkEl.href,
                snippet: clean(snippetEl.innerText),
            });
        }
    });

    if (organic.length === 0) {
        return {
            ok: false,
            error: 'no_results',
            elapsed_ms: Date.now() - t0,
            finalUrl: window.location.href,
        };
    }

    return {
        ok: true,
        source: 'organic_fallback',
        answer: organic.map((r, i) =>
            `[${i+1}] ${r.title}\\n${r.snippet}\\n${r.url}`
        ).join('\\n\\n'),
        sources: organic,
        elapsed_ms: Date.now() - t0,
    };
})(%QUERY%)
"""


def _env_or_value(value: Optional[str], *env_names: str) -> Optional[str]:
    """Return an explicit value, or the first non-empty environment value."""
    if value:
        return value
    for name in env_names:
        candidate = os.environ.get(name)
        if candidate:
            return candidate
    return None


def _version_sort_key(path: Path) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", str(path))
    if not match:
        return ()
    return tuple(int(part) for part in match.groups())


def _existing(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths if path.is_file()]


def _find_chrome(channel: str = "chrome") -> str:
    """Find a Chrome/Edge/Chromium binary path on the system."""
    system = platform.system()
    requested = (channel or "chrome").lower()
    candidates: list[str] = []

    explicit = _env_or_value(None, "CHROME_PATH", "UC_CHROME_BINARY")
    if explicit:
        candidates.append(explicit)

    home = Path.home()
    if system == "Windows":
        by_channel: dict[str, list[Path]] = {"chrome": [], "msedge": [], "chromium": []}
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            cft_root = Path(local_appdata) / "agent-browser-cli" / "chrome-for-testing"
            by_channel["chrome"].extend(
                sorted(
                    cft_root.glob("*/chrome-win64/chrome.exe"),
                    key=_version_sort_key,
                    reverse=True,
                )
            )

        for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base_value = os.environ.get(key)
            if not base_value:
                continue
            base = Path(base_value)
            by_channel["chrome"].append(base / "Google" / "Chrome" / "Application" / "chrome.exe")
            by_channel["msedge"].append(base / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        if requested in by_channel:
            candidates.extend(_existing(by_channel[requested]))
        for name, paths in by_channel.items():
            if name != requested:
                candidates.extend(_existing(paths))
        candidates.extend(["chrome.exe", "msedge.exe"])
    elif system == "Darwin":
        by_channel = {
            "chrome": [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")],
            "msedge": [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")],
            "chromium": [Path("/Applications/Chromium.app/Contents/MacOS/Chromium")],
        }
        if requested in by_channel:
            candidates.extend(_existing(by_channel[requested]))
        for name, paths in by_channel.items():
            if name != requested:
                candidates.extend(_existing(paths))
    else:
        local_chromes: list[Path] = []
        for root in (
            home / ".local/share/browser-binaries/puppeteer/chrome",
            home / ".local/share/browser-binaries/ms-playwright",
        ):
            local_chromes.extend(root.glob("**/chrome-linux64/chrome"))
        candidates.extend(
            str(path)
            for path in sorted(local_chromes, key=_version_sort_key, reverse=True)
        )
        linux_by_channel = {
            "chrome": ["google-chrome", "google-chrome-stable", "chrome"],
            "msedge": ["microsoft-edge", "microsoft-edge-stable", "msedge"],
            "chromium": ["chromium", "chromium-browser"],
        }
        if requested in linux_by_channel:
            candidates.extend(linux_by_channel[requested])
        for name, names in linux_by_channel.items():
            if name != requested:
                candidates.extend(names)

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate).expanduser()
        if path.is_file() and (system == "Windows" or os.access(path, os.X_OK)):
            return str(path)
        found = shutil.which(candidate)
        if found:
            return found
    raise RuntimeError("Chrome/Edge/Chromium not found. Install Chrome or set CHROME_PATH env var.")


def _chrome_major_version(binary: str) -> Optional[int]:
    """Best-effort Chrome major version detection for undetected-chromedriver."""
    path_match = re.search(r"(?:^|[\\/])(\d+)\.\d+\.\d+\.\d+(?:[\\/]|$)", str(binary))
    if path_match:
        return int(path_match.group(1))

    try:
        cp = subprocess.run(
            [binary, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except Exception:
        return None
    text = f"{cp.stdout}\n{cp.stderr}"
    match = re.search(r"(\d+)\.\d+\.\d+\.\d+", text)
    return int(match.group(1)) if match else None


def _normalize_browser_backend(backend: Optional[str]) -> str:
    value = (backend or "subprocess").strip().lower()
    aliases = {
        "raw": "subprocess",
        "chrome": "subprocess",
        "subprocess": "subprocess",
        "uc": "undetected",
        "undetected": "undetected",
        "undetected-chromedriver": "undetected",
    }
    if value not in aliases:
        raise ValueError("browser_backend must be 'subprocess' or 'undetected'")
    return aliases[value]


class AIModeEngine:
    """Single-tab Chrome engine via raw CDP.

    Loads Google Search results pages and waits for the AI Overview
    container (#m-x-content) to render, then extracts synthesized answer
    plus source citations.
    """

    def __init__(self):
        self._proc = None
        self._uc_driver = None
        self._ws = None
        self._ws_url = None
        self._page_target = None
        self._lock = asyncio.Lock()
        self._msg_id = 0
        self._cdp_url = None
        self._user_data_dir = None
        self._owns_user_data_dir = False
        self._browser_backend = "subprocess"

    async def start(
        self,
        cdp_url=None,
        headless=True,
        channel="chrome",
        user_data_dir: Optional[str] = None,
        browser_backend: Optional[str] = None,
        proxy_server: Optional[str] = None,
        chromedriver_path: Optional[str] = None,
    ):
        """Start Chrome and connect via CDP."""
        self._cdp_url = cdp_url
        self._browser_backend = _normalize_browser_backend(
            _env_or_value(browser_backend, "GEMINI_SEARCH_BROWSER_BACKEND")
        )
        try:
            if cdp_url:
                await self._connect_cdp(cdp_url)
            else:
                await self._launch_chrome(
                    headless=headless,
                    channel=channel,
                    user_data_dir=user_data_dir,
                    browser_backend=self._browser_backend,
                    proxy_server=proxy_server,
                    chromedriver_path=chromedriver_path,
                )
            await self._warmup()
        except Exception:
            await self.stop()
            raise

    def _prepare_user_data_dir(self, user_data_dir: Optional[str]) -> str:
        if user_data_dir:
            profile_path = Path(user_data_dir).expanduser().resolve()
            profile_path.mkdir(parents=True, exist_ok=True)
            self._user_data_dir = str(profile_path)
            self._owns_user_data_dir = False
        else:
            self._user_data_dir = tempfile.mkdtemp(prefix="gemini-search-mcp-")
            self._owns_user_data_dir = True
        return self._user_data_dir

    async def _launch_chrome(
        self,
        headless=True,
        channel="chrome",
        user_data_dir: Optional[str] = None,
        browser_backend: Optional[str] = None,
        proxy_server: Optional[str] = None,
        chromedriver_path: Optional[str] = None,
    ):
        backend = _normalize_browser_backend(browser_backend)
        if backend == "undetected":
            await self._launch_undetected_chrome(
                headless=headless,
                channel=channel,
                user_data_dir=user_data_dir,
                proxy_server=proxy_server,
                chromedriver_path=chromedriver_path,
            )
            return
        await self._launch_subprocess_chrome(
            headless=headless,
            channel=channel,
            user_data_dir=user_data_dir,
            proxy_server=proxy_server,
        )

    async def _launch_subprocess_chrome(
        self,
        headless=True,
        channel="chrome",
        user_data_dir: Optional[str] = None,
        proxy_server: Optional[str] = None,
    ):
        """Launch Chrome subprocess with minimal automation footprint."""
        chrome_path = _find_chrome(channel)
        profile_dir = self._prepare_user_data_dir(user_data_dir)
        port = int(os.environ.get("GEMINI_SEARCH_CDP_PORT", "19250"))
        proxy = _env_or_value(proxy_server, "GEMINI_SEARCH_PROXY_SERVER")

        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--lang=en-US",
        ]
        if proxy:
            args.append(f"--proxy-server={proxy}")
        if headless:
            args.append("--headless=new")
        args.append("about:blank")

        self._proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        await self._wait_for_cdp(port, f"Chrome subprocess (pid={self._proc.pid})")
        await self._connect_cdp(f"http://127.0.0.1:{port}")

    async def _launch_undetected_chrome(
        self,
        headless=True,
        channel="chrome",
        user_data_dir: Optional[str] = None,
        proxy_server: Optional[str] = None,
        chromedriver_path: Optional[str] = None,
    ):
        """Launch Chrome through undetected-chromedriver, then use CDP."""
        try:
            import undetected_chromedriver as uc
        except ImportError as exc:
            raise RuntimeError(
                "undetected backend requires: pip install -e '.[undetected]'"
            ) from exc

        chrome_path = _env_or_value(None, "UC_CHROME_BINARY", "CHROME_PATH") or _find_chrome(channel)
        profile_dir = self._prepare_user_data_dir(user_data_dir)
        port = int(os.environ.get("GEMINI_SEARCH_CDP_PORT", "19250"))
        proxy = _env_or_value(proxy_server, "GEMINI_SEARCH_PROXY_SERVER")
        driver_path = _env_or_value(
            chromedriver_path,
            "GEMINI_SEARCH_CHROMEDRIVER",
            "UC_CHROMEDRIVER",
        )

        options = uc.ChromeOptions()
        options.binary_location = chrome_path
        options.add_argument("--lang=en-US,en")
        options.add_argument("--window-size=1365,900")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--no-first-run")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")

        self._uc_driver = uc.Chrome(
            options=options,
            user_data_dir=profile_dir,
            driver_executable_path=driver_path or None,
            browser_executable_path=chrome_path,
            version_main=_chrome_major_version(chrome_path),
            port=port,
            headless=headless,
            use_subprocess=True,
        )
        await self._wait_for_cdp(port, "undetected-chromedriver Chrome")
        await self._connect_cdp(f"http://127.0.0.1:{port}")

    async def _wait_for_cdp(self, port: int, label: str, timeout_sec: float = 20.0):
        """Wait until Chrome exposes /json/version on the requested CDP port."""
        import urllib.request

        last_error = None
        attempts = max(1, int(timeout_sec * 2))
        for _ in range(attempts):
            await asyncio.sleep(0.5)
            try:
                data = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=2
                ).read()
                info = json.loads(data)
                self._ws_url = info["webSocketDebuggerUrl"]
                return
            except Exception as exc:  # noqa: BLE001 - diagnostic retry loop
                last_error = exc
        raise RuntimeError(f"{label} did not expose CDP on port {port}: {last_error}")

    async def _connect_cdp(self, http_url):
        """Connect to Chrome via CDP WebSocket."""
        import urllib.request

        try:
            data = urllib.request.urlopen(f"{http_url}/json/version", timeout=5).read()
            info = json.loads(data)
            self._ws_url = info["webSocketDebuggerUrl"]
        except Exception as e:
            raise RuntimeError(f"Cannot connect to Chrome at {http_url}: {e}")

        pages = json.loads(urllib.request.urlopen(f"{http_url}/json/list", timeout=5).read())
        page_targets = [p for p in pages if p.get("type") == "page"]
        if page_targets:
            self._page_target = page_targets[0]["webSocketDebuggerUrl"]
        else:
            new_tab = json.loads(urllib.request.urlopen(f"{http_url}/json/new?about:blank", timeout=5).read())
            self._page_target = new_tab["webSocketDebuggerUrl"]

        if not websockets:
            raise RuntimeError("websockets package required: pip install websockets")
        self._ws = await websockets.connect(self._page_target, max_size=10 * 1024 * 1024)

    async def _cdp_send(self, method, params=None):
        """Send a CDP command and return the result."""
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        await self._ws.send(json.dumps(msg))
        while True:
            resp = json.loads(await self._ws.recv())
            if resp.get("id") == self._msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP error: {resp['error']}")
                return resp.get("result", {})

    async def _evaluate(self, expression):
        """Evaluate JS in the page and return the result."""
        result = await self._cdp_send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        })
        val = result.get("result", {}).get("value")
        exc = result.get("exceptionDetails")
        if exc:
            desc = exc.get("exception", {}).get("description", exc.get("text", str(exc)))
            raise RuntimeError(f"JS error: {desc}")
        return val

    async def _navigate(self, url):
        """Navigate the page to a URL and wait for load."""
        await self._cdp_send("Page.enable")
        await self._cdp_send("Page.navigate", {"url": url})
        for _ in range(60):
            msg = json.loads(await self._ws.recv())
            if msg.get("method") == "Page.loadEventFired":
                break
        await asyncio.sleep(1)

    async def _warmup(self):
        """Navigate to Google search to verify cookies and warm up the session.

        Uses google.com (not .hk) so AI Overview eligibility is detected
        correctly for the user's region. The page may redirect to .hk on
        its own; both render AI Overview identically.
        """
        await self._navigate("https://www.google.com/search?q=hello&hl=en&gl=us")
        url = await self._evaluate("window.location.href")
        if "/sorry/" in (url or ""):
            raise RuntimeError(
                "Google CAPTCHA during warmup. Try a visible persistent profile, "
                "an existing Chrome via --cdp-url, or --browser-backend undetected --no-headless."
            )

    async def ask(self, question: str, timeout_ms: int = 45000) -> str:
        """Ask a question via Google Search and return the AI Overview answer.

        On miss, falls back to top organic results.
        Returns a plain string for MCP tool compatibility. The dict result
        is logged to stderr for debugging.
        """
        async with self._lock:
            from urllib.parse import quote
            url = f"https://www.google.com/search?q={quote(question)}&hl=en&gl=us"
            await self._navigate(url)
            # Wait for DOM to settle
            await asyncio.sleep(2)
            js = _ASK_JS.replace("%QUERY%", json.dumps(question))
            try:
                result = await asyncio.wait_for(self._evaluate(js), timeout=timeout_ms / 1000)
            except asyncio.TimeoutError:
                raise RuntimeError("Query timed out")
            except Exception:
                await self._warmup()
                await self._navigate(url)
                await asyncio.sleep(2)
                result = await self._evaluate(js)

        if isinstance(result, dict):
            if result.get("error"):
                raise RuntimeError(f"{result['error']}: {result.get('finalUrl','')}")
            answer = result.get("answer", "")
            sources = result.get("sources", [])
            source_label = result.get("source", "unknown")
            elapsed = result.get("elapsed_ms", 0)

            if sources:
                # Append source citations as footer
                source_lines = []
                for i, s in enumerate(sources[:5], 1):
                    title = s.get("title", s.get("url", ""))
                    url_s = s.get("url", "")
                    source_lines.append(f"  [{i}] {title} - {url_s}")
                answer = f"{answer}\n\nSources ({source_label}, {elapsed}ms):\n" + "\n".join(source_lines)
            return answer or "(no answer)"
        return str(result) if result else ""

    async def ask_stream(self, question: str, timeout_ms: int = 45000):
        """Yield answer in one chunk (AI Overview DOM is single-pass)."""
        text = await self.ask(question, timeout_ms)
        if text:
            yield text

    async def stop(self):
        """Shutdown browser resources and remove owned temporary profile."""
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._uc_driver:
            try:
                self._uc_driver.quit()
            except Exception:
                pass
            self._uc_driver = None
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
            self._proc = None
        if self._user_data_dir:
            if self._owns_user_data_dir:
                shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = None
            self._owns_user_data_dir = False


async def e2e_test():
    import time

    cdp = os.environ.get("CDP_URL")
    channel = os.environ.get("BROWSER_CHANNEL", "chrome")
    headless = os.environ.get("HEADLESS", "1") != "0"
    browser_backend = os.environ.get("GEMINI_SEARCH_BROWSER_BACKEND")
    user_data_dir = os.environ.get("GEMINI_SEARCH_USER_DATA_DIR")
    proxy_server = os.environ.get("GEMINI_SEARCH_PROXY_SERVER")
    chromedriver_path = os.environ.get("GEMINI_SEARCH_CHROMEDRIVER") or os.environ.get("UC_CHROMEDRIVER")
    engine = AIModeEngine()
    print(
        f"Starting... "
        f"(cdp={cdp or 'self-launch'}, backend={browser_backend or 'subprocess'}, "
        f"channel={channel}, headless={headless})"
    )
    t0 = time.time()
    await engine.start(
        cdp_url=cdp,
        headless=headless,
        channel=channel,
        user_data_dir=user_data_dir,
        browser_backend=browser_backend,
        proxy_server=proxy_server,
        chromedriver_path=chromedriver_path,
    )
    print(f"  Ready in {time.time()-t0:.1f}s")

    tests = [
        ("math", "what is 7*8? answer only the number"),
        ("web", "what is the current bitcoin price in USD today?"),
        ("chinese", "用中文简要介绍量子计算, 不超过2句话"),
    ]
    passed = 0
    for name, q in tests:
        t0 = time.time()
        try:
            ans = await engine.ask(q)
            print(f"  [{name}] ({time.time()-t0:.1f}s): {ans[:200]}")
            if ans:
                passed += 1
        except Exception as e:
            print(f"  [{name}] ERROR: {e}")

    await engine.stop()
    print(f"\n{'PASSED' if passed == len(tests) else 'PARTIAL'} ({passed}/{len(tests)})")


if __name__ == "__main__":
    asyncio.run(e2e_test())