"""Probe whether AI Mode renders answers directly in the DOM."""
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
            await send("Page.navigate", {"url": "https://www.google.com.hk/search?q=what+is+the+capital+of+France&hl=en&gl=us&udm=50"})
            for _ in range(60):
                m = json.loads(await ws.recv())
                if m.get("method") == "Page.loadEventFired": break
            # Wait extra for AI Mode to render
            await asyncio.sleep(6)

            # Check what DOM has
            r = await send("Runtime.evaluate", {
                "expression": """({
                    title: document.title,
                    hasPTRUV: !!document.querySelector('.pTRUV'),
                    pTRUVCount: document.querySelectorAll('.pTRUV').length,
                    hasN6owBd: !!document.querySelector('.n6owBd'),
                    n6owBdCount: document.querySelectorAll('.n6owBd').length,
                    hasMZBHN: !!document.querySelector('.MZBHN'),
                    mzbhnText: (document.querySelector('.MZBHN') || {}).innerText || null,
                    bodyLen: document.body.innerText.length,
                    bodyPreview: document.body.innerText.substring(0, 500),
                })""",
                "returnByValue": True,
            })
            print("DOM probe:")
            print(json.dumps(r.get("result", {}).get("value"), indent=2, ensure_ascii=False))

    finally:
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()

asyncio.run(main())