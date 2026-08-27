"""서버 진입점 — REST 앱을 MCP 서버로 바꾸고 전송(transport)만 담당한다.

    server/routes.py  FastAPI 라우트 3개 = MCP 도구 3개 (LLM 이 읽는 계약)
    server/tools.py   판정 본체(순수 함수). MCP 를 모른다
    app.py            REST → MCP 변환 · streamable HTTP · 바인딩 주소

도구를 `@mcp.tool` 로 붙이지 않고 **REST 앱을 통째로 변환**(`FastMCP.from_fastapi`)
하는 것은 등록 게이트웨이가 받는 형태에 맞추기 위해서다. 덕분에 도구 스키마는
FastAPI 의 OpenAPI 문서 한 곳에서 나오고, 판정 함수는 MCP 를 모르는 평범한 함수로
남아 테스트·스크립트가 SDK 내부 속성에 기대지 않는다.

MCP 는 **streamable HTTP** 여야 한다. 경로는 루트(`/`) 이고, 같은 포트로 `/health`
와 경로 지도(`/maps/{name}`)가 함께 나간다 — 이 둘은 겉 앱에 달려 있어 MCP 도구가
되지 않는다(도구가 되는 것은 `api_app` 의 라우트뿐이다).

바인딩 주소는 인자·환경변수로 뺀다 — 로컬은 루프백, 컨테이너는 0.0.0.0 이어야 포트가
밖으로 열린다. 겉으로 내보내는 지도 주소는 `MAP_BASE_URL` 이 따로 정한다(0.0.0.0 은
브라우저가 열 수 있는 주소가 아니다).

실행:
    uv run python app.py                       → http://127.0.0.1:11000/
    docker compose up -d                       → http://127.0.0.1:11000/
"""

import argparse
import asyncio
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).parent))

from server import maps, tiles
from server.routes import register_routes
from server.shared import create_base_app

# Rest API 앱 생성
api_app = create_base_app(
    title="Jeju-Star-API-Server",
    description="제주 밤하늘 관측 조건 판정 - REST API",
    version="1.0",
    docs_url=None,
    redoc_url=None,
)

# 라우트 등록 (라우트 1개 = 도구 1개)
register_routes(api_app)

mcp = FastMCP.from_fastapi(
    api_app,
    name="Jeju-Star-MCP-Server",
    instructions="""제주도 밤하늘 관측을 돕는 서버입니다. 관측지 추천 · 별이 보이는지
판정 · 접근성 조회를 답합니다. 질문의 목적에 따라 도구를 고르세요 (좌표냐 지명이냐로
고르지 않습니다).

주요 기능:
관측지 추천 (recommend_spots)
   - "어디로 갈까" — 출발지·지역·도보·주차·반려동물 조건에 맞는 곳을 검증된 62곳
     중에서 골라 줍니다. 출발지를 주면 실제 도로 기준 주행시간으로 자릅니다.
장소 판정 (evaluate_place)
   - "여기 별 보여?" — 지명이나 좌표로 지목한 한 곳을 판정합니다. 등록되지 않은
     장소도 하늘은 판정하되 주차·야간 출입은 확인되지 않았음을 밝힙니다.
관측지 상세 (spot_details)
   - "거기 어때?" — 검증된 관측지의 주차·도보·야간 출입·반려동물·화장실을 답합니다.

응답에는 사람이 읽는 결론(verdict)·근거(reasons)와 함께 수치(numbers)·출처
(attribution)가 따로 실립니다. 수치는 지어내지 말고 numbers 를 그대로 인용하세요.
경로 지도가 있으면 map_url 로 나갑니다.""",
)


# MCP HTTP (중요합니다. Streamable http 이어야 합니다.)
#
# `stateless_http=True` 는 이 서버의 방침이다 — 판정은 매 호출 좌표·시각만으로
# 결정되므로 세션에 남길 것이 없고, 외부 LLM 호스트가 세션을 여러 개 붙여도 서버가
# 상태를 들고 있지 않는다.
mcp_app = mcp.http_app(
    path="/",
    transport="streamable-http",
    json_response=False,
    stateless_http=True,
)

# lifespan 연동을 위한 래퍼 앱
app = FastAPI(
    title="Jeju Star MCP Server",
    description="제주 밤하늘 관측 조건 판정 MCP 서버",
    version="1.0.0",
    lifespan=mcp_app.lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "jeju-star-mcp"}


# 도구가 만든 경로 지도를 이 서버가 직접 서빙한다. 별도 웹서버를 세우지 않는 것은
# 포트가 하나면 컨테이너 노출도 하나로 끝나서다. 이름은 내용 해시라 세션 상태가
# 생기지 않고, `maps.read` 가 모양을 검사해 경로 탈출을 막는다.
#
# **겉 앱에 단다** — `api_app` 에 달면 MCP 도구가 되어 버린다.
@app.get("/maps/{name}", include_in_schema=False)
async def serve_map(name: str):
    document = maps.read(name)
    if document is None:
        return PlainTextResponse("지도를 찾을 수 없습니다.", status_code=404)
    return HTMLResponse(document)


# 배경 타일도 이 서버가 중계한다. 이유와 사본 규칙은 `server/tiles.py` 에 있다.
# 지도와 같은 자리에 다는 이유도 같다 — 포트가 하나면 컨테이너 노출도 하나로 끝난다.
#
# **스레드로 뺀다.** 사본이 없는 한 장은 공급자에서 1초가 걸리는데, 그동안 이벤트
# 루프가 멈추면 같은 화면의 나머지 다섯 장도 함께 선다 — 중계를 붙여 놓고 오히려
# 직접 받던 때보다 느려진다.
@app.get("/tiles/{layer}/{z}/{x}/{y}", include_in_schema=False)
async def serve_tile(layer: str, z: int, x: int, y: int):
    got = await asyncio.to_thread(tiles.fetch, layer, z, x, y)
    if got is None:
        # 화면은 이 실패를 세고 있다가 넉 장이 되면 키가 필요 없는 공급자로 갈아탄다
        # (`core/mapview.py`). 그러니 여기서는 조용히 실패하는 편이 낫다.
        return PlainTextResponse("타일을 가져오지 못했습니다.", status_code=502)
    blob, content_type = got
    return Response(
        blob,
        media_type=content_type,
        # 브라우저도 사본을 쥐게 둔다. 서버 사본은 "누가 열어도 빠르게"를, 이쪽은
        # "같은 사람이 다시 열면 요청조차 없게"를 맡는다.
        headers={"Cache-Control": f"public, max-age={tiles.MAX_AGE}"},
    )


app.mount("/", mcp_app)


if __name__ == "__main__":
    import os

    import uvicorn

    parser = argparse.ArgumentParser(description="Jeju Star MCP Server")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"),
                        help="Host to bind")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "11000")),
        help="Port to bind (default: 11000)",
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    uvicorn.run(
        "app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
