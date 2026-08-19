"""tools — 가드레일과 판정 계약.

네트워크가 필요 없는 경로만 검증한다(범위 밖·형식 오류·scope 오류는 외부 호출 전에
단락된다). 실제 판정 경로는 `uv run python -m server.app` 로 확인한다.

도구 **등록**(이 함수들이 MCP 로 노출되는지)은 `test_app.py` 소관이다.
"""

from __future__ import annotations

import pytest

from server import tools
from server.core import astro
from server.tools import evaluate_place, evaluate_spot

EXPECTED_KEYS = {"verdict", "reasons", "numbers", "attribution", "as_of", "resolved"}


def test_geocode는_모듈이_아니라_호출_가능한_함수여야_한다():
    # Given: tools 가 지오코딩을 이름으로 가져다 쓸 때
    # When: 그 이름을 확인하면
    # Then: 모듈이 아니라 함수다.
    #       `from server.clients import geocode` 로 모듈을 바인딩하면 호출 시
    #       TypeError 가 나는데, evaluate_place 의 `except Exception` 이 이를 삼켜
    #       **입력과 무관하게 항상 '주소 확인 실패'** 가 된다. 조용히 죽는 실패라
    #       계약으로 못박는다.
    assert callable(tools.geocode)
    assert not hasattr(tools.geocode, "__path__"), "모듈이 바인딩돼 있다"


# --- 가드레일 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        pytest.param(37.5665, 126.9780, id="서울"),
        pytest.param(33.0, 126.5, id="위도 하한 밖"),
        pytest.param(33.4, 127.5, id="경도 상한 밖"),
    ],
)
def test_제주_범위_밖은_프롬프트형_응답을_돌려준다(lat, lon):
    # Given: 제주 행정구역 밖의 좌표가 주어졌을 때
    # When: 평가하면
    result = evaluate_spot(lat, lon)
    # Then: 예외가 아니라 '지원 범위 밖' 응답이며, 스키마 모양은 그대로다
    assert result["verdict"] == "지원 범위 밖"
    assert set(result) == EXPECTED_KEYS
    assert result["reasons"]


@pytest.mark.parametrize(
    ("date", "time"),
    [
        pytest.param("2026/07/24", None, id="날짜 구분자 오류"),
        pytest.param("내일", None, id="자연어 날짜"),
        pytest.param(None, "22시", id="시각 형식 오류"),
        pytest.param("2026-13-99", None, id="범위를 벗어난 날짜"),
    ],
)
def test_날짜_시각_형식_오류는_입력_오류로_환원된다(date, time):
    # Given: 파싱할 수 없는 date/time 이 주어졌을 때
    # When: 제주 안 좌표로 평가하면
    result = evaluate_spot(33.4762, 126.8229, date=date, time=time)
    # Then: 예외를 던지지 않고 형식을 안내하는 응답이 나온다
    assert result["verdict"] == "입력 오류"
    assert set(result) == EXPECTED_KEYS


# scope 검사는 범위 검사보다 먼저 일어난다. 범위 밖 좌표를 쓰면 어떤 갈래로 갔는지가
# verdict 로 드러나고, 외부 호출도 타지 않는다.
OUT_OF_RANGE = (37.5665, 126.9780)


@pytest.mark.parametrize("scope", ["tonight", "밤", "both", "moment;night"])
def test_알_수_없는_scope는_입력_오류로_환원된다(scope):
    # Given: moment/night 이 아닌 scope 가 주어졌을 때
    # When: 평가하면
    result = evaluate_spot(*OUT_OF_RANGE, scope=scope)
    # Then: 범위 가드에 닿기 전에 scope 오류로 단락된다
    assert result["verdict"] == "입력 오류"


@pytest.mark.parametrize("scope", ["  MOMENT ", "Night", "moment", "NIGHT"])
def test_scope는_대소문자와_공백을_정규화한다(scope):
    # Given: 대소문자·공백이 섞인 유효한 scope 가 주어졌을 때
    # When: 범위 밖 좌표로 평가하면
    result = evaluate_spot(*OUT_OF_RANGE, scope=scope)
    # Then: scope 오류가 아니라 범위 가드에 걸린다 = 정규화가 동작했다
    assert result["verdict"] == "지원 범위 밖"


@pytest.mark.parametrize("scope", ["", None])
def test_빈_scope는_moment로_기본값이_된다(scope):
    # Given: scope 를 비워서 넘겼을 때
    # When: 범위 밖 좌표로 평가하면
    result = evaluate_spot(*OUT_OF_RANGE, scope=scope)
    # Then: 입력 오류가 아니라 기본값 moment 로 흘러 범위 가드에 걸린다
    assert result["verdict"] == "지원 범위 밖"


def test_범위_가드는_night_경로에도_걸린다():
    # Given: 제주 밖 좌표에 밤 집계를 요청했을 때
    # When: 평가하면
    result = evaluate_spot(37.5665, 126.9780, scope="night")
    # Then: moment 와 같은 가드가 적용된다(두 경로의 일관성)
    assert result["verdict"] == "지원 범위 밖"


# --- 천체력 지원 범위 ------------------------------------------------------------


@pytest.mark.parametrize("scope", ["moment", "night"])
@pytest.mark.parametrize("date", ["2100-01-01", "1800-01-01"])
def test_천체력_범위_밖_날짜는_입력_오류로_환원된다(date, scope):
    # Given: DE421 이 덮지 않는 날짜가 주어졌을 때(대략 1900~2053 밖)
    # When: 제주 안 좌표로 평가하면
    result = evaluate_spot(33.4762, 126.8229, date=date, scope=scope)
    # Then: skyfield 의 EphemerisRangeError 가 도구 밖으로 새지 않고,
    #       고정 스키마의 '입력 오류' 응답이 된다. 형식 검사만으로는 못 걸러진다
    assert result["verdict"] == "입력 오류"
    assert set(result) == EXPECTED_KEYS
    assert any("천체력" in r for r in result["reasons"])


def test_지원_범위_경계는_거부하지_않는다():
    # Given: 천체력이 실제로 덮는 범위의 양 끝에서
    for when in (astro.EPHEM_START, astro.EPHEM_END):
        # When: 지원 여부를 물으면
        # Then: 경계 자체는 지원한다
        #       (범위를 파일에서 읽으므로 하드코딩과 어긋나지 않는다)
        assert astro.supports(when)


def test_지원_범위는_천체력_파일에서_읽는다():
    # Given: DE421 을 로드한 상태에서
    # When: 노출된 범위를 보면
    # Then: 상수가 아니라 파일의 세그먼트에서 유도된 값이라 교체 시 따라온다
    assert astro.EPHEM_START < astro.EPHEM_END
    assert astro.EPHEM_START.year <= 1900
    assert astro.EPHEM_END.year >= 2050


# --- 검증 순서 --------------------------------------------------------------------


def test_evaluate_place는_지오코딩보다_먼저_입력을_검증한다(monkeypatch):
    # Given: 지오코딩이 호출되면 즉시 실패하도록 해두고
    called = []

    def spy(*a, **kw):
        called.append(a)
        raise AssertionError("입력이 잘못됐는데 지오코딩을 호출했다")

    monkeypatch.setattr(tools, "geocode", spy)

    # When: 잘못된 scope·날짜로 지명 평가를 요청하면
    bad_scope = evaluate_place("성산일출봉", scope="tonight")
    bad_date = evaluate_place("성산일출봉", date="엉터리")

    # Then: 외부 호출 없이 '입력 오류' 로 단락된다.
    #       (뒤에 검증하면 지오코딩까지 실패했을 때 '주소 확인 실패' 로 잘못 분류된다)
    assert called == []
    assert bad_scope["verdict"] == "입력 오류"
    assert bad_date["verdict"] == "입력 오류"


def test_좌표_경로와_지명_경로의_입력_판정이_같다(monkeypatch):
    # Given: 지오코딩이 항상 실패하는 상황에서(네트워크 장애 등)
    monkeypatch.setattr(tools, "geocode", lambda *a, **kw: None)
    # When: 같은 잘못된 입력을 두 도구에 주면
    for kwargs in ({"scope": "tonight"}, {"date": "엉터리"}, {"date": "2100-01-01"}):
        spot = evaluate_spot(33.4762, 126.8229, **kwargs)
        place = evaluate_place("성산일출봉", **kwargs)
        # Then: 지오코딩 성패와 무관하게 같은 판정이 나온다
        assert spot["verdict"] == place["verdict"] == "입력 오류", kwargs


# --- 응답 계약 ------------------------------------------------------------------


def test_모든_오류_응답도_고정_스키마를_지킨다():
    # Given: 서로 다른 실패 경로들에서 (전부 외부 호출 전에 단락되는 경로)
    failures = [
        evaluate_spot(*OUT_OF_RANGE),                          # 범위 밖
        evaluate_spot(33.4762, 126.8229, date="엉터리"),        # 형식 오류
        evaluate_spot(*OUT_OF_RANGE, scope="tonight"),         # scope 오류
    ]
    # When: 각 응답의 키 집합을 보면
    # Then: 전부 같다 — 실패해도 응답 '모양'은 바뀌지 않는다
    for result in failures:
        assert set(result) == EXPECTED_KEYS
        assert isinstance(result["reasons"], list)
        assert isinstance(result["numbers"], dict)
        assert isinstance(result["attribution"], list)
