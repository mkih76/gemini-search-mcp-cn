"""Find which element contains the AI Overview answer text."""
import asyncio, json, subprocess, time, urllib.request
from urllib.parse import quote
import websockets

PORT = 19252
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
            url = f"https://www.google.com/search?q={quote('what is the capital of France')}&hl=en&gl=us"
            await send("Page.navigate", {"url": url})
            for _ in range(60):
                m = json.loads(await ws.recv())
                if m.get("method") == "Page.loadEventFired": break
            await asyncio.sleep(6)

            # Hunt for element containing "The capital of France is Paris"
            r = await send("Runtime.evaluate", {
                "expression": """(() => {
                    const target = 'The capital of France is Paris';
                    // Find any element whose text contains the answer
                    const matches = [];
                    const walk = (el, depth) => {
                        if (depth > 20) return;
                        if (!el) return;
                        const txt = (el.innerText || '').trim();
                        if (txt.includes(target) && txt.length < 2000) {
                            matches.push({
                                tag: el.tagName,
                                cls: el.className || '',
                                attrid: el.getAttribute('data-attrid') || '',
                                id: el.id || '',
                                len: txt.length,
                                preview: txt.substring(0, 150),
                            });
                        }
                        for (const c of el.children) walk(c, depth+1);
                    };
                    walk(document.body, 0);
                    return matches.slice(0, 10);
                })()""",
                "returnByValue": True,
            })
            v = r.get("result", {}).get("value", [])
            print(f"Found {len(v)} matching elements:")
            for m in v:
                print(json.dumps(m, ensure_ascii=False, indent=2))

    finally:
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()

asyncio.run(main())