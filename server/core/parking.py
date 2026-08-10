"""공영주차장 — 야간에 차를 세울 수 있는 지점 (정적 CSV 조회).

관광객은 **차를 세운 자리에서** 별을 본다. 어두운 곳을 찾는 것과 밤에 초행길로
갈 수 있는 곳을 찾는 것은 다른 문제이고, 후자의 최소 조건이 "세울 데가 있는가"다.
갓길·농로에 세우는 것은 관측 실패가 아니라 안전 문제라서(`architecture.md` §0)
주차 가능 지점은 결과에 덧붙는 정보가 아니라 **후보를 거르는 축**으로 쓴다.

지금은 **지도 표기용 로더**다 — 판정(`judge`)에는 들어가지 않는다. 후보 풀(P9)에서
어둡기·토지소유와 교집합을 낼 때 이 모듈이 그 주차 축이 된다.

데이터
--------------------------------------------------------------------------
공공데이터포털 주차장정보 표준데이터 2종(데이터기준일자 2026-04-16). 둘 다 UTF-8(BOM).

    제주시   1,544행 → 좌표 유효 1,444행
    서귀포시   113행 → 좌표 유효   113행

전부 **공영·연중 00:00~23:59** 라 운영시간은 행마다 같다 — 구분이 되지 않으므로
싣지 않는다. 실제로 갈리는 것은 유형(노외/노상)·구획수·요금뿐이다.

**가로등 데이터와 달리 위경도 뒤바뀜은 없다.** 대신 제주시 파일에 좌표가 빈 행이
85개 있고(주소만 있음), 추자면 15행은 서비스 범위(33.0~33.7) 밖이라 빠진다 —
`lamps.py` 가 추자면 가로등을 빼는 것과 같은 경계다.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from server import path

# --- 상수 --------------------------------------------------------------------

#: 좌표 유효 범위. `lamps.py` 와 같은 경계 — 두 축을 같은 지도에 겹쳐 쓰므로
#: 한쪽에만 있는 지점이 생기면 안 된다. 추자면(≈33.95°N)은 여기서 빠진다.
_LAT_RANGE = (33.0, 33.7)
_LON_RANGE = (126.0, 127.1)

#: 원본 파일. 둘 다 UTF-8(BOM) 로 배포된다(가로등 파일과 달리 인코딩이 같다).
_SOURCES = (path.PARKING_JEJU, path.PARKING_SEOGWIPO)
_ENCODING = "utf-8-sig"

#: attribution 최상위에 축어로 노출할 데이터 귀속.
SOURCE: str = (
    "공영주차장: 공공데이터포털 주차장정보 표준데이터 — "
    "제주특별자치도 제주시(1,544행) · 서귀포시(113행), 데이터기준일자 2026-04-16."
)


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Parking:
    """공영주차장 한 곳.

    code:  주차장관리번호. 원본이 주는 안정된 키라, 사람이 검토해 남긴 판단을
           이 값으로 붙인다(`scripts/review_parking.py`).
    kind:  노외(주차장 부지) · 노상(도로변 구획). 밤에 오래 세워 두는 관측에는
           노외가 맞고 노상은 통행 차량 곁이라 성격이 다르다.
    slots: 주차구획수.
    fee:   무료 · 유료 · 혼합.
    """

    code: str
    name: str
    lat: float
    lon: float
    kind: str
    slots: int
    fee: str
    address: str


# --- 로드 ---------------------------------------------------------------------

def _read(csv_path) -> list[Parking]:
    """CSV 한 개에서 좌표가 유효한 주차장만 뽑는다."""
    rows = csv.DictReader(io.StringIO(csv_path.read_bytes().decode(_ENCODING)))
    lots: list[Parking] = []
    for row in rows:
        try:
            lat = float(row["위도"])
            lon = float(row["경도"])
        except (KeyError, TypeError, ValueError):
            continue  # 좌표가 비었거나 숫자가 아닌 행(제주시 85행)
        if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]):
            continue
        if not (_LON_RANGE[0] <= lon <= _LON_RANGE[1]):
            continue  # 추자면
        try:
            slots = int(row["주차구획수"])
        except (TypeError, ValueError):
            slots = 0
        lots.append(
            Parking(
                code=row["주차장관리번호"].strip(),
                name=row["주차장명"].strip(),
                lat=lat,
                lon=lon,
                kind=row["주차장유형"].strip(),
                slots=slots,
                fee=row["요금정보"].strip(),
                address=(row["소재지도로명주소"].strip()
                         or row["소재지지번주소"].strip()),
            )
        )
    return lots


def _load() -> tuple[Parking, ...]:
    """두 CSV 를 합친다. 모듈 로드 시 1회."""
    return tuple(lot for csv_path in _SOURCES for lot in _read(csv_path))


_LOTS = _load()

#: 사용 가능한 공영주차장 총수(좌표 유효, 범위 밖 제외).
COUNT: int = len(_LOTS)


def lots() -> tuple[Parking, ...]:
    """전체 공영주차장. 읽기 전용 뷰."""
    return _LOTS
