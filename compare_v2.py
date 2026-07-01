"""Compare AI Mode (cn fork, headed) vs Tavily on 13 queries."""
import asyncio
import json
import os
import time
from pathlib import Path

import httpx

from queries import QUERIES
from gemini_search.engine import AIModeEngine

GEMINI_USER_DATA_DIR = "C:/Users/22975/mcp-tools/gemini-search-mcp-cn/.chrome-profile-us"
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "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")

TAVILY_URL = "https://api.tavily.com/search"


async def run_gemini(engine: AIModeEngine):
    results = []
    for name, query, lang in QUERIES:
        t0 = time.time()
        error = None
        answer = ""
        try:
            answer = await engine.ask(query, timeout_ms=60000)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        elapsed = time.time() - t0
        results.append({
            "name": name, "query": query, "lang": lang,
            "backend": "gemini_search_cn",
            "answer": answer,
            "elapsed_sec": round(elapsed, 2),
            "error": error,
            "char_count": len(answer),
        })
        print(f"  [gemini] {name} {elapsed:.1f}s {len(answer)}c", flush=True)
    return results


async def run_tavily():
    results = []
    async with httpx.AsyncClient(timeout=60) as client:
        for name, query, lang in QUERIES:
            t0 = time.time()
            error = None
            try:
                r = await client.post(TAVILY_URL, json={
                    "api_key": TAVILY_API_KEY, "query": query,
                    "max_results": 5, "include_answer": True, "search_depth": "advanced",
                })
                r.raise_for_status()
                data = r.json()
                answer = data.get("answer", "")
                results_list = data.get("results", [])
                if not answer:
                    answer = "\n".join(
                        f"[{i+1}] {x.get('title','')}\n{x.get('content','')}\n{x.get('url','')}"
                        for i, x in enumerate(results_list[:5])
                    ) or "(no answer)"
                results.append({
                    "name": name, "query": query, "lang": lang,
                    "backend": "tavily", "answer": answer,
                    "elapsed_sec": round(time.time() - t0, 2),
                    "error": None, "char_count": len(answer),
                })
                print(f"  [tavily] {name} {time.time()-t0:.1f}s {len(answer)}c", flush=True)
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                results.append({
                    "name": name, "query": query, "lang": lang,
                    "backend": "tavily", "answer": "",
                    "elapsed_sec": round(time.time() - t0, 2),
                    "error": error, "char_count": 0,
                })
                print(f"  [tavily] {name} ERROR: {e}", flush=True)
    return results


async def main():
    out_dir = Path("D:/gemini-search-comparison")
    out_dir.mkdir(exist_ok=True, parents=True)

    print("=" * 60)
    print("Initializing Gemini Search engine (HEADED + US profile)...")
    print("=" * 60)
    engine = AIModeEngine()
    t0 = time.time()
    await engine.start(
        headless=False,  # HEADED for AI Mode
        channel="chrome",
        user_data_dir=GEMINI_USER_DATA_DIR,
    )
    print(f"[startup] {time.time()-t0:.1f}s, AI Mode: {engine._supports_aimode}")
    if not engine._supports_aimode:
        print("[WARN] AI Mode not available - falling back to organic. Check IP/profile.")

    try:
        print()
        print("=" * 60)
        print("Running Gemini Search queries...")
        print("=" * 60)
        gemini_results = await run_gemini(engine)

        print()
        print("=" * 60)
        print("Running Tavily queries...")
        print("=" * 60)
        tavily_results = await run_tavily()

        all_results = {
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_queries": len(QUERIES),
                "gemini_user_data_dir": GEMINI_USER_DATA_DIR,
                "gemini_search_version": "0.4.0-cn-fork-v2",
                "gemini_mode": "headed_aimode",
            },
            "queries": [
                {
                    "name": q[0], "query": q[1], "lang": q[2],
                    "gemini": next((r for r in gemini_results if r["name"] == q[0]), None),
                    "tavily": next((r for r in tavily_results if r["name"] == q[0]), None),
                }
                for q in QUERIES
            ],
        }
        out_path = out_dir / "results-v2.json"
        out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[OK] Wrote {out_path}")
        print(f"  Size: {out_path.stat().st_size / 1024:.1f} KB")
    finally:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())