"""spots — 검증된 관측지 목록의 조회·거르기 계약.

정적 JSON 조회라 네트워크를 타지 않는다. 데이터 **내용**(어느 곳이 들어 있나)이
아니라 **다루는 방식**을 본다 — 내용은 사람이 검증해 채우는 것이라 테스트가
값을 못박으면 데이터를 고칠 때마다 테스트가 깨진다.
"""

from __future__ import annotations

import pytest

from server.core import spots


def test_관측지를_읽고_좌표가_제주_안이다():
    # Given: 검증된 관측지 목록에서
    all_spots = spots.all_spots()
    # When: 좌표를 보면
    # Then: 전부 제주 범위 안이다. 밖에 있으면 도구가 '지원 범위 밖'을
    #       추천하는 자가당착이 된다
    assert len(all_spots) > 0
    for s in all_spots:
        assert 33.19 <= s.lat <= 33.57, s.name
        assert 126.14 <= s.lon <= 126.98, s.name


def test_이름_찾기는_띄어쓰기를_따지지_않는다():
    # Given: 사용자가 띄어쓰기를 맞춰 줄 이유가 없다
    a = spots.find("새별오름")
    b = spots.find("새별 오름")
    # When: 두 표기로 찾으면
    # Then: 같은 곳이다
    assert a is not None
    assert a is b


@pytest.mark.parametrize("query", ["", "   ", "서울시청", "존재하지않는오름"])
def test_없는_이름은_None이다(query):
    # Given: 목록에 없는 이름이나 빈 질의를 주면
    # When: 찾으면
    # Then: 아무 곳이나 돌려주지 않는다. 여기서 엉뚱한 곳을 반환하면
    #       "매오름 물었는데 왜 다른 데를 답하지"가 된다
    assert spots.find(query) is None


def test_주차장이_있으면_주행_목적지는_주차장이다():
    # Given: 관측 지점이 오름 정상이라 도로에서 먼 곳에서
    climbing = [s for s in spots.all_spots() if s.needs_climb and s.parking]
    assert climbing, "등반이 필요하고 주차장이 있는 곳이 데이터에 있어야 한다"
    s = climbing[0]
    # When: 차로 향할 지점을 물으면
    # Then: 관측 지점이 아니라 주차장이다 — 주행시간은 차를 세우는 곳까지다.
    #       남은 구간은 walk_minutes 가 따로 답한다
    assert s.drive_target() == (s.parking[0]["lat"], s.parking[0]["lon"])
    assert s.drive_target() != s.coord()


def test_주차장이_없으면_관측_지점으로_떨어진다():
    # Given: 주차장이 등록되지 않은 곳에서
    no_parking = [s for s in spots.all_spots() if not s.parking]
    if not no_parking:
        pytest.skip("주차장 없는 관측지가 데이터에 없다")
    s = no_parking[0]
    # When: 주행 목적지를 물으면
    # Then: 예외가 아니라 관측 지점 자체로 떨어진다
    assert s.drive_target() == s.coord()


def test_등산_없는_곳_거르기는_등반을_전부_뺀다():
    # Given: "등산 없는 곳" 질의에서
    kept = spots.filter_spots(no_climb=True)
    # When: 결과를 보면
    # Then: 오르막이 필요한 곳이 하나도 없고, 전체보다는 적다
    assert all(not s.needs_climb for s in kept)
    assert 0 < len(kept) < len(spots.all_spots())


def test_도보_시간을_모르는_곳은_거르지_않는다():
    # Given: walk_minutes 가 없는 곳이 데이터에 있을 때
    unknown = [s for s in spots.all_spots() if s.walk_minutes is None]
    if not unknown:
        pytest.skip("도보 시간이 없는 관측지가 데이터에 없다")
    # When: 도보 0분 이하로 좁히면
    kept = spots.filter_spots(max_walk_minutes=0.0)
    # Then: 모르는 곳은 남아 있다. 모르는 것과 오래 걸리는 것은 다르다 —
    #       모른다고 빼 버리면 사용자가 그 곳의 존재조차 못 본다
    for s in unknown:
        assert s in kept, s.name


def test_거르기_조건을_안_주면_전부_돌려준다():
    # Given: 조건 없는 추천("아무 데나 별 보기 좋은 곳")에서
    # When: 거르면
    # Then: 후보를 임의로 줄이지 않는다
    assert len(spots.filter_spots()) == len(spots.all_spots())


def test_지역_거르기는_알려진_구분만_받는다():
    # Given: 데이터가 쓰는 지역 구분에서
    used = {s.region for s in spots.all_spots()}
    # When: 노출된 목록과 견주면
    # Then: 도구가 안내하는 값과 데이터의 값이 어긋나지 않는다.
    #       어긋나면 "동쪽에서 추천해줘"가 조용히 0건을 돌려준다
    assert used <= set(spots.REGIONS), f"목록에 없는 지역: {used - set(spots.REGIONS)}"
    for region in used:
        assert spots.filter_spots(region=region), region


def test_원문_필드를_참거짓으로_접지_않는다():
    # Given: 야간 출입이 조건부인 곳들 (자유 문장으로 적혀 있다)
    conditional = [s for s in spots.all_spots() if not s.always_open]
    assert conditional, "조건부 야간 출입이 데이터에 있어야 한다"
    # When: 그 값을 보면
    for s in conditional:
        # Then: 파생 축(always_open)은 거짓이지만 원문은 살아 있다.
        #       "예약한 야영객만" 같은 조건이 참/거짓으로 접히면 사라진다
        assert s.night_access, s.name
        assert s.night_access != "상시 개방"
