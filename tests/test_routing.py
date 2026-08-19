"""routing — 주행시간이 직선거리가 아님을 못박는다.

전부 로컬 그래프 조회라 네트워크를 타지 않는다. 값 자체의 정확도(내비게이션과의
차이)는 `scripts/check_route_calibration.py` 가 따로 본다 — 여기서는 **구조가
맞는지**를 본다.
"""

from __future__ import annotations

import math

import pytest

from server.core import routing

AIRPORT = (33.5070, 126.4930)      # 제주국제공항 (북)
SEOGWIPO = (33.2541, 126.5601)     # 서귀포시청 (남 — 한라산 반대편)
SAEBYEOL = (33.3651, 126.3611)     # 새별오름 주차장 (서)
UDO = (33.5060, 126.9530)          # 우도 — 다리가 없다


def _straight_km(a, b) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def test_한라산_반대편은_직선거리보다_한참_돌아간다():
    # Given: 제주시(북)와 서귀포(남) 사이에는 한라산이 있다
    route = routing.drive_time(AIRPORT, SEOGWIPO)
    straight = _straight_km(AIRPORT, SEOGWIPO)
    # When: 실제 도로로 재면
    # Then: 직선거리보다 확실히 길다. 직선거리로 "30분 안"을 자르면 산 반대편을
    #       추천하게 되는데, 그것을 막는 것이 이 모듈의 존재 이유다.
    assert route is not None
    assert route.km > straight * 1.3, f"{route.km:.1f}km vs 직선 {straight:.1f}km"


def test_도로가_닿지_않는_섬은_None이다():
    # Given: 우도는 배로만 간다 (다리가 없다)
    # When: 주행시간을 물으면
    route = routing.drive_time(AIRPORT, UDO)
    # Then: 억지로 붙여 숫자를 내지 않고 '못 간다'로 답한다.
    #       여기서 아무 값이나 내면 배를 타야 하는 곳을 "차로 40분"이라 추천한다
    assert route is None


def test_예산을_넘는_목적지는_잘린다():
    # Given: 공항에서 서귀포까지는 40분을 넘는다
    over = routing.drive_time(AIRPORT, SEOGWIPO, budget_minutes=10)
    within = routing.drive_time(AIRPORT, SEOGWIPO, budget_minutes=180)
    # When: 예산을 좁혔다 넓히면
    # Then: 좁을 때만 잘린다 = "30분 안에 갈 수 있는 곳" 이 실제로 동작한다
    assert over is None
    assert within is not None


def test_한_번의_탐색이_목적지_순서를_그대로_지킨다():
    # Given: 목적지 세 곳을 한 번에 물으면
    targets = [SAEBYEOL, UDO, SEOGWIPO]
    routes = routing.drive_times(AIRPORT, targets)
    # When: 결과를 보면
    # Then: 길이와 순서가 입력과 같다. 호출자가 관측지 메타데이터와 zip 으로
    #       맞물리므로, 못 간 곳을 빼서 줄이면 이름이 어긋난다
    assert len(routes) == len(targets)
    assert routes[0] is not None
    assert routes[1] is None       # 우도
    assert routes[2] is not None


def test_출발지와_목적지가_같으면_0분이다():
    # Given: 같은 지점을 출발지이자 목적지로 주면
    route = routing.drive_time(SAEBYEOL, SAEBYEOL)
    # When: 재면
    # Then: 0 이다 (같은 노드에 붙는다)
    assert route is not None
    assert route.minutes == pytest.approx(0.0, abs=0.01)
    assert route.km == pytest.approx(0.0, abs=0.01)


def test_가까운_곳이_먼_곳보다_오래_걸리지_않는다():
    # Given: 공항에서 새별오름(서)과 서귀포(남·한라산 너머)를
    near, far = routing.drive_times(AIRPORT, [SAEBYEOL, SEOGWIPO])
    # When: 비교하면
    # Then: 순서가 뒤집히지 않는다 — 다익스트라가 최단 시간을 준다는 최소 성질
    assert near is not None and far is not None
    assert near.minutes < far.minutes


def test_목적지가_없으면_빈_목록이다():
    # Given: 조건에 맞는 후보가 하나도 없을 때 (추천에서 실제로 일어난다)
    # When: 빈 목록으로 물으면
    # Then: 탐색을 시작조차 하지 않는다
    assert routing.drive_times(AIRPORT, []) == []


def test_스냅_거리를_함께_돌려준다():
    # Given: 도로 위가 아닌 좌표를 주면 (관측 지점은 대개 도로 옆이다)
    route = routing.drive_time(AIRPORT, SAEBYEOL)
    # When: 결과를 보면
    # Then: 좌표를 도로에 얼마나 끌어다 붙였는지가 응답에 있다.
    #       호출자가 "이 값은 주차장 앞까지"임을 판단할 수 있어야 한다
    assert route is not None
    assert route.snap_dest_m >= 0.0
    assert route.snap_dest_m <= routing.SNAP_LIMIT_M
    assert set(route.to_dict()) == {"minutes", "km", "snap_origin_m", "snap_dest_m"}


def test_일방통행이_그래프에_반영돼_있다():
    # Given: 원본 OSM 에 oneway 가 3,449개 있다
    # When: 간선 수를 노드 수와 견주면
    # Then: 모든 도로가 양방향이었다면 간선은 정확히 2배수로 대칭이다.
    #       비대칭이 있다는 것이 일방통행이 살아 있다는 뜻이다
    total = len(routing._INDICES)
    assert total > 0
    # 대칭 여부를 직접 세는 대신, 진입/진출 차수 합이 어긋나는 노드가 있는지 본다
    outdeg = routing._INDPTR[1:] - routing._INDPTR[:-1]
    indeg = [0] * len(outdeg)
    for v in routing._INDICES:
        indeg[int(v)] += 1
    assert any(int(o) != i for o, i in zip(outdeg, indeg, strict=True))
