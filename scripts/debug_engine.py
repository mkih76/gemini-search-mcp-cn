"""Debug what Google returns for an AI Mode search. We connect to Chrome via
   CDP, navigate to the same URL the engine uses, and dump the relevant
   attributes from the response HTML.
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = 19250
PROFILE = "C:/Users/22975/mcp-tools/gemini-search-mcp/.chrome-profile"


def wait_for_cdp(port: int, timeout: float = 20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2
            ).read()
            return True
        except Exception:
            time.sleep(0.5)
    return False


async def main():
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    proc = subprocess.Popen(
        [
            chrome, f"--remote-debugging-port={PORT}",
            f"--user-data-dir={PROFILE}",
            "--headless=new", "--no-first-run", "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_for_cdp(PORT, 20):
            print("CDP not ready"); return
        import websockets
        targets = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/json/list", timeout=5
        ).read())
        page = [t for t in targets if t.get("type") == "page"][0]
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=20*1024*1024) as ws:
            mid = 0
            async def send(method, params=None):
                nonlocal mid
                mid += 1
                await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == mid:
                        return r.get("result", {})

            await send("Page.enable")
            url = "https://www.google.com.hk/search?q=hello&hl=en&gl=us&udm=50&aep=1&ntc=1"
            await send("Page.navigate", {"url": url})
            for _ in range(60):
                msg = json.loads(await ws.recv())
                if msg.get("method") == "Page.loadEventFired":
                    break
            await asyncio.sleep(2)

            # Get current URL
            r = await send("Runtime.evaluate", {
                "expression": "window.location.href",
                "returnByValue": True,
            })
            print("Final URL:", r.get("result", {}).get("value"))

            # Try the same fetch the engine does
            r = await send("Runtime.evaluate", {
                "expression": """(async () => {
                    const r1 = await fetch(window.location.href, {credentials:'include'});
                    const html = await r1.text();
                    return {
                        status: r1.status,
                        len: html.length,
                        srtst: !!html.match(/data-srtst="([^"]+)"/),
                        xsrf: !!html.match(/data-xsrf-folwr-token="([^"]+)"/),
                        garc: !!html.match(/data-garc="([^"]+)"/),
                        hasAI: html.includes('AI Mode') || html.includes('AI mode'),
                        hasDivAI: !!document.querySelector('[data-srtst]'),
                        title: document.title,
                    };
                })()""",
                "awaitPromise": True, "returnByValue": True,
            })
            print("Page probe:", json.dumps(r.get("result", {}).get("value"), indent=2))

            # Dump first 500 chars of HTML
            r = await send("Runtime.evaluate", {
                "expression": """(async () => {
                    const r1 = await fetch(window.location.href, {credentials:'include'});
                    const html = await r1.text();
                    return html.substring(0, 800);
                })()""",
                "awaitPromise": True, "returnByValue": True,
            })
            print("HTML preview:", r.get("result", {}).get("value"))

    finally:
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()


asyncio.run(main())