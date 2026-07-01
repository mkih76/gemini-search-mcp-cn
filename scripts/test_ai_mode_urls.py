"""Test AI Mode availability with different URL/param combinations."""
import asyncio, json, subprocess, time, urllib.request
import websockets

PORT = 19250
PROFILE = "C:/Users/22975/mcp-tools/gemini-search-mcp/.chrome-profile"

def wait_for_cdp(port):
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2).read()
            return True
        except: time.sleep(0.5)
    return False

async def main():
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    proc = subprocess.Popen([
        chrome, f"--remote-debugging-port={PORT}",
        f"--user-data-dir={PROFILE}", "--headless=new",
        "--no-first-run", "--no-default-browser-check",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_cdp(PORT)
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list").read())
        page = [t for t in targets if t.get("type") == "page"][0]
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=20*1024*1024) as ws:
            mid = 0
            async def send(m, p=None):
                nonlocal mid; mid += 1
                await ws.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == mid: return r.get("result", {})

            await send("Page.enable")
            # Try multiple URL forms
            urls = [
                "https://www.google.com/search?q=capital+of+france&hl=en&gl=us&udm=50",
                "https://www.google.com/search?q=capital+of+france",
                "https://www.google.com/search?q=capital+of+france&hl=zh-CN&gl=cn",
            ]
            for url in urls:
                print(f"\n=== URL: {url}")
                await send("Page.navigate", {"url": url})
                for _ in range(60):
                    m = json.loads(await ws.recv())
                    if m.get("method") == "Page.loadEventFired": break
                await asyncio.sleep(4)
                r = await send("Runtime.evaluate", {
                    "expression": """({
                        url: window.location.href,
                        title: document.title,
                        bodySample: document.body.innerText.substring(0, 400),
                        hasAISnippet: !!window.google?.sn && window.google.sn.includes('aim'),
                        cookieCount: document.cookie.split(';').length,
                    })""",
                    "returnByValue": True,
                })
                v = r.get("result", {}).get("value", {})
                print(f"  url:    {v.get('url', '')[:100]}")
                print(f"  title:  {v.get('title')}")
                print(f"  body:   {v.get('bodySample', '')[:200]}")
                print(f"  aim?:   {v.get('hasAISnippet')}")

    finally:
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()

asyncio.run(main())