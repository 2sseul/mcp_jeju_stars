"""schema — 응답 계약.

값이 부분적이어도 응답 '모양'은 고정이다. 특히 `resolved`·`spots` 는 값이 없어도
**키가 항상 존재**해야 한다(`docs/plan.md` 고정 2).
"""

from __future__ import annotations

from server.clients.open_meteo import _clean
from server.schema import Response

EXPECTED_KEYS = {
    "verdict", "reasons", "numbers", "attribution", "as_of", "resolved", "spots",
    "map_url",
}


def _make(**overrides) -> Response:
    base = {
        "verdict": "최적",
        "reasons": ["완전한 밤이라 은하수까지 볼 수 있어요"],
        "numbers": {"sqm": 21.2},
        "attribution": ["Open-Meteo"],
        "as_of": "2026-07-24T22:00+09:00",
    }
    return Response(**{**base, **overrides})


def test_resolved가_없어도_키는_항상_존재한다():
    # Given: 좌표를 직접 받아 지오코딩 해석이 없는 응답에서
    response = _make()
    # When: dict 로 변환하면
    result = response.to_dict()
    # Then: resolved·spots 키가 None 값으로라도 반드시 들어 있다
    assert set(result) == EXPECTED_KEYS
    assert result["resolved"] is None
    assert result["spots"] is None
    assert result["map_url"] is None


def test_spots가_있으면_그대로_실린다():
    # Given: 관측지를 말하는 응답에서 (추천·상세조회)
    rows = [{"name": "새별오름", "region": "서"}]
    # When: dict 로 변환하면
    result = _make(spots=rows).to_dict()
    # Then: 같은 키 집합을 유지하면서 목록이 실린다
    assert set(result) == EXPECTED_KEYS
    assert result["spots"] == rows


def test_spots도_내부_상태를_유출하지_않는다():
    # Given: 관측지 dict 를 담은 응답에서
    rows = [{"name": "새별오름"}]
    result = _make(spots=rows).to_dict()
    # When: 호출자가 돌려받은 항목을 수정해도
    result["spots"][0]["name"] = "끼워넣기"
    # Then: 원본은 그대로다 (항목마다 복사한다)
    assert rows == [{"name": "새별오름"}]


def test_resolved가_있으면_그대로_실린다():
    # Given: 지오코딩으로 위치가 해석된 응답에서
    resolved = {"query": "성산일출봉", "lat": 33.46, "lon": 126.94}
    # When: dict 로 변환하면
    result = _make(resolved=resolved).to_dict()
    # Then: 같은 키 집합을 유지하면서 해석 결과가 실린다
    assert set(result) == EXPECTED_KEYS
    assert result["resolved"] == resolved


def test_to_dict는_내부_상태를_유출하지_않는다():
    # Given: 가변 컨테이너를 담은 응답에서
    reasons = ["원본"]
    numbers = {"sqm": 21.2}
    response = _make(reasons=reasons, numbers=numbers)
    # When: 변환 결과를 호출자가 수정하면
    result = response.to_dict()
    result["reasons"].append("끼워넣기")
    result["numbers"]["sqm"] = 0.0
    # Then: 원본은 그대로다(복사본을 돌려주므로)
    assert reasons == ["원본"]
    assert numbers == {"sqm": 21.2}


def test_예보_결측값은_None으로_환원된다():
    # Given: 예보 응답에 값이 없거나 NaN 이 들어왔을 때
    # When: 정규화하면
    # Then: 판정이 '불가'로 오해하지 않도록 None 으로 환원된다
    assert _clean(None) is None
    assert _clean(float("nan")) is None
    assert _clean(42) == 42.0
