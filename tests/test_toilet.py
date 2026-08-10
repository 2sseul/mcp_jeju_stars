"""toilet — 공중화장실 근접 조회 (정적 CSV 조회).

데이터 출처와 좌표를 어떻게 얻었는지는 `server/core/toilet.py` 모듈 독스트링과
`scripts/geocode_toilets.py`.

네트워크는 쓰지 않는다. CSV 는 저장소에 있는 정적 파일이고, 좌표 컬럼은 배치
스크립트가 미리 채워 둔 것이다.
"""

from __future__ import annotations

from server.core import toilet

# --- 로드 ---------------------------------------------------------------------


def test_좌표가_채워진_행만_로드된다():
    # Given: 849행 중 주소를 좌표로 바꾸지 못한 53행이 빈 칸으로 남아 있을 때
    # When: 사용 가능한 화장실 수를 세면
    # Then: 좌표가 있는 행만 남는다(원본 전체보다 적고, 대부분은 남는다)
    assert 700 < toilet.COUNT < 849


def test_모든_좌표가_서비스_범위_안이다():
    # Given: 추자면(≈33.95°N)은 제주 본섬에서 40km 떨어져 있을 때
    # When: 로드된 화장실 좌표를 전부 훑으면
    # Then: `core.lamps`·`core.parking` 과 같은 경계 안에만 있다
    assert all(33.0 <= t.lat <= 33.7 for t in toilet.toilets())
    assert all(126.0 <= t.lon <= 127.1 for t in toilet.toilets())


# --- 개방시간 ------------------------------------------------------------------


def test_개방시간은_구분과_상세를_한_줄로_합친다():
    # Given: 원본이 구분('상시'·'정시')과 상세('09:00~18:00')를 따로 담을 때
    # When: 한 줄로 합치면
    # Then: 사람이 읽을 때 필요한 것(몇 시까지 열려 있나)만 남는다
    assert toilet._hours({"개방시간": "정시", "개방시간상세": "09:00~18:00"}) \
        == "09:00~18:00"
    # 상세가 없으면 구분이 곧 답이다 — '상시'는 그 자체로 24시간을 뜻한다
    assert toilet._hours({"개방시간": "상시", "개방시간상세": ""}) == "상시"


# --- 반경 조회 -----------------------------------------------------------------


def test_저지오름은_반경_200m_안에_화장실이_있다():
    # Given: 관측지 저지오름 좌표가 주어졌을 때 (원본에 '저지오름' 화장실이 있다)
    near = toilet.near(33.3349, 126.2480)
    # When: 기본 반경(걸어서 2~3분)으로 조회하면
    # Then: 최소 한 곳이 걸리고, 전부 반경 안이며, 가까운 순이다
    assert near
    assert all(n.distance_m <= toilet.WALK_M for n in near)
    assert [n.distance_m for n in near] == sorted(n.distance_m for n in near)


def test_용눈이오름은_반경_200m_안에_화장실이_없다():
    # Given: 관측지 용눈이오름 좌표가 주어졌을 때
    # When: 기본 반경으로 조회하면
    # Then: 한 곳도 없다 — 그 자체가 관측 계획에 쓰이는 답이다
    assert toilet.near(33.4762, 126.8229) == ()


def test_반경_밖이어도_가장_가까운_곳은_말한다():
    # Given: 반경 안에 화장실이 없는 관측지(용눈이오름)가 주어졌을 때
    nearest = toilet.nearest(33.4762, 126.8229)
    # When: 가장 가까운 곳을 물으면
    # Then: '없음'이 아니라 거리와 함께 돌아온다
    #       ("없음"과 "300m 밖에 있음"은 계획이 달라진다)
    assert nearest is not None
    assert nearest.distance_m > toilet.WALK_M


def test_반경을_넓히면_더_많이_걸린다():
    # Given: 같은 좌표를 두 반경으로 물었을 때
    tight = toilet.near(33.4890, 126.4983, radius_m=200.0)
    wide = toilet.near(33.4890, 126.4983, radius_m=2_000.0)
    # When: 두 결과를 비교하면
    # Then: 넓은 쪽이 좁은 쪽을 포함한다
    assert len(wide) >= len(tight)
    assert {id(n.toilet) for n in tight} <= {id(n.toilet) for n in wide}
