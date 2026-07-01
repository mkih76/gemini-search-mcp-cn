"""Prime Chrome with active navigation + CAPTCHA detection.

Unlike prime_chrome.py (which trusts the user), this script:
1. Launches visible Chrome with --remote-debugging-port=19250
2. Connects via CDP and navigates to google.com.hk/search?q=hello
3. Polls every 3s, reports whether the page is /sorry/ (CAPTCHA) or normal results
4. Auto-exits when the user closes the window OR after timeout
5. On exit, prints final verdict so we know whether cookies are good

Usage:
    python prime_chrome_v2.py --profile-dir <path>
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
PORT = 19250


def find_chrome() -> str:
    for p in CHROME_PATHS:
        if os.path.isfile(p):
            return p
    raise RuntimeError("Chrome not found")


def wait_for_cdp(port: int, timeout: float = 20) -> str:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            data = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2
            ).read()
            return json.loads(data)["webSocketDebuggerUrl"]
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    raise RuntimeError(f"CDP not ready: {last_err}")


def list_targets(port: int) -> list:
    data = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/json/list", timeout=5
    ).read()
    return json.loads(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-dir", required=True)
    ap.add_argument("--wait-seconds", type=int, default=240)
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    profile_dir = os.path.abspath(args.profile_dir)
    os.makedirs(profile_dir, exist_ok=True)

    chrome = find_chrome()
    print(f"Chrome:  {chrome}")
    print(f"Profile: {profile_dir}")
    print(f"Port:    {args.port}")
    print()

    proc = subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    final_state = {"verdict": "unknown", "url": "", "captcha": False}

    try:
        wait_for_cdp(args.port, timeout=20)
        print(f"[OK] Chrome launched, CDP ready on port {args.port}")

        # Find a page target
        targets = list_targets(args.port)
        page_targets = [t for t in targets if t.get("type") == "page"]
        if not page_targets:
            # Open a new tab
            urllib.request.urlopen(
                f"http://127.0.0.1:{args.port}/json/new?about:blank", timeout=5
            ).read()
            targets = list_targets(args.port)
            page_targets = [t for t in targets if t.get("type") == "page"]

        target = page_targets[0]
        ws_url = target["webSocketDebuggerUrl"]
        print(f"[OK] Page target: {target.get('url', 'about:blank')[:80]}")

        # Connect websocket via simple client
        import asyncio
        try:
            import websockets
        except ImportError:
            print("[ERR] websockets not installed")
            return 1

        async def cdp_session():
            async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
                msg_id = 0

                async def send(method, params=None):
                    nonlocal msg_id
                    msg_id += 1
                    await ws.send(json.dumps({
                        "id": msg_id, "method": method, "params": params or {}
                    }))
                    while True:
                        resp = json.loads(await ws.recv())
                        if resp.get("id") == msg_id:
                            if "error" in resp:
                                raise RuntimeError(resp["error"])
                            return resp.get("result", {})

                # Navigate to Google
                await send("Page.enable")
                await send("Page.navigate", {
                    "url": "https://www.google.com.hk/search?q=hello&hl=en&gl=us"
                })
                # Wait for load
                for _ in range(60):
                    msg = json.loads(await ws.recv())
                    if msg.get("method") == "Page.loadEventFired":
                        break
                await asyncio.sleep(2)

                # Poll the URL state for up to wait_seconds
                print()
                print("=" * 60)
                print("Polling page state every 4s. Solve CAPTCHA if /sorry/ shows.")
                print("Close the window when done, or wait for timeout.")
                print("=" * 60)
                print()

                deadline = time.time() + args.wait_seconds
                last_state = None
                async def get_url():
                    r = await send("Runtime.evaluate", {
                        "expression": "window.location.href",
                        "returnByValue": True,
                    })
                    return r.get("result", {}).get("value", "")

                while time.time() < deadline:
                    if proc.poll() is not None:
                        print("[INFO] Chrome window closed.")
                        break
                    try:
                        url = await get_url()
                    except Exception as e:
                        await asyncio.sleep(2)
                        continue
                    is_captcha = "/sorry/" in url
                    state = "CAPTCHA" if is_captcha else ("OK" if "google.com" in url else "?")
                    if state != last_state:
                        ts = time.strftime("%H:%M:%S")
                        print(f"  [{ts}] {state:8s} {url[:90]}")
                        last_state = state
                    if not is_captcha and "google.com" in url and "q=hello" in url:
                        # We got past the CAPTCHA gate. Give it a few more seconds
                        # to make sure user isn't still typing/solving.
                        print()
                        print("[WAIT] 8s grace period for cookie finalization...")
                        await asyncio.sleep(8)
                        final_url = await get_url()
                        final_state["url"] = final_url
                        final_state["captcha"] = "/sorry/" in final_url
                        if not final_state["captcha"]:
                            final_state["verdict"] = "success"
                        break
                    await asyncio.sleep(4)
                else:
                    print(f"[TIMEOUT] {args.wait_seconds}s elapsed.")

        asyncio.run(cdp_session())

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    print()
    print("=" * 60)
    print(f"FINAL VERDICT: {final_state['verdict'].upper()}")
    print(f"  Last URL: {final_state['url'][:120]}")
    print(f"  CAPTCHA:  {final_state['captcha']}")
    print("=" * 60)

    if final_state["verdict"] != "success":
        print()
        print("Next attempt will likely still hit CAPTCHA.")
        print("Try: visit google.com normally, do a few searches, browse around,")
        print("then re-run this priming script.")

    return 0 if final_state["verdict"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
