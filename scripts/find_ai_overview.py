"""Find the AI Overview answer selector on google.com (zh-CN)."""
import asyncio, json, subprocess, time, urllib.request
import websockets

PORT = 19250
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
        "--no-first-run", "--no-default-browser-check", "about:blank",
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
            queries = [
                "what is the capital of France",
                "Bitcoin price today USD",
            ]
            for q in queries:
                url = f"https://www.google.com/search?q={q.replace(' ', '+')}&hl=en&gl=us"
                print(f"\n=== Query: {q}")
                await send("Page.navigate", {"url": url})
                for _ in range(60):
                    m = json.loads(await ws.recv())
                    if m.get("method") == "Page.loadEventFired": break
                await asyncio.sleep(5)

                r = await send("Runtime.evaluate", {
                    "expression": """({
                        url: window.location.href,
                        aiOverviewHeader: !!document.querySelector('[data-attrid="AIOverview"]'),
                        // Try common AI Overview selectors
                        selectors: {
                            'AIOverview': document.querySelectorAll('[data-attrid="AIOverview"]').length,
                            'Yb08Nb': document.querySelectorAll('.Yb08Nb').length,
                            'ai_overview_container': document.querySelectorAll('.SzZmKb').length,
                            'data-ai-overview': document.querySelectorAll('[data-hveid][data-md]').length,
                            'mZJni': document.querySelectorAll('.mZJni').length,
                            'n6owBd': document.querySelectorAll('.n6owBd').length,
                            'pTRUV': document.querySelectorAll('.pTRUV').length,
                            'ai-pill': document.querySelectorAll('[aria-label*="AI"]').length,
                        },
                        bodyText: document.body.innerText.substring(0, 1500),
                    })""",
                    "returnByValue": True,
                })
                v = r.get("result", {}).get("value", {})
                print(f"  url: {v.get('url', '')[:100]}")
                print(f"  selectors:")
                for k, n in v.get("selectors", {}).items():
                    if n > 0:
                        print(f"    {k}: {n}")
                print(f"  body:")
                print(v.get("bodyText", ""))

    finally:
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()

asyncio.run(main())