"""app — 진입점이 도구를 제대로 노출하는지.

`tools.py`(판정)와 `app.py`(등록·전송)를 가른 뒤 새로 생긴 이음매를 계약으로 잡는다.
판정 내용 자체는 `test_tools.py` 가 본다 — 여기서는 **노출**만 본다.

pytest-asyncio 를 들이지 않으려고 async 경계는 `asyncio.run` 으로 감싼다(호출이
몇 개뿐이라 플러그인을 추가할 이유가 없다).
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app import mcp
from server import routes, tools

TOOLS = {"recommend_spots", "evaluate_place", "spot_details"}


def _registered() -> dict:
    return asyncio.run(mcp.get_tools())


def test_두_도구가_이름_그대로_등록된다():
    # Given: app 이 tools 의 판정 함수를 MCP 도구로 등록했을 때
    # When: 서버가 들고 있는 도구 목록을 보면
    names = set(_registered())
    # Then: 딱 둘이고, 이름은 외부 LLM 이 부르는 그 이름이다
    #       (이름이 바뀌면 호스트 쪽 툴콜이 조용히 끊긴다)
    assert names == TOOLS


#: 도구 이름 → 그 도구의 요청 모델. `FastMCP.from_fastapi` 는 이 모델의 OpenAPI
#: 문서로 도구 스키마를 만들고, 라우트는 필드를 **이름으로** 판정 함수에 넘긴다.
REQUEST_MODELS = {
    "recommend_spots": routes.RecommendSpotsRequest,
    "evaluate_place": routes.EvaluatePlaceRequest,
    "spot_details": routes.SpotDetailsRequest,
}


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_요청_모델의_필드는_판정_함수의_인자와_이름이_같다(name):
    # Given: 라우트가 요청 모델의 필드를 이름으로 골라 판정 함수에 넘길 때
    fields = set(REQUEST_MODELS[name].model_fields)
    params = set(inspect.signature(getattr(tools, name)).parameters)
    # Then: 모델에만 있는 이름이 없다. 어긋나면 서버가 뜨는 순간이 아니라 **그 도구를
    #       처음 부르는 순간** TypeError 로 드러난다 — 조용히 새는 실패라 계약으로
    #       못박는다(`server/routes.py` 모듈 docstring)
    assert fields <= params, f"모델에만 있는 인자: {sorted(fields - params)}"


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_판정_함수는_라우트를_거치지_않고도_부를_수_있다(name):
    # Given: 등록이 끝난 뒤에도
    fn = getattr(tools, name)
    # Then: tools 의 이름은 여전히 평범한 함수다 = FastAPI·MCP 가 판정 함수를
    #       덮어쓰지 않았다. 이게 깨지면 테스트·스크립트가 SDK 내부 속성에 묶인다
    assert inspect.isfunction(fn)


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_판정_함수는_평범한_파이썬_함수로_남는다(name):
    # Given: fastmcp v2 의 `@mcp.tool` 은 함수 자리에 FunctionTool 객체를 남긴다
    # When: 등록을 마친 뒤 tools 모듈의 이름을 보면
    fn = getattr(tools, name)
    # Then: 여전히 함수다 = 데코레이터가 판정 함수를 덮어쓰지 않았다.
    #       이게 깨지면 테스트·스크립트가 `.fn` 같은 SDK 내부 속성에 묶인다.
    assert inspect.isfunction(fn)
    assert callable(fn)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("recommend_spots", {"origin", "max_drive_minutes", "region", "no_climb"}),
        ("evaluate_place", {"query", "lat", "lon", "scope", "origin"}),
        ("spot_details", {"name", "origin"}),
    ],
)
def test_입력_스키마가_그_도구의_질의축을_노출한다(name, expected):
    # Given: 등록된 도구의 입력 스키마에서
    params = _registered()[name].parameters
    # When: 속성을 보면
    # Then: 그 도구가 답하기로 한 축이 파라미터로 나와 있다.
    #       (없으면 호스트 LLM 이 "30분 안"·"등산 없는 곳"을 영영 못 넘긴다)
    assert set(params["properties"]) >= expected


def test_필수_인자는_spot_details의_name_하나뿐이다():
    # Given: 세 도구의 필수 인자를 보면
    required = {n: set(_registered()[n].parameters.get("required", [])) for n in TOOLS}
    # When: 비교하면
    # Then: 추천은 조건 없이도 부를 수 있고("아무 데나 추천해줘"),
    #       평가는 이름이든 좌표든 택일이라 스키마 수준의 필수가 없다.
    #       상세만 어디를 물었는지가 반드시 필요하다.
    assert required["recommend_spots"] == set()
    assert required["evaluate_place"] == set()
    assert required["spot_details"] == {"name"}


def test_evaluate_place_설명은_scope를_안내한다():
    # Given: 도구 설명은 tools.py 의 docstring 에서 온다
    description = _registered()["evaluate_place"].description or ""
    # When: 그 내용을 보면
    # Then: LLM 이 moment/night 을 고를 수 있을 만큼은 적혀 있다.
    #       (설명이 비면 호스트가 scope 를 영영 안 쓴다)
    assert "scope" in description
    assert "night" in description


def test_추천_설명은_직선거리가_아님을_밝힌다():
    # Given: 추천 도구의 설명에서
    description = _registered()["recommend_spots"].description or ""
    # When: 거리 축을 어떻게 재는지 찾으면
    # Then: 실제 도로 기준임이 적혀 있다. 호출한 LLM 이 "직선거리겠지"라고
    #       가정하고 사용자에게 잘못 설명하는 것을 막는다.
    assert "도로" in description
    assert "직선거리" in description


def test_평가_설명은_미등록_장소_한계를_밝힌다():
    # Given: 평가 도구의 설명에서
    description = _registered()["evaluate_place"].description or ""
    # When: 등록되지 않은 장소를 어떻게 다루는지 찾으면
    # Then: 하늘은 판정하되 접근성은 모른다는 것이 적혀 있다.
    #       이게 빠지면 LLM 이 주차·야간출입을 지어낸다.
    assert "등록" in description
    assert "주차" in description


def test_도구를_MCP_경로로_불러도_가드가_그대로_걸린다():
    # Given: 제주 밖 좌표를 (파이썬 직접 호출이 아니라) 도구 실행 경로로 넘겼을 때
    tool = _registered()["evaluate_place"]
    # When: 실행하면
    result = asyncio.run(tool.run({"lat": 37.5665, "lon": 126.9780}))
    # Then: 예외가 아니라 고정 스키마의 '지원 범위 밖' 이 나온다.
    #       직접 호출과 툴콜이 갈리지 않는지 보는 것이라 네트워크를 타지 않는
    #       가드 경로 하나로 확인한다.
    assert result.structured_content["verdict"] == "지원 범위 밖"
