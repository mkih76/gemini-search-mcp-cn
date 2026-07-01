"""Run all comparison queries on Gemini Search (cn fork) and Tavily.

Output: results.json with structured data for report generation.
"""
import asyncio
import json
import os
import time
from pathlib import Path

import httpx

from queries import QUERIES
from gemini_search.engine import AIModeEngine

GEMINI_USER_DATA_DIR = "C:/Users/22975/mcp-tools/gemini-search-mcp-cn/.chrome-profile"
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

# Tavily API doc: https://docs.tavily.com/docs/rest-api/api-reference
TAVILY_URL = "https://api.tavily.com/search"


async def run_gemini(engine: AIModeEngine):
    """Run all queries through Gemini Search engine."""
    results = []
    for name, query, lang in QUERIES:
        t0 = time.time()
        error = None
        answer = ""
        try:
            answer = await engine.ask(query, timeout_ms=30000)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        elapsed = time.time() - t0
        results.append({
            "name": name,
            "query": query,
            "lang": lang,
            "backend": "gemini_search_cn",
            "answer": answer,
            "elapsed_sec": round(elapsed, 2),
            "error": error,
            "char_count": len(answer),
        })
        print(f"  [gemini] {name} {elapsed:.1f}s {len(answer)}c", flush=True)
    return results


async def run_tavily():
    """Run all queries through Tavily API."""
    if not TAVILY_API_KEY:
        print("[WARN] TAVILY_API_KEY not set, skipping Tavily")
        return []
    results = []
    async with httpx.AsyncClient(timeout=60) as client:
        for name, query, lang in QUERIES:
            t0 = time.time()
            error = None
            data = {}
            try:
                r = await client.post(TAVILY_URL, json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "max_results": 5,
                    "include_answer": True,
                    "search_depth": "advanced",
                })
                r.raise_for_status()
                data = r.json()
                answer = data.get("answer", "")
                results_list = data.get("results", [])
                formatted = answer if answer else "\n".join(
                    f"[{i+1}] {r.get('title','')}\n{r.get('content','')}\n{r.get('url','')}"
                    for i, r in enumerate(results_list[:5])
                )
                if not formatted:
                    formatted = "(no answer)"
                results.append({
                    "name": name,
                    "query": query,
                    "lang": lang,
                    "backend": "tavily",
                    "answer": formatted,
                    "elapsed_sec": round(time.time() - t0, 2),
                    "error": None,
                    "char_count": len(formatted),
                    "raw": data,
                })
                print(f"  [tavily] {name} {time.time()-t0:.1f}s {len(formatted)}c", flush=True)
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                results.append({
                    "name": name,
                    "query": query,
                    "lang": lang,
                    "backend": "tavily",
                    "answer": "",
                    "elapsed_sec": round(time.time() - t0, 2),
                    "error": error,
                    "char_count": 0,
                })
                print(f"  [tavily] {name} ERROR: {e}", flush=True)
    return results


async def main():
    out_dir = Path("D:/gemini-search-comparison")
    out_dir.mkdir(exist_ok=True, parents=True)

    print("=" * 60)
    print("Initializing Gemini Search engine...")
    print("=" * 60)
    engine = AIModeEngine()
    t0 = time.time()
    await engine.start(
        headless=True,
        channel="chrome",
        user_data_dir=GEMINI_USER_DATA_DIR,
    )
    print(f"[startup] {time.time()-t0:.1f}s")

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

        # Combine
        all_results = {
            "metadata": {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_queries": len(QUERIES),
                "gemini_user_data_dir": GEMINI_USER_DATA_DIR,
                "gemini_search_version": "0.4.0-cn-fork",
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
        out_path = out_dir / "results.json"
        out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[OK] Wrote {out_path}")
        print(f"  Size: {out_path.stat().st_size / 1024:.1f} KB")

    finally:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())