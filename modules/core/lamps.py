"""가로등·보안등 근접도 — 국지 광원 (순수 함수 + 정적 CSV 조회).

광공해 3신호 중 **가장 가까운 축**이다. 셋은 같은 물리량(인공 광원)을 서로 다른
공간 규모로 잰다:

    SQM (Sky Brightness, 30초각≈0.9km)  — 광역 하늘밝기. "이 지역 하늘이 어두운가"
    VIIRS (15초각≈0.46km)               — 국지 지상광. "이 근처가 켜져 있는가"
    가로등 (점 좌표, 이 모듈)            — 발밑 광원. "내 눈에 직접 들어오는가"

앞의 둘은 격자라서 관측자 바로 옆 가로등 하나를 픽셀 평균에 묻어 버린다. 그런데
암순응은 시야에 직접 들어오는 광원 하나로 깨진다 — 하늘이 아무리 어두워도 주차장
가로등 밑에 서면 어두운 별은 안 보인다. 그 눈금이 이 모듈이다.

데이터
--------------------------------------------------------------------------
공공데이터포털 **이용허락범위 제한 없음**(자유 이용) 2종을 합친다.

    제주시   가로등현황 (2024-10-10)         52,019행
    서귀포시 가로등·보안등 현황 (2025-07-25)  38,022행

**제주시 데이터는 위도·경도 컬럼이 뒤바뀐 행이 섞여 있다** — 조천읍·구좌읍·한림읍·
우도면이 통째로 그렇다(15,514행). 제주의 위도(≈33)와 경도(≈126)는 값 범위가 겹치지
않으므로 확정적으로 교정된다. 걸러내면 동부 중산간(용눈이오름·산굼부리 권역)에
"가로등이 하나도 없다"는 거짓 판정이 나오므로 **반드시 교정해서 쓴다**.

추자면(≈33.95°N)은 제주 본섬에서 40km 떨어져 서비스 범위(33.19~33.56) 밖이라
자연히 빠진다.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

import numpy as np

from modules import path

# --- 상수 --------------------------------------------------------------------

#: 위도 1도의 거리(km) — 평균 지구 반경 6371.0088 km 기준 (2πR/360).
KM_PER_DEG: float = 111.19492664455873

#: 집계 반경(m). 눈에 직접 들어오는 거리 → 걸어서 벗어날 수 있는 거리 순.
NEAR_M: float = 100.0
MID_M: float = 500.0
FAR_M: float = 1_000.0

#: 좌표 유효 범위(교정 판정용). 제주 본섬 + 부속 도서를 넉넉히 덮는다.
_LAT_RANGE = (33.0, 33.7)
_LON_RANGE = (126.0, 127.1)

#: 원본 파일. 포털은 기관마다 다른 인코딩으로 내려주지만(제주시 UTF-8, 서귀포시
#: CP949) 저장소에 들일 때 `scripts/normalize_csv.py` 로 UTF-8(BOM) 에 맞춘다 —
#: 파일마다 인코딩을 기억해야 하면 새 데이터를 붙일 때마다 같은 실수가 난다.
_SOURCES = (path.LAMPS_JEJU, path.LAMPS_SEOGWIPO)
_ENCODING = "utf-8-sig"

#: attribution 최상위에 축어로 노출할 데이터 귀속.
SOURCE: str = (
    "가로등·보안등: 공공데이터포털 제주특별자치도 제주시_가로등현황(2024-10-10) · "
    "서귀포시_가로등 보안등 현황(2025-07-25). 이용허락범위 제한 없음."
)


# --- 로드 ---------------------------------------------------------------------

def normalize_coord(lat: float, lon: float) -> tuple[float, float] | None:
    """(위도, 경도) 를 바로잡는다. 범위 밖이면 None.

    제주는 위도 33 대, 경도 126 대라 두 값의 범위가 겹치지 않는다. 그래서 컬럼이
    뒤바뀐 행은 **모호함 없이** 되돌릴 수 있다(원본 제주시 파일의 15,514행).
    """
    if _LAT_RANGE[0] <= lat <= _LAT_RANGE[1] and _LON_RANGE[0] <= lon <= _LON_RANGE[1]:
        return lat, lon
    if _LAT_RANGE[0] <= lon <= _LAT_RANGE[1] and _LON_RANGE[0] <= lat <= _LON_RANGE[1]:
        return lon, lat  # 뒤바뀐 행 — 교정
    return None


def _read(csv_path) -> list[tuple[float, float]]:
    """CSV 한 개에서 (위도, 경도) 목록을 뽑는다."""
    text = csv_path.read_bytes().decode(_ENCODING)
    rows = csv.DictReader(io.StringIO(text))
    points: list[tuple[float, float]] = []
    for row in rows:
        try:
            lat = float(row["위도"])
            lon = float(row["경도"])
        except (KeyError, TypeError, ValueError):
            continue  # 좌표가 비었거나 숫자가 아닌 행
        fixed = normalize_coord(lat, lon)
        if fixed is not None:
            points.append(fixed)
    return points


def _load() -> tuple[np.ndarray, np.ndarray]:
    """두 CSV 를 합쳐 (위도, 경도) 배열로. 모듈 로드 시 1회(≈0.1초)."""
    points: list[tuple[float, float]] = []
    for csv_path in _SOURCES:
        points.extend(_read(csv_path))
    arr = np.array(points, dtype=np.float64)
    return arr[:, 0].copy(), arr[:, 1].copy()


_LAT, _LON = _load()

#: 사용 가능한 가로등 총수(교정 후, 범위 밖 제외).
COUNT: int = int(_LAT.size)


def points() -> tuple[np.ndarray, np.ndarray]:
    """전체 가로등 좌표 (위도, 경도) 배열.

    지점 하나를 묻는 `assess` 와 달리 **전체 분포**가 필요한 쪽(밀도 지도 같은 배치
    스크립트)을 위한 읽기 전용 뷰다. 판정 경로는 이 함수를 쓰지 않는다.
    """
    return _LAT, _LON


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Lamps:
    """관측지 주변 가로등 현황.

    nearest_m: 가장 가까운 가로등까지 거리(m). 집계 반경 밖이면 None.
    near:      반경 100m 안의 개수 — 시야에 직접 들어오는 광원.
    mid:       반경 500m 안의 개수.
    far:       반경 1km 안의 개수 — 주변이 시가화됐는지의 눈금.
    """

    nearest_m: float | None
    near: int
    mid: int
    far: int


# --- 조회 ---------------------------------------------------------------------

def _distances_m(lat: float, lon: float) -> np.ndarray:
    """모든 가로등까지의 거리(m). 1km 규모라 등거리 평면 근사로 충분하다."""
    dy = (_LAT - lat) * KM_PER_DEG
    dx = (_LON - lon) * KM_PER_DEG * math.cos(math.radians(lat))
    return np.hypot(dx, dy) * 1000.0


def assess(lat: float, lon: float) -> Lamps:
    """(lat, lon) 주변 가로등 현황. 한 개도 없으면 nearest_m 은 None.

    격자 데이터와 달리 '범위 밖'이라는 개념이 없다 — 점 데이터라 주변에 아무것도
    없으면 그냥 0개다(그 자체가 유의미한 답: 발밑에 조명이 없다).
    """
    d = _distances_m(lat, lon)
    within = d <= FAR_M
    if not within.any():
        return Lamps(nearest_m=None, near=0, mid=0, far=0)
    near_d = d[within]
    return Lamps(
        nearest_m=round(float(near_d.min()), 1),
        near=int((near_d <= NEAR_M).sum()),
        mid=int((near_d <= MID_M).sum()),
        far=int(near_d.size),
    )


# --- 표현 헬퍼 (문구) ---------------------------------------------------------

def describe(lamp: Lamps) -> str:
    """가로등 현황을 사람이 읽는 한 줄로."""
    if lamp.nearest_m is None:
        return f"반경 {FAR_M / 1000:g}km 안에 등록된 가로등이 없어요"
    if lamp.near:
        return (
            f"가장 가까운 가로등이 {lamp.nearest_m:.0f}m 거리예요 "
            f"(100m 안 {lamp.near}개) — 불빛을 등지거나 그늘을 찾으세요"
        )
    return (
        f"가장 가까운 가로등이 {lamp.nearest_m:.0f}m 거리예요 "
        f"(500m 안 {lamp.mid}개 · 1km 안 {lamp.far}개)"
    )
