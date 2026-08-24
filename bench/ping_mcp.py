"""MCP 콜이 되는지만 본다 — LLM 없이 서버에 직접 붙는다.

    python bench/ping_mcp.py                      도구 목록 + spot_details 한 방
    python bench/ping_mcp.py evaluate_place "{\"name\":\"섭지코지\"}"
"""
import asyncio
import json
import os
import sys

from fastmcp import Client

# 로컬·도커·ngrok 공개 주소를 같은 스크립트로 찌른다.
#     set MCP_URL=https://xxxx.ngrok.app/
URL = os.getenv("MCP_URL", "http://127.0.0.1:11000/")


async def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "spot_details"
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {"name": "새별오름"}

    print(f"붙는 곳: {URL}", file=sys.stderr)
    async with Client(URL) as mcp:
        tools = await mcp.list_tools()
        print("도구:", [t.name for t in tools])
        result = await mcp.call_tool(name, args)
        print(f"\n{name}({json.dumps(args, ensure_ascii=False)}) →")
        print(json.dumps(result.data, ensure_ascii=False, indent=2))


asyncio.run(main())
