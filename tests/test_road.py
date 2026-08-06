"""road — 도로 근접 (순수 함수 + 정적 배열 조회).

데이터 출처와 세그먼트 구성은 `server/core/road.py` 모듈 독스트링.

네트워크는 쓰지 않는다. npz 는 저장소에 있는 정적 파일이다.
"""

from __future__ import annotations

from server.core import road

# --- 로드 ---------------------------------------------------------------------


def test_도로망_세그먼트가_로드된다():
    # Given: 제주 전역 OSM 도로망을 150m 세그먼트로 자른 배열이 있을 때
    # When: 세그먼트 수를 세면
    # Then: 6만 개 규모다(`sweep_place_candidates.py` 가 쓰는 것과 같은 배열)
    assert road.COUNT > 50_000


def test_주행_불가_등급은_목록에_박혀_있다():
    # Given: 농로·임도(track)와 사유 진입로(service)는
    # When: 주행 가능 판정에 쓰이는 제외 목록을 보면
    # Then: 둘 다 들어 있다 — 초행 야간 운전으로 들어갈 곳이 아니다
    assert "track" in road.NOT_DRIVABLE
    assert "service" in road.NOT_DRIVABLE


# --- 등급 이름 -----------------------------------------------------------------


def test_모르는_등급은_원문_그대로_보여_준다():
    # Given: 이름표에 없는 OSM 등급이 주어졌을 때
    # When: 사람이 읽는 이름으로 바꾸면
    # Then: 그럴듯한 말로 덮지 않고 원문을 그대로 돌려준다
    assert road.label_of("bridleway") == "bridleway"
    assert road.label_of("track") == "농로·임도"


# --- 조회 ---------------------------------------------------------------------


def test_지방도_옆_관측지는_주행_가능한_길이_바로_잡힌다():
    # Given: 용눈이오름(용눈이오름로 옆)이 주어졌을 때
    hit = road.nearest(33.46015, 126.83129, drivable_only=True)
    # When: 주행 가능한 가장 가까운 길을 물으면
    # Then: 500m 안에 있고, 주행 가능 등급이다
    assert hit is not None
    assert hit.drivable
    assert hit.distance_m < 500


def test_농로가_더_가까우면_두_답이_갈린다():
    # Given: 다랑쉬오름처럼 농로가 먼저 닿는 자리가 주어졌을 때
    any_road = road.nearest(33.463, 126.851)
    drivable = road.nearest(33.463, 126.851, drivable_only=True)
    # When: 아무 길과 주행 가능한 길을 각각 물으면
    # Then: 주행 가능한 쪽이 더 멀다 — 그 차이가 곧 "농로로만 닿는다"는 답이다
    assert any_road is not None and drivable is not None
    assert not any_road.drivable
    assert drivable.distance_m > any_road.distance_m


def test_접근_경로는_같은_이름의_길을_한_줄로_묶는다():
    # Given: 서귀포 삼매봉처럼 시가지라 반경 1km 안에 도로 세그먼트가 빽빽한 곳에서
    legs = road.approach(33.243972, 126.546309)
    # When: 접근 경로를 정리하면
    # Then: 한 도로가 OSM way 여러 개로 쪼개져 있어도 (등급, 이름)으로 묶여
    #       읽을 수 있는 줄 수로 줄어든다(묶지 않으면 80줄이 나온다)
    assert 0 < len(legs) < 40
    keys = [(leg.way_class, leg.name) for leg in legs]
    assert len(keys) == len(set(keys))


def test_접근_경로는_가까운_순이다():
    # Given: 아무 관측지나 주어졌을 때
    legs = road.approach(33.463, 126.851)
    # When: 줄 순서를 보면
    # Then: 관측지에서 가까운 길이 먼저다 — 도착 직전부터 읽히게
    assert [leg.nearest_m for leg in legs] == sorted(leg.nearest_m for leg in legs)


def test_가로등이_하나도_없는_구간은_None_이다():
    # Given: 1100고지처럼 반경 1km 안에 가로등이 0개인 곳이 주어졌을 때
    legs = road.approach(33.3583, 126.4658)
    # When: 각 구간의 가로등 최근접 중앙값을 보면
    # Then: NaN 이 아니라 None 이다 — 원본은 '없음'을 NaN 으로 적어 두는데
    #       그대로 비교하면 `NaN > 100` 이 False 라 '가로등 있음'으로 뒤집힌다
    assert legs
    assert all(leg.lamp_median_m is None for leg in legs)
    assert "가로등 없음" in road.describe_approach(legs)


def test_요약은_등급도_판정도_적지_않는다():
    # Given: 농로가 먼저 닿는 곳(다랑쉬오름 일대)이 주어졌을 때
    legs = road.approach(33.463, 126.851)
    summary = road.describe_approach(legs)
    # When: 한 줄 요약을 보면
    # Then: 잰 값만 있고 등급 이름도 '주행 불가' 같은 판정도 없다 —
    #       폭·교행 여지는 원본에 거의 없으므로 아는 척하지 않는다
    assert "주행" not in summary
    for label in ("농로", "임도", "진입로", "지방도", "주거지"):
        assert label not in summary
    assert road.measured(legs[0]) in summary


def test_잰_값이_없으면_없다고_적는다():
    # Given: 폭·차선 태그가 없는 길이 주어졌을 때(제주 도로의 99% 가 그렇다)
    legs = [
        leg for leg in road.approach(33.463, 126.851)
        if leg.width_m is None and leg.lanes is None
    ]
    # When: 그 길의 잰 값을 한 줄로 만들면
    # Then: 빈칸으로 두거나 등급으로 메우지 않고 '정보 없음'이라고 적는다
    assert legs
    assert "폭·차선 정보 없음" in road.measured(legs[0])


def test_태그_커버리지를_그대로_말할_수_있다():
    # Given: 원본 OSM 의 폭·차선·노면 태그가 대부분 비어 있을 때
    got = road.coverage()
    # When: 커버리지를 물으면
    # Then: 0~1 비율로 답한다 — 화면이 "왜 다 정보 없음인가"를 이 값으로 설명한다
    assert set(got) == {"lanes", "width", "surface"}
    assert all(0.0 <= v <= 1.0 for v in got.values())
    assert got["width"] < 0.1   # 폭은 1% 미만이다. 이 사실 자체가 답이다


def test_도로가_없으면_요약이_그렇게_말한다():
    # Given: 반경 안에 길이 하나도 없을 때(빈 결과)
    # When: 요약을 만들면
    # Then: 빈 문자열이 아니라 없다고 적는다 — 화면이 빈칸으로 남지 않게
    assert "없다" in road.describe_approach(())


def test_주행_가능_조회는_제외_등급을_돌려주지_않는다():
    # Given: 제주 안 아무 지점이나 주어졌을 때
    # When: 주행 가능만 걸러 물으면
    # Then: 제외 목록에 든 등급은 절대 나오지 않는다
    for lat, lon in ((33.3583, 126.4675), (33.2449, 126.5596), (33.4762, 126.8229)):
        hit = road.nearest(lat, lon, drivable_only=True)
        assert hit is not None
        assert hit.way_class not in road.NOT_DRIVABLE
