"""표고 조회 — 정적 격자에서 읽는 순수 함수 (네트워크 없음).

`scripts/build_elevation_grid.py` 가 잘라 둔 FABDEM(1초각 ~30m) 격자를 연다.
도보 경로가 얼마나 오르는지, 그리고 관측지 한 점이 어떤 지형에 서 있는지를
여기서 답한다.

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

도보 시간은 **사람이 나눠 둔 구간을 쓰지 않는다**
--------------------------------------------------------------------------
`data/jeju_spots.json` 의 `walk_routes[].segments` 는 사람이 노면·암릉을 적어 둔
칸이라 길이가 제각각이고, **가장 가파른 목재계단이 대개 `MIN_M` 보다 짧다**. 그
칸들만 보면 다랑쉬오름은 오름 209m 중 132m 밖에 잡히지 않는다 — 시간이 제일 많이
드는 곳이 통째로 빠진다.

그래서 `spans()` 가 원본 점을 `WALK_WIN_M` 이상으로 **다시 묶는다**. 격자가 계단을
못 본 것이 아니라 30m 계단을 30m 격자로 나눌 때 분모가 작아 잡음이 컸을 뿐이라,
묶어서 분모를 키우면 그대로 나온다(다랑쉬 132m → 209.5m, 경로 순고도 208.9m 와 일치).
`segments` 는 노면·암릉에만 쓰고 경사·거리는 여기서 다시 잰다.

격자 파일은 라이선스(CC BY-NC-SA)상 커밋하지 않으므로, 받은 저장소에서 처음
쓸 때는 `scripts/build_elevation_grid.py` 를 한 번 돌려야 한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from server import path
from server.core import lamps

#: 격자를 못 찾았을 때 안내. 라이선스(CC BY-NC-SA)상 커밋하지 않는 파일이다.
_MISSING = (
    f"표고 격자가 없습니다: {path.DEM_GRID}\n"
    "  라이선스(CC BY-NC-SA)상 커밋하지 않는 파일입니다. 한 번 만들면 됩니다:\n"
    "    uv run --with tifffile --with imagecodecs "
    "python -m scripts.build_elevation_grid"
)

#: FABDEM 은 1초각 격자다 — 파일이 없어도 **간격은 알려져 있다**(자료 사양).
#: 그래서 아래 CELL_M·MIN_M 은 격자 없이도 맞는 값이 된다.
_FABDEM_SCALE = 1.0 / 3600.0

# **격자가 없어도 import 는 된다.** 값을 읽는 `at()` 만 못 쓰고, 나머지(보행 속도
# 함수·오차 폭·구간 나누기 규칙)는 격자와 무관하다.
#
# 서버가 이 모듈을 부르는 이유가 그것이다 — `core/spots.py` 가 논문 오차 폭
# (`WALK_ERROR_MIN_PER_KM`) 하나를 쓴다. 도보 시간·경사는 배치가 미리 재어
# `jeju_spots.json` 에 박아 두므로 **배포 컨테이너에는 표고 격자가 필요 없다**
# (`docs/status.md`). 예전처럼 import 에서 죽으면 그 설계가 무너진다.
if path.DEM_GRID.exists():
    _npz = np.load(path.DEM_GRID, allow_pickle=True)
    #: 데시미터 정수. 미터로 바꾸는 것은 조회할 때 한 번만 한다.
    _GRID = _npz["elevation_dm"]
    _TOP = float(_npz["top"])
    _LEFT = float(_npz["left"])
    _SCALE = float(_npz["scale"])
    _NODATA = int(_npz["nodata"])
    SOURCE: str = str(_npz["source"])
else:
    _GRID = None
    _TOP = _LEFT = 0.0
    _SCALE = _FABDEM_SCALE
    _NODATA = 0
    SOURCE = "표고: FABDEM (격자 파일 없음 — 값 조회 불가)"

#: 격자 파일이 있는가. 배포 컨테이너에는 표고 격자를 넣지 않으므로(`docs/status.md`),
#: 격자를 **써도 되고 없어도 되는** 축은 이 값을 보고 물러선다. 반대로 격자가 반드시
#: 있어야 하는 배치 스크립트는 그냥 부르면 된다 — `at()` 이 안내와 함께 멈춘다.
HAS_GRID: bool = _GRID is not None

#: 격자 한 칸의 크기(m). 1초각을 위도 33도에서 잰 값 — 남북 약 30.8m.
CELL_M: float = _SCALE * lamps.KM_PER_DEG * 1000.0

#: 이보다 짧은 구간의 경사는 답하지 않는다. 격자 **두 칸** — 한 칸이면 양 끝점이
#: 이웃 칸일 수 있고, 그러면 잰 것이 지형이 아니라 그 칸 경계 하나다.
MIN_M: float = 2 * CELL_M

#: 관측지 한 점의 경사를 재는 규모(m). 격자 한 칸(30m)이 아니다 — 묻는 것이
#: "삼각대를 세우고 차를 댈 이 자리가 비탈인가"라 사람이 서서 둘러보는 크기에서
#: 답해야 하고, 한 칸으로 재면 밭두렁 하나가 경사가 된다. 90m 는 이 값을 처음
#: 낸 격자(Copernicus GLO-90)의 칸 크기에서 왔고, 격자를 바꾸면서도 그대로 뒀다 —
#: 눈금이 바뀌면 이미 적어 둔 값들과 비교가 안 된다(`decisions.md` §2.20).
SITE_M: float = 90.0


def at(lat: float, lon: float) -> float | None:
    """그 좌표의 표고(m). 격자 밖이거나 결측이면 None.

    최근접 화소를 그대로 읽는다. 쌍선형 보간을 하면 값이 매끄러워 보이지만 없는
    정밀도가 생길 뿐이다 — 이 격자의 잡음(NMAD 1.27m)이 보간 오차보다 크다.
    """
    if _GRID is None:
        raise SystemExit(_MISSING)
    row = int(round((_TOP - lat) / _SCALE))
    col = int(round((lon - _LEFT) / _SCALE))
    if not (0 <= row < _GRID.shape[0] and 0 <= col < _GRID.shape[1]):
        return None
    value = int(_GRID[row, col])
    return None if value == _NODATA else value / 10.0


def at_many(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """여러 좌표의 표고(m)를 **한 번에**. 격자 밖·결측은 NaN.

    `at()` 을 반복해 부르는 것과 값은 같지만, 파이썬 루프 대신 numpy 색인 한 번으로
    끝난다. 지평선을 재려면 한 지점에서 수만 개를 훑어야 해서(`core/horizon.py`)
    한 점씩 부르면 초 단위가 걸린다.

    격자를 소유한 이 모듈이 갖는다 — 부르는 쪽이 `_GRID` 를 직접 만지면 격자를
    바꿀 때 고칠 자리가 흩어진다.
    """
    if _GRID is None:
        raise SystemExit(_MISSING)
    rows = np.rint((_TOP - lats) / _SCALE).astype(np.int64)
    cols = np.rint((lons - _LEFT) / _SCALE).astype(np.int64)

    inside = (
        (rows >= 0) & (rows < _GRID.shape[0])
        & (cols >= 0) & (cols < _GRID.shape[1])
    )
    out = np.full(np.shape(lats), np.nan, dtype=float)
    if not inside.any():
        return out

    raw = _GRID[rows[inside], cols[inside]].astype(float)
    raw[raw == _NODATA] = np.nan
    out[inside] = raw / 10.0
    return out


def slope_at(lat: float, lon: float) -> float | None:
    """그 점 주변 `SITE_M` 격자의 경사(도). 이웃을 하나라도 모르면 None.

    동/서·남/북 이웃 넷을 받아 중앙차분한다.

        tan(경사) = √( ((E-W)/2d)² + ((N-S)/2d)² )

    `slope_deg` 와 답하는 것이 다르다 — 저쪽은 **걸어간 선**의 평균 기울기이고,
    이쪽은 **선 없이 한 점**이 놓인 지형의 기울기다. 그래서 저쪽은 방향이 있어
    음수가 되지만(내리막), 이쪽은 방향이 없어 늘 0 이상이다.

    이웃도 최근접 화소를 그대로 읽는다 — 90m 상자로 평균을 내 봐도 이 목록에서
    중앙값 0.1°·최대 5.3° 밖에 달라지지 않아, 읽는 방식을 둘로 두지 않는다.
    """
    dlat = SITE_M / (lamps.KM_PER_DEG * 1000.0)
    dlon = dlat / math.cos(math.radians(lat))
    west, east = at(lat, lon - dlon), at(lat, lon + dlon)
    south, north = at(lat - dlat, lon), at(lat + dlat, lon)
    if west is None or east is None or south is None or north is None:
        return None
    dz_dx = (east - west) / (2 * SITE_M)
    dz_dy = (north - south) / (2 * SITE_M)
    return round(math.degrees(math.atan(math.hypot(dz_dx, dz_dy))), 1)


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


def slope_max_deg(points) -> float | None:
    """구간 안에서 **가장 가파른 창**의 경사(도). 창이 하나뿐이면 그 값과 같다.

    `slope_deg` 는 양 끝만 보므로 올랐다 내려오면 상쇄된다 — 저지오름의 한 구간은
    평균 0.0° 인데 실제로는 7.7° 창이 들어 있고, 송악산 전망대는 평균 -0.9° 에
    최대 -14.1° 다. 평균만 보여 주면 그 비탈이 통째로 사라진다.

    부호는 절댓값이 가장 큰 창의 것을 그대로 쓴다 — 내리막도 밤에는 위험하다.
    창 나누기는 `spans()` 가 하므로 격자 잔 톱니가 다시 끼지 않는다.
    """
    got = [s.slope_deg for s in spans(points) if s.slope_deg is not None]
    if not got:
        return None
    return max(got, key=abs)


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


# --- 도보 시간 ----------------------------------------------------------------

#: 경사를 재려고 원본 점을 다시 묶는 길이(m). `MIN_M`(약 62m)보다 크기만 하면 되고,
#: 62~250m 어디로 잡아도 소요시간이 대부분 5% 안에서 같아 어림수 70 을 쓴다.
WALK_WIN_M: float = 70.0

#: Márquez-Pérez 수정 Tobler 함수 `v = 4.8·exp(-5.3·|0.7·S + 0.03|)` (km/h).
#: S 는 경사 tan. 원본 Tobler(1993)는 평지 5.04km/h·감쇠 3.5 인데, 이쪽은
#: 평지 4.09km/h·감쇠 5.3 이라 **느리고 경사에 더 민감**하다.
_WALK_A: float = 4.8
_WALK_B: float = 5.3
_WALK_C: float = 0.7
_WALK_D: float = 0.03

#: 논문이 밝힌 오차(분/km). 값을 내보낼 때 이 폭을 함께 적는다 — 단일값으로 주면
#: 없는 정밀도가 생긴다.
WALK_ERROR_MIN_PER_KM: tuple[float, float] = (1.8, 2.3)

WALK_SOURCE: str = (
    "도보 시간: Márquez-Pérez, Vallejo-Villalta & Álvarez-Francoso (2017), "
    "Geografisk Tidsskrift-Danish Journal of Geography 117(1): 53-62"
)


@dataclass(frozen=True)
class Span:
    """다시 묶은 한 도막. 경사를 **잴 수 있는 길이**가 보장된다."""

    metres: float
    #: 도막 양 끝의 평균 경사(도). 오르막 양수. 표고 결측이면 None.
    slope_deg: float | None
    #: 도막 양 끝의 순 고도차(m). 표고 결측이면 None.
    climb_m: float | None


def spans(points, window: float = WALK_WIN_M) -> tuple[Span, ...]:
    """경로를 `window` 이상 도막으로 다시 묶는다.

    **마지막 자투리는 버리지 않고 직전 도막에 붙인다.** 버리면 짧은 경로에서
    치명적이다 — 망동산(291m)은 자투리를 버릴 때 고도 31.1m 중 14.5m 만 잡혔다.
    붙이면 마지막 도막이 `window`~2배 `window` 가 되고 경로 전체가 덮인다.

    경로가 통째로 `MIN_M` 보다 짧으면 경사를 모르는 도막 하나를 답한다. 그 길이에서는
    고도차가 몇 m 를 넘지 않아 시간에 영향이 없다 — 차를 대고 바로 서는 자리다.
    """
    if len(points) < 2:
        return ()

    # 먼저 도막 경계(점 인덱스)만 잡는다. 경사·고도는 경계가 확정된 뒤 한 번만 잰다 —
    # 자투리를 붙이면 마지막 도막의 양 끝이 달라지므로 미리 재면 버리는 값이 생긴다.
    bounds: list[tuple[int, int]] = []
    i = 0
    while i < len(points) - 1:
        j = i + 1
        while j < len(points) and length_m(points[i : j + 1]) < window:
            j += 1
        if j >= len(points):
            break
        bounds.append((i, j))
        i = j

    if not bounds:
        return (Span(length_m(points), None, None),)
    if bounds[-1][1] < len(points) - 1:
        bounds[-1] = (bounds[-1][0], len(points) - 1)

    out = []
    for a, b in bounds:
        piece = points[a : b + 1]
        out.append(Span(length_m(piece), slope_deg(piece), climb_m(piece)))
    return tuple(out)


def ascent_m(points) -> float | None:
    """경로가 실제로 **오른 만큼**(m). 표고를 모르면 None.

    `climb_m` 은 양 끝의 순 고도차라 오르내리는 길에서 모자란다 — 저지오름은
    순 111.7m 인데 실제로 오르는 것은 146.7m 다. 점마다 더하면 격자 잔 톱니가
    전부 쌓이므로, 경사를 잴 수 있는 도막(`spans`) 단위로만 더한다.
    """
    got = spans(points)
    if not got or all(s.climb_m is None for s in got):
        return None
    return round(sum(s.climb_m for s in got if s.climb_m and s.climb_m > 0), 1)


def walk_speed_kmh(slope: float | None) -> float:
    """그 경사에서의 보행 속도(km/h) — Márquez-Pérez(2017) 수정 Tobler 함수.

    경사를 모르면 평지로 본다. 그런 도막은 `MIN_M` 보다 짧은 경로뿐이고, 그 길이의
    고도차는 시간에 영향이 없다.
    """
    s = math.tan(math.radians(slope or 0.0))
    return _WALK_A * math.exp(-_WALK_B * abs(_WALK_C * s + _WALK_D))


def walk_minutes(points) -> float | None:
    """경로를 걷는 **편도** 시간(분). 점이 모자라면 None.

    도막마다 경사를 넣어 속도를 구하고 그 시간을 더한다. 경로 평균 경사로 한 번에
    계산하면 안 된다 — 새별오름은 평균 7.6° 지만 실제로는 +15°·+21° 구간이 있고,
    함수가 볼록해 평균으로 재면 늘 짧게 나온다.

    **왕복은 이 값의 두 배가 아니다.** 함수가 오르막·내리막에 비대칭이라(내려올 때가
    빠르다) 왕복이 필요하면 반대 방향으로 다시 적분해야 한다.

    야간·짐은 들어 있지 않다. 그 감속을 잰 공표 자료를 찾지 못했고, 없는 계수를
    지어내지 않는다(`docs/decisions.md`).
    """
    got = spans(points)
    if not got:
        return None
    return round(
        sum(s.metres / 1000.0 / walk_speed_kmh(s.slope_deg) * 60.0 for s in got), 1
    )
