r"""cmd 에서 도구를 직접 불러 보는 클라이언트 — 서버가 떠 있어야 한다.

    python scripts\mcp_call.py                                  도구 목록·스키마
    python scripts\mcp_call.py evaluate_place "{\"query\":\"새별오름\"}"
    python scripts\mcp_call.py recommend_spots "{\"origin\":\"제주공항\",\"max_drive_minutes\":30}"

주소는 --url 로 바꾼다(기본 http://127.0.0.1:11000/). 인자 JSON 은 파일로도 준다:
    python scripts\mcp_call.py evaluate_place @args.json
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client

DEFAULT_URL = os.getenv("MCP_URL", "http://127.0.0.1:11000/")

# cmd 기본 코드페이지(cp949)에는 '—' 같은 글자가 없어 출력이 예외로 죽는다. 한글은
# cp949 로도 나가니 인코딩은 그대로 두고 못 찍는 글자만 바꾼다. 원문 그대로 보려면
# cmd 에서 `chcp 65001` 을 먼저 친다.
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def _load_args(raw: str) -> dict:
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text(encoding="utf-8")
    return json.loads(raw)


async def main() -> int:
    p = argparse.ArgumentParser(description="MCP 도구 호출")
    p.add_argument("tool", nargs="?", help="도구 이름. 없으면 목록만 찍는다")
    p.add_argument("args", nargs="?", default="{}", help="인자 JSON 또는 @파일")
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--schema", action="store_true", help="목록에 입력 스키마까지")
    ns = p.parse_args()

    async with Client(ns.url) as client:
        tools = await client.list_tools()

        if not ns.tool:
            for t in tools:
                print(f"\n■ {t.name}\n  {(t.description or '').strip().splitlines()[0]}")
                if ns.schema:
                    print(json.dumps(t.inputSchema, ensure_ascii=False, indent=2))
                else:
                    props = (t.inputSchema or {}).get("properties", {})
                    print("  인자: " + (", ".join(props) or "없음"))
            return 0

        names = [t.name for t in tools]
        if ns.tool not in names:
            print(f"그런 도구가 없다: {ns.tool}\n있는 것: {', '.join(names)}", file=sys.stderr)
            return 2

        res = await client.call_tool(ns.tool, _load_args(ns.args))
        text = res.content[0].text if res.content else ""
        try:  # 도구 응답은 JSON 문자열이다 — 읽기 좋게 편다
            print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
        except Exception:
            print(text)
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
