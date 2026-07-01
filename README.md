# gemini-search-mcp (cn fork)

Free MCP server for web search powered by Google AI Mode (Gemini). Forked
from [Sophomoresty/gemini-search-mcp](https://github.com/Sophomoresty/gemini-search-mcp)
with adaptations for non-US IP environments.

## What's different from upstream

| Aspect | Upstream | This fork |
|---|---|---|
| Target environment | US IP + headed Chrome + persistent profile | Same, plus auto-fallback for headless/non-US |
| AI Mode flow | folwr token via `google.com.hk` (breaks on non-US) | folwr token via `google.com` + organic SERP fallback |
| Strategy | Single (AI Mode only — fails on non-US) | Dual: AI Mode (headed) + organic SERP (headless) |
| Login required | No | No |

## Quick start

```bash
# 1. Install
pip install -e .

# 2. Prime a persistent Chrome profile (headed, manual CAPTCHA solve if prompted)
python scripts/prime_chrome_v2.py --profile-dir ~/.cache/gemini-search/chrome-profile

# 3. Add to your MCP config (Claude Desktop, Hermes, etc.)
```

MCP server config:

```json
{
  "mcpServers": {
    "gemini-search": {
      "command": "python",
      "args": ["-m", "gemini_search_mcp"],
      "env": {
        "GEMINI_SEARCH_USER_DATA_DIR": "~/.cache/gemini-search/chrome-profile",
        "HEADLESS": "0",
        "BROWSER_CHANNEL": "chrome"
      }
    }
  }
}
```

## Requirements for AI Mode (full quality)

Google AI Mode is gated by 3 things:

1. **headed Chrome window** — `--headless=new` triggers `/sorry/` CAPTCHA
2. **persistent profile** — fresh profiles get 91KB JS shell instead of 360KB token page
3. **US-region IP** — non-US IPs see "AI Mode is not currently available on your device or account"

When all three are met, the engine auto-detects AI Mode availability during `_warmup` and uses it. When any fails, it falls back to organic SERP extraction (still 5 results with links, just not AI-synthesized).

## Headless fallback

Set `HEADLESS=1` to run without a visible window. The engine will:
- Use the persistent profile (still required)
- Detect that AI Mode is blocked (91KB shell, no `data-srtst` token)
- Fall back to extracting top 5 organic Google results from the rendered DOM

Answer quality is lower (snippet concat vs Gemini synthesis) but stable and fast.

## MCP tools

| Tool | Description |
|---|---|
| `web_search(query)` | Search the web and get a synthesized answer grounded in real-time results |
| `ask(prompt)` | General question — Gemini Search decides whether to search the web |

## Architecture

```
Agent calls web_search("query")
  → Chrome Runtime.evaluate (CDP via websockets)
    → _warmup: navigate to google.com/search?q=hello (no udm)
      → builds cookie session (NID, AEC, SNID)
    → Probe AI Mode: fetch google.com/search?q=test&udm=50
      → if has data-srtst token → AI Mode enabled
      → if 91KB shell or /sorry/ → organic fallback
    → ask():
      [AI Mode path]
      → fetch AI Mode URL (udm=50&aep=1&ntc=1)
      → extract data-srtst, data-xsrf-folwr-token, data-garc, etc.
      → POST to /async/folwr endpoint
      → parse .pTRUV + .n6owBd blocks from HTML
      [Organic path]
      → navigate to /search?q=...
      → extract top 5 div.g blocks from rendered DOM
```

## Files

- `gemini_search/engine.py` — Chrome CDP engine, dual strategy
- `gemini_search_mcp/` — FastMCP server exposing `web_search` + `ask` tools
- `gemini_search/server.py` — OpenAI-compatible API server (`gemini-search --port 8080`)
- `scripts/prime_chrome_v2.py` — headed CAPTCHA priming helper
- `scripts/uc_google_probe.py` — undetected-chromedriver probe (for advanced CAPTCHA bypass)
- `scripts/windows_chrome_profile_probe.py` — Windows-specific two-phase profile verifier
- `compare_v2.py` — Gemini Search vs Tavily comparison harness (13 queries)
- `generate_report_v2.py` — generates markdown report from results JSON

## License

MIT (same as upstream)