"""주행 시간 — 실제 도로를 따라간 시간이다 (순수 함수 + 정적 그래프 조회).

왜 직선거리가 아닌가
--------------------------------------------------------------------------
제주는 가운데가 한라산이다. 북쪽 제주시와 남쪽 서귀포는 직선으로 25km 지만 차로는
산을 넘거나(1100도로·516도로) 돌아가야 한다. 직선거리로 "30분 안"을 자르면 한라산
반대편을 추천하게 된다. 동서 방향도 마찬가지로 해안을 따라 도는 구간이 길다.

그래서 `data/road/jeju_road_graph.npz`(주행 가능 도로를 이어 붙인 CSR 그래프) 위에서
다익스트라로 최단 **시간**을 푼다. `scripts/build_road_graph.py` 가 만든다.

정체는 따지지 않는다 (`plan.md` P11)
--------------------------------------------------------------------------
실시간 교통 API 를 쓰지 않으므로 `egress 0` 방침을 깨지 않고, 애초에 이 서버가 답하는
것은 **밤 시간대 이동**이라 정체가 거의 없다. 대신 신호·교차로 대기는 시간대와 무관하게
붙으므로 그것만 얹는다 — `_JUNCTION_S` 주석에 근거를 달아 두었다.

한 번의 조회로 여러 목적지를 답한다
--------------------------------------------------------------------------
추천은 "출발지 하나 → 관측지 63곳"이다. 목적지마다 길찾기를 돌리면 63번 푸는데,
다익스트라는 원래 **출발지 하나에서 모든 곳까지**를 한 번에 푼다. `drive_times` 가
그 형태다. `budget_minutes` 를 주면 그 시간을 넘는 순간 탐색을 멈춘다 — "30분 안"을
물었으면 제주 반대편까지 풀 이유가 없다.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

from server import path

if not path.ROAD_GRAPH.exists():
    raise FileNotFoundError(
        f"도로 그래프가 없습니다: {path.ROAD_GRAPH.relative_to(path.ROOT)}\n"
        "먼저 `uv run python -m scripts.build_road_graph` 를 한 번 돌리세요."
    )

_npz = np.load(path.ROAD_GRAPH, allow_pickle=True)

_LAT: np.ndarray = _npz["node_lat"]
_LON: np.ndarray = _npz["node_lon"]
_INDPTR: np.ndarray = _npz["indptr"]
_INDICES: np.ndarray = _npz["indices"]
_METERS: np.ndarray = _npz["meters"]
_SECONDS: np.ndarray = _npz["seconds"]

#: attribution 최상위에 축어로 노출할 데이터 귀속(그래프가 적어 둔 것).
SOURCE: str = str(_npz["source"])

_EARTH_M = 6_371_000.0

#: 갈림길 노드 하나를 지날 때 붙는 지연(초). 그래프의 간선 시간은 법정속도로 쉬지 않고
#: 달린 자유주행이라 신호·감속이 빠져 있다.
#:
#: **문헌 상수가 아니라 실측 보정값이다.** 「도로용량편람」의 신호교차로 제어지연
#: (LOS A ≤ 15초)을 그대로 쓰면 안 된다 — 여기서 세는 것은 신호교차로가 아니라
#: OSM 노드 차수가 2를 넘는 **모든 갈림길**이고, 그중 신호가 있는 곳은 일부다.
#: 원본 Overpass 추출이 way 만 담고 있어(노드 태그가 없다) `highway=traffic_signals`
#: 를 가려낼 수 없으므로, 갈림길 전체에 얇게 얹어 총량을 맞춘다.
#:
#: 보정 근거 — 제주공항 출발 5개 경로를 내비게이션 소요시간과 맞춰 본 결과
#: (`scripts/check_route_calibration.py` 로 재현·재보정한다):
#:
#:     지연 0초 → 평균 비율 0.80 (전 구간 과소)
#:     지연 5초 → 평균 비율 0.98 ← 채택
#:     지연 15초 → 평균 비율 1.23 (전 구간 과대)
#:
#: **알려진 편향**: 1100도로·516도로 같은 급커브 산길은 법정속도를 낼 수 없어
#: 여전히 30%가량 짧게 나온다. 곡률을 재지 않는 한 남는 오차다.
_JUNCTION_S = 5.0

#: 교차로로 세는 분기점. 나가는 간선이 이 수보다 많으면 갈림길로 본다.
#: (양방향 도로 한복판의 노드는 나가는 간선이 2개다 — 왔던 길과 갈 길.)
_JUNCTION_DEGREE = 2

#: 좌표를 도로에 붙일 때 이보다 멀면 "도로에서 떨어져 있다"고 답한다.
#: 그래프가 150m 세그먼트가 아니라 OSM 노드 그대로라 도로 위 점은 대개 수십 m 안에
#: 붙는다. 1km 를 넘으면 주행 가능 도로가 닿지 않는 자리다.
SNAP_LIMIT_M = 1_000.0


@dataclass(frozen=True)
class Route:
    """출발지 → 목적지 한 건의 주행 결과."""

    minutes: float
    km: float
    #: 좌표를 도로에 붙이며 생긴 오차(m). 출발지·목적지 각각.
    snap_origin_m: float
    snap_dest_m: float

    def to_dict(self) -> dict:
        return {
            "minutes": round(self.minutes, 1),
            "km": round(self.km, 1),
            "snap_origin_m": round(self.snap_origin_m),
            "snap_dest_m": round(self.snap_dest_m),
        }


def _haversine_to_all(lat: float, lon: float) -> np.ndarray:
    """한 점에서 모든 그래프 노드까지의 거리(m)."""
    p1 = math.radians(lat)
    p2 = np.radians(_LAT)
    dp = p2 - p1
    dl = np.radians(_LON) - math.radians(lon)
    a = np.sin(dp / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * _EARTH_M * np.arcsin(np.sqrt(a))


def snap(lat: float, lon: float) -> tuple[int, float]:
    """좌표를 가장 가까운 도로 노드에 붙인다. (노드 번호, 떨어진 거리 m)."""
    d = _haversine_to_all(lat, lon)
    i = int(np.argmin(d))
    return i, float(d[i])


def _dijkstra(
    start: int, budget_s: float, targets: set[int]
) -> tuple[dict[int, tuple[float, float]], dict[int, int]]:
    """start 에서 각 노드까지 최단 시간. ({노드: (초, m)}, {노드: 직전 노드}).

    budget_s 를 넘는 노드는 넣지 않는다. targets 를 모두 찾으면 즉시 멈춘다 —
    둘 다 "제주 전체를 풀지 않기 위한" 장치다.

    직전 노드를 함께 모으는 것은 **경로를 그리기 위해서**다(`route_path`). 시간·거리만
    쓰는 호출자는 두 번째 값을 버리면 되고, 모으는 비용은 dict 하나뿐이다.
    """
    best_s: dict[int, float] = {start: 0.0}
    best_m: dict[int, float] = {start: 0.0}
    prev: dict[int, int] = {}
    done: set[int] = set()
    left = set(targets)
    left.discard(start)
    queue: list[tuple[float, float, int]] = [(0.0, 0.0, start)]

    while queue:
        sec, met, u = heapq.heappop(queue)
        if u in done:
            continue
        done.add(u)
        left.discard(u)
        if not left:
            break
        if sec > budget_s:
            break

        lo, hi = int(_INDPTR[u]), int(_INDPTR[u + 1])
        # 갈림길이면 신호 대기를 얹는다. 도로 한복판(나가는 간선 2개)은 그냥 지난다.
        delay = _JUNCTION_S if (hi - lo) > _JUNCTION_DEGREE else 0.0
        for e in range(lo, hi):
            v = int(_INDICES[e])
            if v in done:
                continue
            ns = sec + float(_SECONDS[e]) + delay
            if ns > budget_s:
                continue
            if ns < best_s.get(v, math.inf):
                best_s[v] = ns
                best_m[v] = met + float(_METERS[e])
                prev[v] = u
                heapq.heappush(queue, (ns, best_m[v], v))

    return {n: (best_s[n], best_m[n]) for n in done}, prev


def drive_times(
    origin: tuple[float, float],
    destinations: list[tuple[float, float]],
    budget_minutes: float | None = None,
) -> list[Route | None]:
    """출발지에서 각 목적지까지의 주행 시간·거리. 못 가면 그 자리에 None.

    다익스트라를 **한 번만** 돌려 모든 목적지를 답한다. 목적지 수만큼 길찾기를
    돌리는 것과 결과는 같고 비용은 1/n 이다.

    Args:
        origin: 출발지 (위도, 경도).
        destinations: 목적지 좌표 목록.
        budget_minutes: 이 시간을 넘는 곳은 None. 생략하면 제한 없음(느리다).

    Returns:
        destinations 와 **같은 길이·같은 순서**의 목록. 도로가 닿지 않거나
        budget 을 넘으면 그 자리가 None 이다. 순서를 지키는 것은 호출자가 목적지
        메타데이터(관측지 이름 등)와 zip 으로 맞물리기 때문이다.
    """
    if not destinations:
        return []

    o_node, o_snap = snap(*origin)
    snapped = [snap(lat, lon) for lat, lon in destinations]

    budget_s = math.inf if budget_minutes is None else budget_minutes * 60.0
    targets = {n for n, _ in snapped}
    reached, _ = _dijkstra(o_node, budget_s, targets)

    out: list[Route | None] = []
    for node, d_snap in snapped:
        hit = reached.get(node)
        # 도로에서 1km 넘게 떨어진 자리는 "붙일 도로가 없다"로 본다. 억지로 붙이면
        # 엉뚱한 길의 시간을 그 장소의 시간인 양 답하게 된다.
        if hit is None or d_snap > SNAP_LIMIT_M or o_snap > SNAP_LIMIT_M:
            out.append(None)
            continue
        sec, met = hit
        out.append(
            Route(
                minutes=sec / 60.0,
                km=met / 1000.0,
                snap_origin_m=o_snap,
                snap_dest_m=d_snap,
            )
        )
    return out


def drive_time(
    origin: tuple[float, float],
    destination: tuple[float, float],
    budget_minutes: float | None = None,
) -> Route | None:
    """출발지 → 목적지 한 건. `drive_times` 의 단건 형태."""
    return drive_times(origin, [destination], budget_minutes)[0]


def route_path(
    origin: tuple[float, float],
    destination: tuple[float, float],
    budget_minutes: float | None = None,
) -> list[tuple[float, float]] | None:
    """출발지 → 목적지의 **실제 지나가는 길**(위도·경도 점렬). 못 가면 None.

    `drive_time` 이 "몇 분"을 답한다면 이건 "어느 길로"를 답한다. 지도에 선을 그리는
    쪽만 쓰므로 `Route` 에 넣지 않았다 — 점이 수백 개라 도구 응답에 실으면 사람도
    LLM 도 읽지 않는 덩어리가 응답의 대부분을 차지한다.

    Returns:
        [(lat, lon), ...] — 출발 노드에서 도착 노드까지 순서대로. 길이 2 미만이면
        None(붙일 도로가 없거나 같은 노드).
    """
    o_node, o_snap = snap(*origin)
    d_node, d_snap = snap(*destination)
    if o_snap > SNAP_LIMIT_M or d_snap > SNAP_LIMIT_M:
        return None

    budget_s = math.inf if budget_minutes is None else budget_minutes * 60.0
    reached, prev = _dijkstra(o_node, budget_s, {d_node})
    if d_node not in reached:
        return None

    # 도착에서 출발까지 거꾸로 타고 올라간 뒤 뒤집는다.
    nodes = [d_node]
    while nodes[-1] != o_node:
        step = prev.get(nodes[-1])
        if step is None:      # 출발 노드까지 이어지지 않는다(도달 못 한 경우)
            return None
        nodes.append(step)
    nodes.reverse()

    if len(nodes) < 2:
        return None
    return [(float(_LAT[n]), float(_LON[n])) for n in nodes]
