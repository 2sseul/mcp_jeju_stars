"""지형 지평선 — 이 자리에서 하늘이 어느 방위로 얼마나 막혀 있나 (순수 함수).

별자리 축(`constellation.py`)은 "오리온자리는 남쪽 12도" 까지 답한다. 그런데 남쪽이
한라산이면 12도는 **보이지 않는다.** 이 모듈이 그 '보이지 않음'을 잰다.

무엇을 재는가
--------------------------------------------------------------------------
관측자를 중심으로 방위마다 지형을 훑어, 그 방향에서 **하늘이 시작되는 고도각**을 낸다.
평지 한가운데면 0도에 가깝고, 오름 밑이나 한라산 쪽이면 10도를 넘기도 한다.

    horizon("남") = 12.4  →  남쪽 하늘은 고도 12.4도부터 보인다

계산 — 시선이 지형을 스치는 각의 최대값
--------------------------------------------------------------------------
한 방위로 거리 d 를 늘려 가며 표고 h 를 읽고, 관측자에서 그 점을 본 고도각을 잰다.

    고도각 = atan2(h - h0 - drop(d), d)

가장 큰 값이 그 방위의 지평선이다. **가장 높은 지형이 아니라 가장 크게 올려다보게 되는
지형**이 하늘을 막는다 — 멀리 있는 한라산보다 코앞의 둔덕이 더 가릴 수 있다.

지구가 둥근 것을 뺀다
--------------------------------------------------------------------------
`drop(d) = d² / (2R)` 만큼 먼 지형은 지구 곡면을 따라 내려간다(R = 지구 평균 반지름).
20km 에서 31m, 30km 에서 71m 다. 한라산(1,947m)을 20km 밖에서 볼 때 이 보정이 없으면
지평선을 0.09도쯤 높게 잡는다 — 크지 않지만 공짜로 맞출 수 있는 값이라 넣는다.

**대기 굴절은 넣지 않는다.** 표준 굴절은 이 강하를 약 13% 덜어 내는데(측지 관례
k≈0.13), 30km 에서 9m·고도각으로 0.02도다. 격자 자체의 수직 오차(FABDEM NMAD 1.27m)와
30m 해상도가 그보다 훨씬 크므로, 없는 정밀도를 만들지 않는다.

**관측자 눈높이도 더하지 않는다.** 1.6m 를 더해 봐야 같은 이유로 묻힌다.

알려진 한계
--------------------------------------------------------------------------
격자는 **맨땅**(FABDEM — 수관·건물 제거)이다. 그래서 실제로 시야를 막는 방풍림·건물·
전봇대는 이 계산에 안 잡힌다. 여기서 낸 지평선은 **지형만의 하한**이고, 현장은 더
막혀 있을 수 있다 — 문구도 그렇게 말해야 한다.
"""

from __future__ import annotations

import math

import numpy as np

from server.core import elevation

__all__ = [
    "BEARINGS",
    "EARTH_R_M",
    "MAX_KM",
    "MIN_M",
    "OPEN_DEG",
    "drop_m",
    "profile",
]

# --- 상수 --------------------------------------------------------------------

#: 지구 평균 반지름(m). IUGG 평균 반지름 R₁ = 6,371.0088 km.
EARTH_R_M: float = 6_371_008.8

#: 얼마까지 훑을까. 제주 어디서든 한라산까지 25km 안이고, 그 너머 지형은 곡면
#: 강하(30km 에서 71m)에 묻혀 지평선을 거의 올리지 못한다.
MAX_KM: float = 30.0

#: 어디서부터 훑을까. 격자 한 칸(약 30m)보다 가까우면 읽는 것이 지형이 아니라
#: 관측자가 선 칸 자신이다.
MIN_M: float = elevation.CELL_M

#: 거리 표본 수. 로그 간격으로 놓는다 — 가까운 지형이 지평선을 좌우하므로 그쪽을
#: 촘촘히 본다(30m~300m 구간에 약 4분의 1이 들어간다).
SAMPLES: int = 240

#: 8방위. `constellation._BEARINGS`·`spots._BEARINGS` 와 같은 이름과 순서다.
BEARINGS: tuple[str, ...] = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")

#: 한 방위 칸(45도) 안을 몇 갈래로 쪼개 볼까. 칸 한가운데만 쏘면 바로 옆의 오름을
#: 통째로 놓친다. 45/9 = 5도 간격이다.
RAYS_PER_BEARING: int = 9

#: 이 값 아래면 '트여 있다'고 본다. 격자 해상도(30m)와 수직 오차를 감안하면 1도 미만의
#: 지평선은 지형이라기보다 잡음이다 — 30m 앞에서 0.5m 차이가 1도다.
OPEN_DEG: float = 1.0


# --- 순수 계산 ----------------------------------------------------------------

def drop_m(distance_m: float | np.ndarray) -> float | np.ndarray:
    """거리 d 에서 지구 곡면이 내려가는 높이(m). d² / 2R."""
    return distance_m * distance_m / (2.0 * EARTH_R_M)


def _ray_angles(
    lat: float, lon: float, base_m: float, azimuths_deg: np.ndarray
) -> np.ndarray:
    """방위별 지평선 고도각(도). azimuths_deg 와 같은 길이로 돌려준다."""
    # 거리 표본 — 로그 간격(가까운 쪽을 촘촘히).
    dist = np.geomspace(MIN_M, MAX_KM * 1000.0, SAMPLES)

    # 위·경도 1도의 거리. 위도 33도의 경도 1도는 위도 1도보다 짧다.
    m_per_deg_lat = math.pi * EARTH_R_M / 180.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(lat))

    az = np.radians(azimuths_deg)[:, None]
    d = dist[None, :]

    # 방위각은 북=0, 시계방향이다 — 북쪽이 +위도, 동쪽이 +경도.
    lats = lat + (d * np.cos(az)) / m_per_deg_lat
    lons = lon + (d * np.sin(az)) / m_per_deg_lon

    heights = elevation.at_many(lats, lons)

    # 바다·격자 밖은 지형이 없는 것이지 낮은 지형이 아니다. 시선을 막지 않으므로
    # 각을 재지 않고 버린다(-inf 로 두면 max 에서 저절로 빠진다).
    rise = heights - base_m - drop_m(d)
    angles = np.degrees(np.arctan2(rise, d))
    angles = np.where(np.isnan(heights), -np.inf, angles)

    out = angles.max(axis=1)
    # 지형이 하나도 없는 방위(전부 바다)는 지평선이 0도다.
    return np.where(np.isfinite(out), out, 0.0)


def profile(lat: float, lon: float) -> dict[str, float] | None:
    """8방위별 지평선 고도(도). 관측자 표고를 모르면 None.

    각 방위 칸은 45도 폭이라 그 안을 `RAYS_PER_BEARING` 갈래로 쏘고 **가장 높은
    것**을 취한다 — 별자리는 방위 칸 단위로 답하므로, 칸 안 어딘가가 막혀 있으면
    그 칸은 막힌 것으로 봐야 안전하다.

    Returns:
        {"북": 2.1, "북동": 0.4, ...} — 음수는 0으로 눌러 돌려준다(바다 쪽에서
        지평선이 수평선 아래로 내려가는 것은 여기서 다룰 일이 아니다).
    """
    # 배포 컨테이너에는 표고 격자가 없다(`docs/status.md`). 지평선은 있으면 좋은
    # 축이지 없으면 못 답하는 축이 아니므로, 여기서 물러서고 부르는 쪽이 단서 없이
    # 답하게 둔다 — 서버가 멈추는 것보다 낫다.
    if not elevation.HAS_GRID:
        return None
    base = elevation.at(lat, lon)
    if base is None:
        return None

    step = 45.0 / RAYS_PER_BEARING
    out: dict[str, float] = {}
    for i, name in enumerate(BEARINGS):
        centre = i * 45.0
        # 칸의 [-22.5, +22.5) 를 고르게 훑는다.
        azimuths = centre - 22.5 + step * (np.arange(RAYS_PER_BEARING) + 0.5)
        angles = _ray_angles(lat, lon, base, azimuths)
        out[name] = round(float(max(angles.max(), 0.0)), 1)
    return out


# --- 서술 --------------------------------------------------------------------

def describe(prof: dict[str, float] | None) -> list[str]:
    """지평선을 사람이 읽는 문장으로. 못 쟀으면 빈 목록.

    **트인 쪽을 먼저 말한다.** 관측자가 정해야 하는 것은 "어디가 막혔나"보다
    "어디를 보고 서나"이기 때문이다. 막힌 쪽은 가장 심한 하나만 덧붙인다 —
    여덟 방위를 다 읊으면 정작 서야 할 방향이 묻힌다(수치는 `numbers` 에 다 있다).
    """
    if not prof:
        return []

    open_ways = [k for k, v in prof.items() if v < OPEN_DEG]
    worst = max(prof.items(), key=lambda kv: kv[1])

    if worst[1] < OPEN_DEG:
        return ["사방 지평선이 트여 있어요 — 어느 쪽 하늘이든 낮게 뜬 별까지 보입니다"]

    line = ""
    if open_ways:
        line += "하늘이 트인 쪽은 " + "·".join(open_ways) + "쪽이에요. "
    line += f"{worst[0]}쪽은 지형이 {worst[1]:.0f}도까지 가려요"
    return [
        line,
        "지형만 잰 값이라 방풍림·건물은 안 들어가 있어요 — 현장은 조금 더 막혀 있을 수 있어요",
    ]
