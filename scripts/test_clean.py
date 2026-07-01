"""Probe google.com (no .hk) with Accept-Language en-US."""
import asyncio, json, subprocess, time, urllib.request
import websockets

PORT = 19251  # different port
PROFILE = "C:/Users/22975/mcp-tools/gemini-search-mcp/.chrome-profile"

def wait_for_cdp(port):
    for _ in range(40):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2).read(); return True
        except: time.sleep(0.5)
    return False

async def main():
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    proc = subprocess.Popen([
        chrome, f"--remote-debugging-port={PORT}",
        f"--user-data-dir={PROFILE}", "--headless=new",
        "--no-first-run", "--no-default-browser-check",
        "--lang=en-US", "--accept-lang=en-US,en",
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

            await send("Network.enable")
            await send("Network.setExtraHTTPHeaders", {
                "headers": {"Accept-Language": "en-US,en;q=0.9"}
            })
            await send("Page.enable")

            queries = ["what is the capital of France", "Bitcoin price today USD", "2026年最新个税政策"]
            for q in queries:
                from urllib.parse import quote
                url = f"https://www.google.com/search?q={quote(q)}&hl=en&gl=us&pws=0"
                print(f"\n=== {q}")
                print(f"  URL: {url}")
                await send("Page.navigate", {"url": url})
                for _ in range(60):
                    m = json.loads(await ws.recv())
                    if m.get("method") == "Page.loadEventFired": break
                await asyncio.sleep(5)

                r = await send("Runtime.evaluate", {
                    "expression": """({
                        finalUrl: window.location.href,
                        hasAIOverview: !!document.querySelector('[data-attrid="AIOverview"]'),
                        bodyText: document.body.innerText.substring(0, 800),
                    })""",
                    "returnByValue": True,
                })
                v = r.get("result", {}).get("value", {})
                print(f"  Final URL: {v.get('finalUrl', '')[:100]}")
                print(f"  AI Overview: {v.get('hasAIOverview')}")
                print(f"  Body:")
                print(v.get("bodyText", "")[:600])

    finally:
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()

asyncio.run(main())