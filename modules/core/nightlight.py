"""VIIRS 야간광 — 근거리 지상광 (순수 함수 + 정적 격자 조회).

광공해 3신호 중 **중간 규모**를 맡는다(SQM 광역 · 이 모듈 국지 · 가로등 발밑).
VIIRS 는 위성이 위에서 내려다본 지상의 불빛이라, 하늘밝기(SQM)와는 다른 것을 잰다 —
가로등 '자체'가 VIIRS 이고, 그 빛이 공기 중에 퍼져 만든 뿌연 하늘이 SQM 이다.

**절댓값을 판정에 쓰지 않는다.** 두 가지 이유가 실측으로 확인됐다.

1. 어두운 곳끼리 구별하지 못한다. 제주 최상급 대역(SQM 21.5~22.0) 픽셀의 **96%가
   값이 정확히 0** 이다. Black Marble 이 잔여 배경 노이즈를 없애려 0.5 nW·cm⁻²·sr⁻¹
   미만을 0 으로 두기 때문(Black Marble User Guide). VIIRS=0 인 픽셀들의 실제 SQM 은
   20.85~21.81 로 흩어져 있다 — 하늘밝기로 2.4배 차이인데 VIIRS 는 다 같은 0 이다.
2. 보유 래스터는 0 < v < 0.5 구간에 3,864픽셀이 있다. 임계가 살아 있는 원본이라면
   비어야 할 구간이므로 재샘플링 파생물로 판단된다.

그래서 이 모듈이 답하는 것은 딱 하나다 — **"근처에 밝은 광원이 있는가"**. 있다(크다)는
신호는 유효하고, 없다(0)는 신호는 "어둡다"가 아니라 "0.5 미만"일 뿐이다. 어두운 쪽의
분해능은 전적으로 SQM(`darkness.py`)이 담당한다.

SB(30초각≈0.9km)보다 4배 촘촘한 15초각(≈0.46km)이라, SB 픽셀 평균에 묻히는 국지
광원을 잡아내는 것이 이 축의 실익이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from modules import path

_GRID_PATH = path.VIIRS_GRID

# --- 상수 --------------------------------------------------------------------

#: 위도 1도의 거리(km) — 평균 지구 반경 6371.0088 km 기준.
KM_PER_DEG: float = 111.19492664455873

#: Black Marble 의 배경 노이즈 임계(nW·cm⁻²·sr⁻¹). 이 미만은 원본에서 0 으로 처리된다.
#: 따라서 "광원 있음"을 말할 수 있는 최소 단위이기도 하다.
NOISE_FLOOR: float = 0.5

#: 집계 반경(km). 근거리는 관측지 주변, 광역은 주변 시가화 정도의 눈금.
NEAR_KM: float = 1.0
WIDE_KM: float = 3.0

# --- 격자 로드 ----------------------------------------------------------------

_npz = np.load(_GRID_PATH)
_GRID = _npz["grid"]
_ORIGIN_LON, _ORIGIN_LAT, _SCALE, _NODATA = (float(x) for x in _npz["affine"])
_NROWS, _NCOLS = _GRID.shape

#: attribution 최상위에 축어로 노출할 데이터 귀속.
SOURCE: str = str(_npz["source"])

_LON_MIN, _LON_MAX = _ORIGIN_LON, _ORIGIN_LON + _NCOLS * _SCALE
_LAT_MIN, _LAT_MAX = _ORIGIN_LAT - _NROWS * _SCALE, _ORIGIN_LAT


def _lit_pixels() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """불이 켜진 픽셀만 (위도, 경도, 복사휘도) 평탄 배열로.

    유효 픽셀의 71.9% 가 정확히 0 이라 미리 걷어낸다 — 최대·합 어느 쪽에도 0 은
    기여하지 않으므로 결과는 같고 조회는 3.5배 가볍다. nodata(−999.9)는 부동소수라
    근사로 거른다.
    """
    valid = (np.abs(_GRID - _NODATA) > 1e-3) & (_GRID > 0) & ~np.isnan(_GRID)
    rows, cols = np.nonzero(valid)
    lats = _ORIGIN_LAT - (rows + 0.5) * _SCALE  # 픽셀 '중심'
    lons = _ORIGIN_LON + (cols + 0.5) * _SCALE
    return lats, lons, _GRID[rows, cols].astype(np.float64)


_LIT_LAT, _LIT_LON, _LIT_VAL = _lit_pixels()


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class NightLight:
    """관측지 주변 야간광.

    near_max: 반경 1km 내 최대 복사휘도(nW·cm⁻²·sr⁻¹). 광원이 없으면 0.0.
    wide_max: 반경 3km 내 최대 복사휘도 — 조금 떨어진 대광원(시설·항·읍내)의 눈금.
    at_site:  관측지 픽셀 자체의 값. 0 은 "어둡다"가 아니라 "임계 0.5 미만"이다.
    """

    near_max: float
    wide_max: float
    at_site: float


# --- 조회 ---------------------------------------------------------------------

def value_at(lat: float, lon: float) -> float | None:
    """(lat, lon) 픽셀의 복사휘도. 격자 밖·결측이면 None.

    래스터는 좌상단 모서리가 원점인 area 픽셀이라 인덱스는 내림으로 구한다.
    """
    col = int(math.floor((lon - _ORIGIN_LON) / _SCALE))
    row = int(math.floor((_ORIGIN_LAT - lat) / _SCALE))
    if not (0 <= row < _NROWS and 0 <= col < _NCOLS):
        return None
    val = float(_GRID[row, col])
    if abs(val - _NODATA) < 1e-3 or math.isnan(val):
        return None
    return val


def assess(lat: float, lon: float) -> NightLight | None:
    """(lat, lon) 주변 야간광. 격자 밖이면 None."""
    if not (_LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX):
        return None

    dy = (_LIT_LAT - lat) * KM_PER_DEG
    dx = (_LIT_LON - lon) * KM_PER_DEG * math.cos(math.radians(lat))
    dist = np.hypot(dx, dy)

    def _max_within(radius_km: float) -> float:
        sel = dist <= radius_km
        return round(float(_LIT_VAL[sel].max()), 2) if sel.any() else 0.0

    site = value_at(lat, lon)
    return NightLight(
        near_max=_max_within(NEAR_KM),
        wide_max=_max_within(WIDE_KM),
        at_site=round(site, 2) if site is not None else 0.0,
    )


# --- 표현 헬퍼 (문구) ---------------------------------------------------------

def describe(n: NightLight) -> str:
    """야간광을 사람이 읽는 한 줄로. '없음'을 어둡다고 단정하지 않는다.

    단위(nW·cm⁻²·sr⁻¹)는 문장에서 뺐다 — 사용자가 알아듣지 못하는 말이라
    작은 모델이 그대로 옮기면 답이 읽히지 않는다. 값 자체는 `numbers` 에
    그대로 남아 있으므로 필요한 쪽은 거기서 읽는다.
    """
    if n.near_max < NOISE_FLOOR:
        if n.wide_max >= NOISE_FLOOR:
            return (
                f"인공위성으로 내려다보면 {NEAR_KM:g}km 안은 어둡지만 "
                f"{WIDE_KM:g}km 안에 밝은 곳이 있어요 (밝기 {n.wide_max:g})"
            )
        return f"인공위성에 잡히는 밝은 불빛이 {WIDE_KM:g}km 안에 없어요"
    return (
        f"{NEAR_KM:g}km 안에 불빛이 있어요 (위성이 잰 밝기 {n.near_max:g})"
    )
