"""위성 구름 마스크 -> 운량 비율 -> CloudRank 변환 (순수 함수, 네트워크 없음).

배치 위치: server/core/cloud.py

GK2A 구름탐지(CLD)는 화소당 범주값만 준다. 반면 판정에 쓰는 임계값
(Xin et al. 2020, PTB 30% / STB 50%)은 운량 백분율 기준이다. 그래서 단일
화소가 아니라 관측지 주변 창(window)의 구름 화소 비율을 운량으로 삼는다.

창 크기 근거
------------
관측자가 고도각 A까지 하늘을 본다고 하면, 고도 h의 구름은 수평거리
h / tan(A) 지점까지 시야에 들어온다.

    A = 30deg, h = 3km  ->  3 / tan(30deg) = 5.2km

즉 반경 약 5km. 2km 격자에서 half=2(5x5, 10km x 10km)가 여기에 대응한다.

명시해 두는 전제 두 가지:
  * 고도각 컷오프 30도 — 그 아래는 지형/수목에 가려지는 경우가 많아 제외
  * 대표 운고 3km — 층별로 반경이 달라지지만(하층 ~2km, 상층 ~14km)
    층 구분을 두지 않기로 한 방침에 따라 중층 기준 하나로 대표시킨다

표본 25개이므로 운량 해상도는 4%p, 임계값은 30% -> 8칸, 50% -> 13칸이 된다.

CLD 코드값 (API 활용가이드 1-2, 2026-08 확정)
---------------------------------------------
    0: cloud (Confidence)      -> 구름
    1: cloud (Low Confidence)  -> 구름(확신 낮음)
    2: clear (Confidence)      -> 청천
    3: TBD                     -> 정의 없음. clients/gk2a.py에서 MISSING으로 변환

0과 1이 모두 cloud라는 점에 주의. 1을 어떻게 셀지는 partial_weight로 조절한다.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

__all__ = [
    "MISSING",
    "WINDOW_HALF",
    "CLD_CLOUDY",
    "CLD_PARTIAL",
    "CLD_CLEAR",
    "CLOUD_RANK_EDGES",
    "cloud_fraction",
    "cloud_rank",
]

MISSING = -1

#: 5x5 창 = 10km x 10km. 위 근거 참조.
WINDOW_HALF = 2

#: 확실한 구름 / 확신 낮은 구름 / 청천
CLD_CLOUDY: tuple[int, ...] = (0,)
CLD_PARTIAL: tuple[int, ...] = (1,)
CLD_CLEAR: tuple[int, ...] = (2,)

#: CloudRank 경계(누적 상한, 비율). 0=최적 1=양호 2=밝은 별 한정 3=불가
CLOUD_RANK_EDGES: tuple[float, float, float] = (0.10, 0.30, 0.50)


def cloud_fraction(
    values: np.ndarray,
    iy: int,
    ix: int,
    *,
    half: int = WINDOW_HALF,
    partial_weight: float = 1.0,
    min_valid: int = 5,
) -> float | None:
    """(iy, ix) 주변 창의 구름 비율을 0.0~1.0으로 되돌린다.

    Parameters
    ----------
    values         : (ydim, xdim) 정수 배열. 결측은 MISSING(-1)
    half           : 창 반폭. 5x5를 원하면 2
    partial_weight : cloud(Low Confidence)를 몇으로 셀지. 맨눈 관측은 놓치는
                     쪽이 더 아프므로 기본 1.0(구름으로 간주). 0.5로 낮추면
                     완화되고, 0.0이면 확실한 구름만 센다.
    min_valid      : 유효 화소가 이보다 적으면 None(판정 보류)

    Returns
    -------
    비율, 또는 유효 표본이 부족하면 None. 창은 배열 경계에서 잘린다.
    """
    if values.ndim != 2:
        raise ValueError(f"2차원 배열이 필요합니다 (받은 shape={values.shape})")
    ny, nx = values.shape
    if not (0 <= iy < ny and 0 <= ix < nx):
        raise IndexError(f"격자 범위 밖: (iy={iy}, ix={ix}), shape={values.shape}")
    if not 0.0 <= partial_weight <= 1.0:
        raise ValueError("partial_weight는 0.0~1.0 사이여야 합니다")

    window = values[
        max(iy - half, 0) : min(iy + half + 1, ny),
        max(ix - half, 0) : min(ix + half + 1, nx),
    ]

    valid = window >= 0
    n_valid = int(valid.sum())
    if n_valid < min_valid:
        return None

    cloudy = int((np.isin(window, CLD_CLOUDY) & valid).sum())
    partial = int((np.isin(window, CLD_PARTIAL) & valid).sum())
    return (cloudy + partial_weight * partial) / n_valid


def cloud_rank(
    fraction: float | None,
    *,
    edges: Sequence[float] = CLOUD_RANK_EDGES,
) -> int | None:
    """운량 비율을 CloudRank(0~3)로 변환한다.

    0 = 최적(<=10%) / 1 = 양호(<=30%) / 2 = 밝은 별 한정(<=50%) / 3 = 불가(>50%)
    fraction이 None이면 None을 그대로 흘려보낸다(판정 보류).
    """
    if fraction is None:
        return None
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"비율은 0.0~1.0이어야 합니다 (받은 값={fraction})")
    for rank, edge in enumerate(edges):
        if fraction <= edge:
            return rank
    return len(edges)