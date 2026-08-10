"""표고 조회 — 정적 격자에서 읽는 순수 함수 (네트워크 없음).

`scripts/build_elevation_grid.py` 가 잘라 둔 FABDEM(1초각 ~30m) 격자를 연다.
도보 경로가 얼마나 오르는지를 여기서 답한다.

**맨땅(DTM)이다.** Copernicus GLO-30·SRTM 같은 DSM 은 수관·건물 높이가 섞여 있어
숲길 오름에서 사람이 나무를 밟고 걷는 것으로 계산된다 — 제주 육지의 67%가 1m 이상,
31.7%가 5m 이상 부풀어 있다(`decisions.md` §2.17).

왜 `core` 에 있나 — 이것은 **잰 값**이지 판단이 아니고, 파일 하나만 읽으므로
네트워크도 LLM 도 부르지 않는다(`architecture.md` 계층 규칙). 편집 도구가 저장할
때마다 부르므로 배치로 두면 값이 늘 한 박자 늦는다.

무엇을 답하지 않나
--------------------------------------------------------------------------
**격자 한 칸(30m)보다 짧은 구간의 경사는 못 잰다.** 양 끝점이 같은 칸이면 차가 0 이
나오고, 칸 경계를 걸치면 그 경계 하나가 통째로 경사가 된다. `MIN_M` 보다 짧으면
`None` 을 답한다 — 0° 로 답하면 '평평하다'로 읽힌다.

격자 파일은 라이선스(CC BY-NC-SA)상 커밋하지 않으므로, 받은 저장소에서 처음
쓸 때는 `scripts/build_elevation_grid.py` 를 한 번 돌려야 한다.
"""

from __future__ import annotations

import math

import numpy as np

from server import path
from server.core import lamps

if not path.DEM_GRID.exists():
    raise SystemExit(
        f"표고 격자가 없습니다: {path.DEM_GRID.relative_to(path.ROOT)}\n"
        "  라이선스(CC BY-NC-SA)상 커밋하지 않는 파일입니다. 한 번 만들면 됩니다:\n"
        "    uv run --with tifffile --with imagecodecs "
        "python -m scripts.build_elevation_grid"
    )

_npz = np.load(path.DEM_GRID, allow_pickle=True)

#: 데시미터 정수. 미터로 바꾸는 것은 조회할 때 한 번만 한다.
_GRID = _npz["elevation_dm"]
_TOP = float(_npz["top"])
_LEFT = float(_npz["left"])
_SCALE = float(_npz["scale"])
_NODATA = int(_npz["nodata"])

SOURCE: str = str(_npz["source"])

#: 격자 한 칸의 크기(m). 1초각을 위도 33도에서 잰 값 — 남북 약 30.8m.
CELL_M: float = _SCALE * lamps.KM_PER_DEG * 1000.0

#: 이보다 짧은 구간의 경사는 답하지 않는다. 격자 **두 칸** — 한 칸이면 양 끝점이
#: 이웃 칸일 수 있고, 그러면 잰 것이 지형이 아니라 그 칸 경계 하나다.
MIN_M: float = 2 * CELL_M


def at(lat: float, lon: float) -> float | None:
    """그 좌표의 표고(m). 격자 밖이거나 결측이면 None.

    최근접 화소를 그대로 읽는다. 쌍선형 보간을 하면 값이 매끄러워 보이지만 없는
    정밀도가 생길 뿐이다 — 이 격자의 잡음(NMAD 1.27m)이 보간 오차보다 크다.
    """
    row = int(round((_TOP - lat) / _SCALE))
    col = int(round((lon - _LEFT) / _SCALE))
    if not (0 <= row < _GRID.shape[0] and 0 <= col < _GRID.shape[1]):
        return None
    value = int(_GRID[row, col])
    return None if value == _NODATA else value / 10.0


def metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 점 사이 거리(m). `core.lamps` 와 같은 등거리 평면 근사."""
    dy = (b[0] - a[0]) * lamps.KM_PER_DEG
    dx = (b[1] - a[1]) * lamps.KM_PER_DEG * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy) * 1000.0


def length_m(points) -> float:
    return sum(metres_between(points[i - 1], points[i]) for i in range(1, len(points)))


def slope_deg(points) -> float | None:
    """점 목록 양 끝의 평균 경사(도). 너무 짧거나 표고를 모르면 None.

    가운데 점들은 쓰지 않는다 — 길이는 실제로 걸은 거리(꺾인 선의 합)로 재고,
    고도는 양 끝만 본다. 가운데를 더하면 격자 잔 톱니가 전부 누적된다.
    """
    if len(points) < 2:
        return None
    metres = length_m(points)
    if metres < MIN_M:
        return None
    start, end = at(*points[0]), at(*points[-1])
    if start is None or end is None:
        return None
    return round(math.degrees(math.atan2(end - start, metres)), 1)


def climb_m(points) -> float | None:
    """양 끝의 순 고도차(m). 오르막이면 양수."""
    if len(points) < 2:
        return None
    start, end = at(*points[0]), at(*points[-1])
    if start is None or end is None:
        return None
    return round(end - start, 1)


def percent(climb: float, metres: float) -> float:
    """국립공원공단 배점표가 쓰는 백분율 경사. `core.trail` 이 이 값을 받는다."""
    return abs(climb) / metres * 100.0 if metres else 0.0
