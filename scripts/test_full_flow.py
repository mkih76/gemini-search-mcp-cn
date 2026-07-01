"""Replicate the EXACT _ASK_JS logic with full error capture."""
import asyncio, json, subprocess, time, urllib.request
from urllib.parse import quote
import websockets

PORT = 19261
PROFILE = "C:/Users/22975/mcp-tools/gemini-search-mcp-cn/.chrome-profile"

def wait_for_cdp(port):
    for _ in range(40):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2).read(); return True
        except: time.sleep(0.5)
    return False

ASK_JS = """
(async (q) => {
    try {
        const pageUrl = 'https://www.google.com/search?q=' + encodeURIComponent(q) + '&hl=en&gl=us&udm=50&aep=1&ntc=1';
        const r1 = await fetch(pageUrl, {credentials:'include'});
        if (!r1.ok) return {error:'fetch_status_' + r1.status, htmlLen:0};
        const html = await r1.text();
        const m = (p) => { const x = html.match(p); return x ? x[1] : ''; };
        const srtst = m(/data-srtst="([^"]+)"/);
        if (!srtst) return {error:'no_token', htmlLen:html.length, preview:html.substring(0,300)};
        const xsrf = m(/data-xsrf-folwr-token="([^"]+)"/);
        const garc = m(/data-garc="([^"]+)"/);
        const lro = m(/data-lro-token="([^"]+)"/);
        const mlros = m(/data-lro-signature="([^"]+)"/);
        const ei = m(/data-ei="([^"]+)"/);
        const stkp = m(/data-stkp="([^"]+)"/);
        const ved = m(/aria-current="page"[^>]*data-ved="([^"]+)"/);
        const sca = m(/sca_esv=([a-f0-9]+)/);
        const p = new URLSearchParams({srtst,garc,mlro:lro,mlros,ei,q,yv:'3',vet:'1'+ved+'..i',ved,aep:'1',gl:'us',hl:'en',sca_esv:sca,udm:'50',stkp,cs:'0',async:'_fmt:adl,_xsrf:'+xsrf});
        const r2 = await fetch('https://www.google.com/async/folwr?'+p.toString(), {credentials:'include'});
        if (!r2.ok) return {error:'folwr_status_' + r2.status};
        const fh = await r2.text();
        const div = document.createElement('div');
        div.innerHTML = fh;
        div.querySelectorAll('script,style,button,noscript,[aria-hidden="true"],span[style*="display:none"],.LGKDTe,.SGF5Lb').forEach(x => x.remove());
        let parts = [];
        div.querySelectorAll('.pTRUV').forEach(el => {
            const t = el.textContent.trim();
            if (t && t.length > 1) parts.push(t);
        });
        div.querySelectorAll('.n6owBd').forEach(el => {
            const t = el.textContent.trim();
            if (t && t.length > 10) parts.push(t);
        });
        if (!parts.length) {
            div.querySelectorAll('.mZJni,.XEqVsf,.ub891').forEach(x => x.remove());
            div.querySelectorAll('[dir="ltr"]').forEach(el => {
                const t = el.textContent.trim();
                if (t.length > 30) parts.push(t);
            });
        }
        let text = parts.join('\\n\\n');
        const noise = ['Copy','Share','Good response','Bad response','About this result','Show all','AI responses may include mistakes','Tell me which'];
        for (const n of noise) { while (text.endsWith(n)) text = text.slice(0, -n.length).trim(); }
        return {ok:true, answer:text, folwrLen:fh.length};
    } catch(e) {
        return {error:'js_exception', message:e.message, stack: e.stack};
    }
})(%QUERY%)
"""

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

            # Warmup with normal Google search
            print("Warmup...")
            await send("Page.navigate", {"url": "https://www.google.com/search?q=hello&hl=en&gl=us"})
            for _ in range(60):
                m = json.loads(await ws.recv())
                if m.get("method") == "Page.loadEventFired": break
            await asyncio.sleep(3)

            # Now run the actual _ASK_JS
            for query in ["capital of France", "Bitcoin price today", "what is the capital of Australia"]:
                print(f"\n=== Query: {query}")
                js = ASK_JS.replace("%QUERY%", json.dumps(query))
                r = await send("Runtime.evaluate", {
                    "expression": js,
                    "awaitPromise": True, "returnByValue": True,
                })
                v = r.get("result", {}).get("value", {})
                print(json.dumps(v, ensure_ascii=False, indent=2)[:1500])

    finally:
        proc.terminate()
        try: proc.wait(5)
        except: proc.kill()

asyncio.run(main())