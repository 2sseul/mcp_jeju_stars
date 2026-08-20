"""카카오맵에서 검색해 둔 장소 — 후보 보강 (정적 CSV 조회).

공공데이터 주차장(`parking.py`)은 **공영만** 담는다. 관측지 후보로는 공원·휴게소처럼
밤에 차를 대고 하늘을 볼 수 있는 자리가 더 필요한데, 그건 카카오맵 검색에서만 나온다.
`scripts/fetch_kakao_places.py` 가 긁어 둔 CSV 를 여기서 읽는다.

파일이 없으면 **빈 목록**이다 — 예외를 던지지 않는다. 이 데이터는 검색으로 언제든
다시 만드는 보강분이라, 없다고 검토 도구 전체가 못 뜨면 안 된다.

키워드 검색분에는 이름만 걸린 엉뚱한 곳이 섞여 있다(휴게소 검색에 편의점, 공원
검색에 화장실·시설물). **여기서 거르지 않는다** — 무엇을 후보로 볼지는 사람이
검토하며 정할 일이고, 규칙으로 먼저 자르면 그 판단이 코드에 숨는다. 대신 원본
분류(`category`)를 그대로 실어 화면에서 보고 판단할 수 있게 한다.

같은 장소가 두 검색에 다 걸리기도 한다(예: "1100고지휴게소 주차장"은 주차장·휴게소
양쪽에). 카카오 장소 id 로 **한 번만** 싣는다 — 지도에 점이 겹쳐 두 번 찍히면 같은
곳을 두 번 판단하게 된다.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

import numpy as np

from modules import path
from modules.core import lamps

#: 좌표 유효 범위. `lamps.py`·`parking.py` 와 같은 경계 — 세 데이터를 한 지도에
#: 겹쳐 쓰므로 한쪽에만 있는 지점이 생기면 안 된다.
_LAT_RANGE = (33.0, 33.7)
_LON_RANGE = (126.0, 127.1)

#: 읽는 순서. 같은 장소가 여러 파일에 있으면 **먼저 온 파일의 것**을 남긴다.
#: `scripts/fetch_kakao_places.py` 의 TARGETS 순서와 같다.
SOURCES = ("parking", "park", "rest_area", "store")

#: attribution 최상위에 축어로 노출할 데이터 귀속.
SOURCE: str = "장소 검색: 카카오맵 (Kakao Corp.) — 로컬 API 카테고리·키워드 검색 결과."


@dataclass(frozen=True)
class Place:
    """카카오맵 장소 하나.

    source:   어느 검색에서 나왔는가(파일 이름). 화면의 레이어 토글이 이걸로 가른다.
    category: 카카오 원본 분류(예: "교통,수송 > 교통시설 > 주차장"). 키워드 검색의
              군더더기를 사람이 눈으로 거를 때 쓰는 유일한 단서라 그대로 싣는다.
    url:      카카오맵 상세 페이지. 로드뷰로도 안 보일 때 여기서 사진·후기를 본다.
    """

    source: str
    id: str
    name: str
    lat: float
    lon: float
    category: str
    address: str
    url: str


def _read(source: str) -> list[Place]:
    csv_path = path.KAKAO_PLACES / f"{source}.csv"
    if not csv_path.exists():
        return []
    text = csv_path.read_bytes().decode("utf-8-sig")
    out: list[Place] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            lat, lon = float(row["lat"]), float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]):
            continue
        if not (_LON_RANGE[0] <= lon <= _LON_RANGE[1]):
            continue
        out.append(
            Place(
                source=source,
                id=row["id"].strip(),
                name=row["place_name"].strip(),
                lat=lat,
                lon=lon,
                category=row["category_name"].strip(),
                address=(row["road_address_name"].strip()
                         or row["address_name"].strip()),
                url=row["place_url"].strip(),
            )
        )
    return out


def _load() -> tuple[Place, ...]:
    """CSV 들을 합치고 장소 id 로 중복을 없앤다. 모듈 로드 시 1회."""
    seen: dict[str, Place] = {}
    for source in SOURCES:
        for place in _read(source):
            seen.setdefault(place.id, place)
    return tuple(seen.values())


_PLACES = _load()

#: 사용 가능한 장소 총수(중복 제거 후).
COUNT: int = len(_PLACES)


def places() -> tuple[Place, ...]:
    """전체 장소. 읽기 전용 뷰."""
    return _PLACES


def counts() -> dict[str, int]:
    """검색별 장소 수(중복 제거 후 기준). 화면의 레이어 이름에 쓴다."""
    out = {source: 0 for source in SOURCES}
    for place in _PLACES:
        out[place.source] += 1
    return out


# --- 반경 조회 ------------------------------------------------------------------
#
# `core.toilet`·`core.parking` 과 같은 모양이다. 공영 표준데이터가 담지 않는
# 오름·해변·관광지 주차장이 여기 있어(카카오 1,912곳), 등록되지 않은 자리 주변을
# 물을 때는 둘을 함께 봐야 "주차할 데가 있나"에 답할 수 있다.

#: 기본 반경(m). `toilet.WALK_M`·`parking.WALK_M` 과 같은 값·같은 이유.
WALK_M: float = 200.0


@dataclass(frozen=True)
class Nearby:
    """어떤 자리에서 본 장소 하나 — 그 자리와의 거리를 함께."""

    place: Place
    distance_m: float


_LAT = np.array([p.lat for p in _PLACES], dtype=np.float64)
_LON = np.array([p.lon for p in _PLACES], dtype=np.float64)
_SOURCE = np.array([p.source for p in _PLACES], dtype="<U16")


def _distances_m(lat: float, lon: float) -> np.ndarray:
    """모든 장소까지의 거리(m). 등거리 평면 근사(`core.toilet` 와 같다)."""
    dy = (_LAT - lat) * lamps.KM_PER_DEG
    dx = (_LON - lon) * lamps.KM_PER_DEG * math.cos(math.radians(lat))
    return np.hypot(dx, dy) * 1000.0


def near(
    lat: float,
    lon: float,
    radius_m: float = WALK_M,
    source: str | None = None,
) -> tuple[Nearby, ...]:
    """반경 안의 장소 — 가까운 순. `source` 를 주면 그 갈래만(예: "parking")."""
    if not _PLACES:
        return ()
    distance = _distances_m(lat, lon)
    within = distance <= radius_m
    if source is not None:
        within &= _SOURCE == source
    hit = np.flatnonzero(within)
    order = hit[np.argsort(distance[hit])]
    return tuple(
        Nearby(place=_PLACES[int(i)], distance_m=float(distance[int(i)]))
        for i in order
    )
