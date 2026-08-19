"""주행 가능 도로를 **이어 붙인 그래프**로 줄여 둔다 (배치, 다시 돌려도 안전).

왜 따로 만드나
--------------------------------------------------------------------------
`jeju_road_darkness.npz` 는 도로를 150m 세그먼트로 **흩어 놓은** 것이다. "옆에 길이
있나"는 답하지만 "여기서 저기까지 몇 분"은 답하지 못한다 — 세그먼트끼리 어떻게
이어지는지가 그 파일에 없기 때문이다. 이어짐을 담는 것은 이 파일뿐이다.

30MB 짜리 원본 JSON 을 `core` 가 열 수 없으므로(모듈 로드가 몇 초씩 걸린다) 여기서
CSR(compressed sparse row) 배열로 줄인다. `build_road_tags.py` 와 같은 규율이다.

속도는 어디서 오나 — 추정하지 않는다
--------------------------------------------------------------------------
정체를 따지지 않기로 했으므로(`plan.md` P11) 실시간 교통 API 가 필요 없다. 대신
**법정 최고속도**를 쓴다:

1. OSM 에 `maxspeed` 가 적혀 있으면 그 값. 제주 도로 29,390개 중 416개(1.4%)뿐이다.
2. 없으면 등급별 기본값 — `도로교통법 시행규칙` 제19조(자동차등의 속도)와
   안전속도 5030 정책에서 온 값이다. `_SPEED_KMH` 주석에 조항을 달아 두었다.

**이 값은 신호·교차로 대기를 담지 않는다.** 법정속도로 쉬지 않고 달린 자유주행
시간이라 실제보다 낙관적이다. 그래서 `core/routing.py` 가 교차로 지연을 따로 얹는다 —
같은 수를 두 곳에서 만들지 않도록, 여기서는 순수한 주행 시간만 넣는다.

무엇을 도로로 치지 않나
--------------------------------------------------------------------------
`road.NOT_DRIVABLE`(농로·임도·사유 진입로·보행로)을 그대로 쓴다. 후보를 거른 기준과
길찾기 기준이 다르면 "왜 저기로 안내하지"를 설명할 수 없다.

실행:
    uv run python -m scripts.build_road_graph
"""

from __future__ import annotations

import json
import re
from itertools import pairwise

import numpy as np

from server import path
from server.core.road import NOT_DRIVABLE

#: 등급별 법정 최고속도(km/h). `maxspeed` 태그가 없을 때만 쓴다.
#:
#: 근거 — 「도로교통법 시행규칙」 제19조 제1항:
#:   · 자동차전용도로: 최고 90km/h                        → trunk
#:   · 일반도로(편도 2차로 이상): 최고 80km/h              → primary
#:   · 일반도로(편도 1차로): 최고 60km/h                   → secondary·tertiary
#:   · 주거·상업·공업지역 일반도로: 50km/h (안전속도 5030) → residential·unclassified
#: 연결로(`_link`)는 나들목·교차로 램프라 본선 속도로 달릴 수 없다. 곡선 반경이
#: 작아 설계속도가 본선의 절반 수준이므로 40km/h 로 둔다.
#: `living_street`(보행 우선 도로)는 「도로교통법」상 보행자 우선도로에 해당해 20km/h.
_SPEED_KMH: dict[str, float] = {
    "motorway": 100.0,
    "trunk": 90.0,
    "primary": 80.0,
    "secondary": 60.0,
    "tertiary": 60.0,
    "unclassified": 50.0,
    "residential": 50.0,
    "living_street": 20.0,
    "road": 50.0,
    "motorway_link": 40.0,
    "trunk_link": 40.0,
    "primary_link": 40.0,
    "secondary_link": 40.0,
    "tertiary_link": 40.0,
}

#: 등급을 모를 때. 가장 느린 일반도로로 본다 — 모르는 길을 빠르다고 치면 도착
#: 시간을 낙관해서 "30분 안"에 못 가는 곳을 추천하게 된다.
_SPEED_FALLBACK = 40.0

#: `maxspeed` 의 숫자 부분. '60' · '60 km/h' 를 받는다. 'KR:urban' 같은 구역 표기는
#: 숫자가 없으므로 등급 기본값으로 떨어진다.
_MAXSPEED = re.compile(r"^\s*(\d+(?:\.\d+)?)")

_EARTH_M = 6_371_000.0


def _haversine(lat1, lon1, lat2, lon2):
    """두 점 사이 거리(m). 배열을 그대로 받는다."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * _EARTH_M * np.arcsin(np.sqrt(a))


def _speed_kmh(tags: dict) -> float:
    """이 도로를 법정 최고속도 몇 km/h 로 달릴 수 있나."""
    raw = tags.get("maxspeed")
    if raw:
        m = _MAXSPEED.match(str(raw))
        if m:
            v = float(m.group(1))
            # 0 이나 비상식적인 값은 태깅 오류다. 원본에 3·5km/h 가 실제로 있다.
            if 5.0 <= v <= 130.0:
                return v
    return _SPEED_KMH.get(tags.get("highway", ""), _SPEED_FALLBACK)


def _oneway(tags: dict) -> int:
    """진행 방향. 1=정방향만, -1=역방향만, 0=양방향.

    `junction=roundabout` 은 `oneway` 태그가 없어도 일방통행이다(OSM 관례).
    """
    raw = str(tags.get("oneway", "")).strip().lower()
    if raw in ("yes", "true", "1"):
        return 1
    if raw == "-1":
        return -1
    if raw in ("no", "false", "0"):
        return 0
    if tags.get("junction") in ("roundabout", "circular"):
        return 1
    return 0


def build() -> dict:
    """원본 OSM 을 읽어 CSR 그래프 배열을 만든다."""
    ways = json.loads(path.ROADS_OSM.read_text(encoding="utf-8"))["elements"]

    # --- 1) 노드 좌표 수집 (way 의 geometry 가 노드 순서대로 lat/lon 을 준다) ---
    coord: dict[int, tuple[float, float]] = {}
    kept = []
    for w in ways:
        tags = w.get("tags", {})
        if tags.get("highway") in NOT_DRIVABLE:
            continue
        ids, geom = w.get("nodes"), w.get("geometry")
        # geometry 가 잘린 way(경계 밖으로 나간 것)는 좌표를 못 믿으므로 버린다.
        if not ids or not geom or len(ids) != len(geom) or len(ids) < 2:
            continue
        for nid, g in zip(ids, geom, strict=True):
            coord.setdefault(nid, (g["lat"], g["lon"]))
        kept.append((ids, tags))

    index = {nid: i for i, nid in enumerate(coord)}
    n_nodes = len(coord)
    lat_it = (coord[n][0] for n in coord)
    lon_it = (coord[n][1] for n in coord)
    node_lat = np.fromiter(lat_it, dtype=np.float64, count=n_nodes)
    node_lon = np.fromiter(lon_it, dtype=np.float64, count=n_nodes)

    # --- 2) 간선 만들기 (인접 노드 쌍) ---
    src: list[int] = []
    dst: list[int] = []
    spd: list[float] = []
    for ids, tags in kept:
        speed = _speed_kmh(tags)
        direction = _oneway(tags)
        for a, b in pairwise(ids):
            i, j = index[a], index[b]
            if i == j:
                continue
            if direction >= 0:
                src.append(i)
                dst.append(j)
                spd.append(speed)
            if direction <= 0:
                src.append(j)
                dst.append(i)
                spd.append(speed)

    src_a = np.asarray(src, dtype=np.int32)
    dst_a = np.asarray(dst, dtype=np.int32)
    spd_a = np.asarray(spd, dtype=np.float64)

    meters = _haversine(
        node_lat[src_a], node_lon[src_a], node_lat[dst_a], node_lon[dst_a]
    )
    seconds = meters / (spd_a * 1000.0 / 3600.0)

    # --- 3) CSR 로 정렬 (출발 노드별로 묶어 두면 조회가 슬라이스 하나로 끝난다) ---
    order = np.argsort(src_a, kind="stable")
    src_a, dst_a = src_a[order], dst_a[order]
    meters, seconds = meters[order], seconds[order]
    indptr = np.zeros(n_nodes + 1, dtype=np.int64)
    np.cumsum(np.bincount(src_a, minlength=n_nodes), out=indptr[1:])

    return {
        "node_lat": node_lat,
        "node_lon": node_lon,
        "indptr": indptr,
        "indices": dst_a,
        "meters": meters.astype(np.float32),
        "seconds": seconds.astype(np.float32),
        "source": np.array(
            "도로망: OpenStreetMap (Overpass) · "
            "속도: 도로교통법 시행규칙 제19조 법정 최고속도"
        ),
    }


def main() -> None:
    arrays = build()
    path.ROAD_GRAPH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path.ROAD_GRAPH, **arrays)

    n_nodes = len(arrays["node_lat"])
    n_edges = len(arrays["indices"])
    # 양방향 간선이라 합의 절반이 실제 도로 연장이다.
    km = float(arrays["meters"].sum()) / 1000.0 / 2
    size_mb = path.ROAD_GRAPH.stat().st_size / 1024 / 1024
    print(f"노드 {n_nodes:,}개 · 간선 {n_edges:,}개 · 도로 연장 약 {km:,.0f}km")
    print(f"→ {path.ROAD_GRAPH.relative_to(path.ROOT)} ({size_mb:.1f}MB)")


if __name__ == "__main__":
    main()
