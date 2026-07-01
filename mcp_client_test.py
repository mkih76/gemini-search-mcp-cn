"""Minimal MCP stdio client to test gemini-search-mcp end-to-end.

Uses JSON-RPC over stdin/stdout as MCP spec requires.
"""
import asyncio
import json
import os
import subprocess
import sys
import time

PROFILE = "C:/Users/22975/mcp-tools/gemini-search-mcp-cn/.chrome-profile-us"


async def send_message(proc, msg_id, method, params=None):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line.encode("utf-8"))
    await proc.stdin.drain()
    print(f"--> {method}", flush=True)


async def read_response(proc, timeout=60):
    try:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    if not line:
        return None
    try:
        return json.loads(line.decode("utf-8").strip())
    except json.JSONDecodeError:
        return {"raw": line.decode("utf-8", errors="replace")}


async def read_until_id(proc, target_id, timeout=60):
    """Read messages until we find one with our target id (skip notifications)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
        except asyncio.TimeoutError:
            continue
        if not line:
            return None
        try:
            data = json.loads(line.decode("utf-8").strip())
        except json.JSONDecodeError:
            continue
        if data.get("id") == target_id:
            return data
        # else: notification (no id) or different request
    return None


async def main():
    env = os.environ.copy()
    env["GEMINI_SEARCH_USER_DATA_DIR"] = PROFILE
    env["HEADLESS"] = "0"
    env["BROWSER_CHANNEL"] = "chrome"

    print(f"Launching: python -m gemini_search_mcp", flush=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "gemini_search_mcp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    async def read_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            sys.stderr.write(f"[mcp-stderr] {line.decode('utf-8', errors='replace')}")
            sys.stderr.flush()

    stderr_task = asyncio.create_task(read_stderr())

    # 1. Initialize
    await send_message(proc, 1, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "0.1"}
    })
    resp = await read_until_id(proc, 1, timeout=60)
    print(f"<-- initialize response: {json.dumps(resp, indent=2)[:500]}", flush=True)

    # 2. initialized notification
    await send_message(proc, None, "notifications/initialized")

    # 3. List tools
    await send_message(proc, 2, "tools/list")
    resp = await read_until_id(proc, 2, timeout=10)
    if resp:
        tools = resp.get("result", {}).get("tools", [])
        print(f"<-- tools/list: {len(tools)} tools", flush=True)
        for t in tools:
            print(f"    - {t.get('name')}: {t.get('description', '')[:100]}", flush=True)
    else:
        print("<-- no tools/list response", flush=True)
        proc.kill()
        return

    # 4. Call web_search 3 times
    queries = [
        "Bitcoin price today USD",
        "what is the capital of France",
        "2026年诺贝尔物理学奖获得者",
    ]
    for i, q in enumerate(queries):
        await send_message(proc, 10 + i, "tools/call", {
            "name": "web_search",
            "arguments": {"query": q}
        })
        resp = await read_until_id(proc, 10 + i, timeout=60)
        if resp:
            result = resp.get("result", {})
            if result.get("isError"):
                print(f"<-- web_search '{q}' ERROR: {result.get('content')}", flush=True)
            else:
                content = result.get("content", [])
                if isinstance(content, list):
                    text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                else:
                    text = str(content)
                print(f"<-- web_search '{q}' ({len(text)}c):", flush=True)
                print(text[:500], flush=True)
                print("---", flush=True)
        else:
            print(f"<-- no response for '{q}'", flush=True)

    proc.terminate()
    await proc.wait()
    stderr_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())