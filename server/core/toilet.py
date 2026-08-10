"""공중화장실 근접 조회 — 관측지에 오래 머물 수 있는가 (정적 CSV 조회).

별을 보는 일은 **한자리에 오래 서 있는 일**이다. 암순응에만 20~30분이 걸리고,
가족·단체는 그보다 더 머문다. 그래서 화장실 유무는 있으면 좋은 부가정보가 아니라
"여기서 두 시간을 보낼 수 있는가"를 가르는 조건이고, 없으면 사람들은 어두운 곳을
찾아 흩어진다 — 안전 문제이기도 하다(`architecture.md` §0).

어둡기(`darkness`)와 달리 이 모듈은 **판정에 들어가지 않는다**. 어두운 곳을 화장실
때문에 떨어뜨리지는 않는다 — 답에 덧붙는 정보다.

데이터
--------------------------------------------------------------------------
공공데이터포털 전국 공중화장실 표준데이터 중 제주 849행. 원본에 좌표가 없어
`scripts/geocode_toilets.py` 가 주소를 카카오 주소검색으로 바꿔 컬럼에 채운다 —
그 스크립트를 아직 돌리지 않았으면 이 모듈은 **빈 목록**이다(예외를 던지지 않는다).

좌표를 못 찾은 행은 빈 칸으로 남아 여기서 빠진다(53행 — 그중 30행은 서비스 범위
밖인 추자면이라 어차피 빠질 것이었다).
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

import numpy as np

from server import path
from server.core import lamps

#: 기본 반경(m). 관측 자리에서 **걸어서 2~3분** — 차를 두고 다녀올 수 있고, 밤에
#: 손전등 하나로 오갈 만한 거리다. 그보다 멀면 "있다"고 말해도 실제로 쓰지 않는다.
WALK_M: float = 200.0

#: 좌표 유효 범위. `core.lamps`·`core.parking`·`core.places` 와 같은 경계 —
#: 네 데이터를 한 지도에 겹쳐 쓰므로 한쪽에만 있는 지점이 생기면 안 된다.
_LAT_RANGE = (33.0, 33.7)
_LON_RANGE = (126.0, 127.1)

#: attribution 최상위에 축어로 노출할 데이터 귀속.
SOURCE: str = (
    "공중화장실: 공공데이터포털 전국 공중화장실 표준데이터(제주 849행). "
    "좌표는 원본에 없어 카카오맵 주소검색으로 변환했다(796행 확인)."
)


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Toilet:
    """공중화장실 한 곳.

    kind:  개방화장실(민간 개방) · 공중화장실 · 간이화장실. 야간에 실제로 열려
           있는지가 셋이 다르다.
    hours: 개방시간. '상시'면 24시간이고, 아니면 '09:00~18:00' 같은 시각이 온다 —
           **밤에 갈 수 있는가**가 이 필드에서 갈린다.
    bell:  비상벨 설치 여부(Y/N). 야간에 인적 없는 곳을 권하는 것이라 안전 표시다.
    """

    name: str
    kind: str
    lat: float
    lon: float
    address: str
    hours: str
    bell: bool
    phone: str


@dataclass(frozen=True)
class Nearby:
    """관측지에서 본 화장실 한 곳 — 그 자리와의 거리를 함께."""

    toilet: Toilet
    distance_m: float


# --- 로드 ---------------------------------------------------------------------

def _hours(row: dict) -> str:
    """개방시간 한 줄. '상시'는 그대로, 나머지는 상세 시각을 앞세운다.

    원본은 구분(`개방시간`: 상시·정시)과 상세(`개방시간상세`: '09:00~18:00')를 따로
    담는데, 사람이 읽을 때 필요한 것은 **몇 시까지 열려 있나** 한 가지다.
    """
    kind = (row.get("개방시간") or "").strip()
    detail = (row.get("개방시간상세") or "").strip()
    if not detail:
        return kind
    if kind and kind not in ("정시", "상시"):
        return f"{detail} ({kind})"
    return detail


def _read() -> list[Toilet]:
    if not path.TOILET.exists():
        return []
    text = path.TOILET.read_bytes().decode("utf-8-sig")
    out: list[Toilet] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            lat, lon = float(row["위도"]), float(row["경도"])
        except (KeyError, TypeError, ValueError):
            continue  # 주소를 좌표로 못 바꾼 행 — 빈 칸으로 남아 있다
        if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]):
            continue
        if not (_LON_RANGE[0] <= lon <= _LON_RANGE[1]):
            continue  # 추자면
        out.append(
            Toilet(
                name=(row.get("화장실명") or "").strip(),
                kind=(row.get("구분명") or "").strip(),
                lat=lat,
                lon=lon,
                address=((row.get("소재지도로명주소") or "").strip()
                         or (row.get("소재지지번주소") or "").strip()),
                hours=_hours(row),
                bell=(row.get("비상벨설치여부") or "").strip().upper() == "Y",
                phone=(row.get("전화번호") or "").strip(),
            )
        )
    return out


def _load() -> tuple[tuple[Toilet, ...], np.ndarray, np.ndarray]:
    """화장실 목록과 좌표 배열. 모듈 로드 시 1회.

    좌표를 배열로 따로 두는 것은 반경 조회를 한 번에 재기 위해서다 — 관측지 106곳과
    화장실 796곳을 낱개 루프로 맞물려 돌 이유가 없다.
    """
    rows = _read()
    if not rows:
        empty = np.empty(0, dtype=np.float64)
        return (), empty, empty
    lat = np.array([t.lat for t in rows], dtype=np.float64)
    lon = np.array([t.lon for t in rows], dtype=np.float64)
    return tuple(rows), lat, lon


_TOILETS, _LAT, _LON = _load()

#: 좌표가 확인된 화장실 총수.
COUNT: int = len(_TOILETS)


def toilets() -> tuple[Toilet, ...]:
    """전체 화장실. 읽기 전용 뷰."""
    return _TOILETS


# --- 조회 ---------------------------------------------------------------------

def _distances_m(lat: float, lon: float) -> np.ndarray:
    """모든 화장실까지의 거리(m). 몇 km 규모라 등거리 평면 근사로 충분하다
    (`core.lamps._distances_m` 와 같은 근사)."""
    dy = (_LAT - lat) * lamps.KM_PER_DEG
    dx = (_LON - lon) * lamps.KM_PER_DEG * math.cos(math.radians(lat))
    return np.hypot(dx, dy) * 1000.0


def near(lat: float, lon: float, radius_m: float = WALK_M) -> tuple[Nearby, ...]:
    """반경 안의 화장실 — 가까운 순. 없으면 빈 튜플."""
    if not _TOILETS:
        return ()
    distance = _distances_m(lat, lon)
    hit = np.flatnonzero(distance <= radius_m)
    order = hit[np.argsort(distance[hit])]
    return tuple(
        Nearby(toilet=_TOILETS[int(i)], distance_m=float(distance[int(i)]))
        for i in order
    )


def nearest(lat: float, lon: float) -> Nearby | None:
    """반경과 무관하게 가장 가까운 화장실 하나. 하나도 없으면 None.

    반경 안에 없을 때 **얼마나 멀리 있나**를 말하기 위한 것이다 — "없음"과
    "300m 밖에 있음"은 계획이 달라진다.
    """
    if not _TOILETS:
        return None
    distance = _distances_m(lat, lon)
    i = int(np.argmin(distance))
    return Nearby(toilet=_TOILETS[i], distance_m=float(distance[i]))
