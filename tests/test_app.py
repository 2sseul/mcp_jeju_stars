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

from server import tools
from server.app import mcp

TOOLS = {"evaluate_spot", "evaluate_place"}


def _registered() -> dict:
    return asyncio.run(mcp.get_tools())


def test_두_도구가_이름_그대로_등록된다():
    # Given: app 이 tools 의 판정 함수를 MCP 도구로 등록했을 때
    # When: 서버가 들고 있는 도구 목록을 보면
    names = set(_registered())
    # Then: 딱 둘이고, 이름은 외부 LLM 이 부르는 그 이름이다
    #       (이름이 바뀌면 호스트 쪽 툴콜이 조용히 끊긴다)
    assert names == TOOLS


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_등록된_도구는_tools_의_함수_바로_그것이다(name):
    # Given: 등록된 도구를 꺼내서
    tool = _registered()[name]
    # When: 그 안의 함수를 보면
    # Then: 래핑·복제본이 아니라 tools 모듈의 함수 **동일 객체**다.
    #       래퍼를 두면 시그니처·docstring 이 두 곳에 생겨 서로 어긋난다.
    assert tool.fn is getattr(tools, name)


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
    ("name", "required"),
    [("evaluate_spot", {"lat", "lon"}), ("evaluate_place", {"query"})],
)
def test_입력_스키마는_필수_인자만_필수로_둔다(name, required):
    # Given: 등록된 도구의 입력 스키마에서
    params = _registered()[name].parameters
    # When: 속성과 필수 항목을 보면
    # Then: date·time·scope 는 선택이다 — 호스트가 좌표(또는 지명)만으로 부를 수 있다
    assert set(params["properties"]) >= required | {"date", "time", "scope"}
    assert set(params["required"]) == required


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_도구_설명은_scope를_안내한다(name):
    # Given: 도구 설명은 tools.py 의 docstring 에서 온다
    description = _registered()[name].description or ""
    # When: 그 내용을 보면
    # Then: LLM 이 moment/night 을 고를 수 있을 만큼은 적혀 있다.
    #       (설명이 비면 호스트가 scope 를 영영 안 쓴다)
    assert "scope" in description
    assert "night" in description


def test_도구를_MCP_경로로_불러도_가드가_그대로_걸린다():
    # Given: 제주 밖 좌표를 (파이썬 직접 호출이 아니라) 도구 실행 경로로 넘겼을 때
    tool = _registered()["evaluate_spot"]
    # When: 실행하면
    result = asyncio.run(tool.run({"lat": 37.5665, "lon": 126.9780}))
    # Then: 예외가 아니라 고정 스키마의 '지원 범위 밖' 이 나온다.
    #       직접 호출과 툴콜이 갈리지 않는지 보는 것이라 네트워크를 타지 않는
    #       가드 경로 하나로 확인한다.
    assert result.structured_content["verdict"] == "지원 범위 밖"
