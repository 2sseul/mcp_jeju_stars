"""서버 진입점 — 도구 등록과 전송(transport)만 담당한다.

fastmcp v2 · stateless · streamable HTTP `/mcp`.

판정 로직은 `server/tools.py` 에 순수 함수로 있고, 이 파일은 그것을 MCP 도구로
**등록**하기만 한다. 데코레이터(`@mcp.tool`)를 쓰지 않고 이미 정의된 함수를 넘기는
형태(`mcp.tool(tools.recommend_spots)`)인 것은 의도적이다 — fastmcp v2 의 `@mcp.tool`
은 함수 자리에 `FunctionTool` 객체를 남기므로, 데코레이터를 쓰면 `tools.recommend_spots`
가 더 이상 평범한 파이썬 함수가 아니게 된다. 여기서 등록만 하면 판정 함수는 그대로
호출 가능한 함수로 남아 테스트·스크립트가 SDK 내부 속성(`.fn`)에 기대지 않는다.

도구는 **사용자 질문의 목적**으로 셋이다 — 어디로 갈까(추천) · 여기 별 보여?(평가) ·
거기 어때?(상세). 좌표냐 지명이냐는 입력 형태일 뿐이라 도구를 가르지 않는다.

도구 설명(LLM 이 읽는 것)은 `tools.py` 의 docstring 그대로다. fastmcp 가 함수의
시그니처와 docstring 에서 입력 스키마·설명을 뽑으므로, 계약이 한 곳에만 있다.

바인딩 주소는 환경변수로 뺀다 — 로컬은 루프백, 컨테이너는 0.0.0.0 이어야 포트가
밖으로 열린다(Dockerfile 이 MCP_HOST 를 지정한다).

실행:
    uv run python -m server.app            → http://127.0.0.1:8000/mcp
    docker run -p 8000:8000 jeju-star      → http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse

from server import maps, tools

HOST = os.getenv("MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_PORT", "8000"))

mcp = FastMCP("jeju-star")

# 외부 LLM 호스트가 여러 세션을 붙여도 서버는 상태를 들고 있지 않는다(stateless).
# 판정은 매 호출 좌표·시각만으로 결정되므로 세션에 남길 것이 없다.
mcp.tool(tools.recommend_spots)
mcp.tool(tools.evaluate_place)
mcp.tool(tools.spot_details)


# 도구가 만든 경로 지도를 이 서버가 직접 서빙한다(`plan.md` P13 — 정적 HTML → URL).
# 별도 웹서버를 세우지 않는 것은 포트가 하나면 컨테이너 노출도 하나로 끝나서다.
# 이름은 내용 해시라 세션 상태가 생기지 않고, `maps.read` 가 모양을 검사해
# 경로 탈출을 막는다.
@mcp.custom_route("/maps/{name}", methods=["GET"])
async def serve_map(request: Request):
    document = maps.read(request.path_params["name"])
    if document is None:
        return PlainTextResponse("지도를 찾을 수 없습니다.", status_code=404)
    return HTMLResponse(document)


def main() -> None:
    mcp.run(transport="http", host=HOST, port=PORT, stateless_http=True)


if __name__ == "__main__":
    main()
