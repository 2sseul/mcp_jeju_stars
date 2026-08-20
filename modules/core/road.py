"""도로 근접 — 밤에 초행길로 닿을 수 있는가 (순수 함수 + 정적 배열 조회).

관측지 추천은 안전 문제다(`architecture.md` §0). 어두운 곳을 찾는 것과 **초행에
밤에 갈 수 있는 곳**을 찾는 것은 다른 문제이고, 후자의 첫 조건이 "차로 닿는
길이 있는가"다. 격자에서 뽑은 좌표가 농로 끝이거나 사유지 진입로면 어둡기가
아무리 좋아도 내보낼 수 없다.

`scripts/sweep_place_candidates.py` 는 이 축을 **후보를 거르는 문턱**으로 썼다
(주행 가능 도로 300m 안). 이 모듈은 같은 데이터를 **한 지점에 대해 묻는** 쪽으로
연다 — 편집 도구가 "여기는 어떤 길로 가나"를 화면에 띄우기 위한 것이다.

데이터
--------------------------------------------------------------------------
`data/road/jeju_road_darkness.npz` — OpenStreetMap 도로망(Overpass)을 150m 간격
세그먼트 63,662개로 자른 것. `scripts/build_darkness_grid.py` 계열 배치가 만든다.

거리는 **세그먼트 중점까지**로 잰다(`sweep_place_candidates.py` 와 같은 방식).
150m 간격이라 최대 75m 어긋나는데, 여기서 묻는 것은 "옆에 길이 있나 / 300m
밖인가"라 그 오차로 답이 뒤집히지 않는다.

무엇을 도로로 치지 않나
--------------------------------------------------------------------------
`track`(농로·임도)·`service`(사유 진입로·시설 내부)는 길이 있어도 **초행 야간
운전으로 들어갈 곳이 아니다**. 그래서 둘을 나눠 답한다 — 가장 가까운 길과, 가장
가까운 **주행 가능한** 길. 둘의 거리가 크게 벌어지면 그 자리는 농로로만 닿는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from modules import path
from modules.core import lamps

#: 주행 가능으로 치지 않는 등급. `scripts/sweep_place_candidates.py` 와 같은 목록이다 —
#: 후보를 거른 기준과 화면 기준이 다르면 "왜 이게 통과했지"를 설명할 수 없다.
NOT_DRIVABLE: tuple[str, ...] = ("track", "service", "path", "footway", "steps")

#: OSM `highway` 등급 → 사람이 읽는 이름. OSM 위키의 한국 도로 분류를 따른다.
#: 없는 등급은 원문 그대로 보여 준다 — 모르는 것을 그럴듯한 이름으로 덮지 않는다.
_LABEL = {
    "motorway": "고속도로",
    "trunk": "자동차전용도로",
    "primary": "주요 간선도로",
    "secondary": "주요 지방도",
    "tertiary": "지방도",
    "unclassified": "마을 연결도로",
    "residential": "주거지 도로",
    "living_street": "보행 우선 도로",
    "service": "진입로·시설 내 도로",
    "track": "농로·임도",
    "road": "등급 미분류",
    # `_link` 는 나들목·교차로 연결 램프다. 원문 그대로 두면 화면에 영어가 섞인다.
    "motorway_link": "고속도로 연결로",
    "trunk_link": "자동차전용도로 연결로",
    "primary_link": "간선도로 연결로",
    "secondary_link": "주요 지방도 연결로",
    "tertiary_link": "지방도 연결로",
}

_npz = np.load(path.ROAD_DARKNESS, allow_pickle=True)

#: 세그먼트 중점. 양 끝점을 그때그때 평균 내지 않고 미리 만들어 둔다.
_LAT = (_npz["alat"].astype(np.float64) + _npz["blat"].astype(np.float64)) / 2
_LON = (_npz["alon"].astype(np.float64) + _npz["blon"].astype(np.float64)) / 2

#: 세그먼트마다의 도로 등급·이름(way 인덱스를 펼친 것).
_CLASS = _npz["way_class"][_npz["way"]]
_NAME = _npz["way_name"][_npz["way"]]

#: 주행 가능 여부 마스크. 매번 계산하지 않는다.
_DRIVABLE = ~np.isin(_CLASS, NOT_DRIVABLE)

#: attribution 최상위에 축어로 노출할 데이터 귀속(원본 npz 가 적어 둔 것).
SOURCE: str = str(_npz["source"])

#: 세그먼트마다의 가로등 최근접 거리(m)와 세그먼트 길이. 원본 배치가 함께 넣어 둔 값이라
#: 여기서 다시 재지 않는다 — 같은 수를 두 곳에서 계산하면 언젠가 둘이 갈린다.
_LAMP_M = _npz["nearest_m"].astype(np.float64)
STEP_M: float = float(_npz["step_m"])

# 도로별 폭·차선·노면(`scripts/build_road_tags.py`). 아직 안 만들었으면 **없는 채로**
# 돈다 — 이 값들은 어차피 대부분 비어 있어서, 없다고 도구가 못 뜰 이유가 없다.
if path.ROAD_TAGS.exists():
    _tags = np.load(path.ROAD_TAGS, allow_pickle=True)
    _LANES = _tags["lanes"]
    _WIDTH = _tags["width"]
    _SURFACE = _tags["surface"]
else:
    _LANES = np.full(len(_npz["way_class"]), -1, dtype=np.int8)
    _WIDTH = np.full(len(_npz["way_class"]), np.nan, dtype=np.float32)
    _SURFACE = np.full(len(_npz["way_class"]), "", dtype="<U16")

#: 노면 OSM 값 → 사람이 읽는 말. `scripts/build_road_tags.py` 와 같은 표.
SURFACE_LABEL = {
    "asphalt": "아스팔트", "paved": "포장", "concrete": "콘크리트",
    "paving_stones": "블록", "sett": "돌포장", "unpaved": "비포장",
    "gravel": "자갈", "fine_gravel": "잔자갈", "dirt": "흙", "ground": "흙",
    "grass": "풀", "sand": "모래", "compacted": "다짐",
}


def surface_label(surface: str) -> str:
    """노면 값 → 사람이 읽는 말. 모르는 값은 원문 그대로."""
    return SURFACE_LABEL.get(surface, surface)


def coverage() -> dict[str, float]:
    """폭·차선·노면 태그가 전체 도로 중 몇 할에 있나(0~1).

    화면에 그대로 띄우라고 있는 값이다. 대부분의 줄이 '정보 없음'으로 나오는
    이유를 사람이 알아야, 그 빈칸을 데이터의 결함이 아니라 **원본이 원래 그렇다**로
    읽고 위성·로드뷰로 넘어간다.
    """
    total = len(_LANES) or 1
    return {
        "lanes": float((_LANES > 0).sum()) / total,
        "width": float((~np.isnan(_WIDTH)).sum()) / total,
        "surface": float((_SURFACE != "").sum()) / total,
    }

#: 세그먼트 총수.
COUNT: int = int(_LAT.size)

#: 접근 경로를 훑는 반경(m). "도착 전 1km" 라는 말 그대로다.
APPROACH_M: float = 1_000.0


@dataclass(frozen=True)
class Road:
    """관측지에서 가장 가까운 도로 한 조각.

    way_class: OSM `highway` 등급 원문(residential·track…).
    label:     사람이 읽는 이름. 모르는 등급이면 원문 그대로다.
    name:      도로명. OSM 에 이름이 없는 길이 많아 빈 문자열일 수 있다.
    drivable:  초행 야간 운전으로 들어갈 만한 등급인가(농로·진입로는 False).
    """

    way_class: str
    label: str
    name: str
    distance_m: float
    drivable: bool


def label_of(way_class: str) -> str:
    """등급 → 사람이 읽는 이름. 모르는 등급은 원문 그대로."""
    return _LABEL.get(way_class, way_class)


def _distances_m(lat: float, lon: float) -> np.ndarray:
    """모든 세그먼트 중점까지의 거리(m). `core.lamps` 와 같은 등거리 평면 근사."""
    dy = (_LAT - lat) * lamps.KM_PER_DEG
    dx = (_LON - lon) * lamps.KM_PER_DEG * math.cos(math.radians(lat))
    return np.hypot(dx, dy) * 1000.0


def nearest(lat: float, lon: float, drivable_only: bool = False) -> Road | None:
    """가장 가까운 도로. `drivable_only` 면 농로·진입로를 빼고 찾는다.

    도로망이 제주 전역을 덮으므로 실제로 None 이 나오지는 않는다 — 배열이 비어
    있을 때만이고, 그건 데이터가 없다는 뜻이라 예외 대신 None 으로 답한다.
    """
    if not COUNT:
        return None
    distance = _distances_m(lat, lon)
    if drivable_only:
        index = np.flatnonzero(_DRIVABLE)
        if not index.size:
            return None
        i = int(index[np.argmin(distance[index])])
    else:
        i = int(np.argmin(distance))
    way_class = str(_CLASS[i])
    return Road(
        way_class=way_class,
        label=label_of(way_class),
        name=str(_NAME[i]),
        distance_m=float(distance[i]),
        drivable=bool(_DRIVABLE[i]),
    )


# --- 접근 경로 ----------------------------------------------------------------

@dataclass(frozen=True)
class Leg:
    """도착 전 반경 안에 있는 길 하나 — 그 길에 대해 **잰 값**.

    세그먼트를 낱개로 늘어놓으면 150m 짜리 수십 줄이 되어 읽을 수가 없다. 같은
    길(`금백조로`)의 조각을 하나로 묶어야 "무슨 길로 들어가나"가 보인다.

    등급을 사람이 읽는 말로 옮긴 이름(`label`)도, 거기서 나온 '주행 가능' 표시도
    담지 않는다 — 그건 잰 값이 아니라 판정이고, 필요하면 `way_class` 로 언제든
    다시 낼 수 있다(`way_class in NOT_DRIVABLE`).

    nearest_m:     관측지에서 이 길까지 가장 가까운 거리.
    length_m:      반경 안에 든 이 길의 길이(세그먼트 수를 간격으로 곱한 것).
    lamp_median_m: 이 구간 세그먼트들의 가로등 최근접 **중앙값**. 한 구간에 가로등이
                   있냐 없냐를 한 값으로 말하려면 평균보다 중앙값이 맞다 — 끝자락
                   한 개가 평균을 끌어내린다. 구간 전체가 가로등 집계 반경 밖이면
                   **None** 이다(= 그 길에는 빛이 없다).
    lanes:         차선 수. OSM 에 없으면 None — 3.9% 만 있다.
    width_m:       도로 폭(m). OSM 에 없으면 None — 0.8% 만 있다.
    surface:       노면(아스팔트·비포장…). OSM 에 없으면 빈 문자열 — 5.8% 만 있다.

    **없는 값은 추정하지 않는다.** 등급에서 폭을 역산하면(track 이니 좁겠지) 그건
    잰 값이 아니라 짐작이고, 짐작을 화면에 숫자로 띄우면 사람이 그걸 믿는다.
    """

    way_class: str
    name: str
    nearest_m: float
    length_m: float
    lamp_median_m: float | None
    lanes: int | None
    width_m: float | None
    surface: str


def approach(lat: float, lon: float, radius_m: float = APPROACH_M) -> tuple[Leg, ...]:
    """도착 전 반경 안의 길들 — 가까운 순.

    **실제 주행 경로가 아니다.** 저장소에 경로탐색 엔진이 없으므로 이것은 "반경
    안에 이런 길들이 있다"이지 "이 길로 지나간다"가 아니다. 그래도 답이 되는 이유는
    중산간 관측지의 1km 안에는 길이 한두 개뿐이라, 목록이 곧 진입로이기 때문이다.
    시가지에서는 여러 줄이 나오고 그때는 사람이 지도를 봐야 한다.
    """
    if not COUNT:
        return ()
    distance = _distances_m(lat, lon)
    hit = np.flatnonzero(distance <= radius_m)
    if not hit.size:
        return ()

    # 묶는 키는 OSM way 가 아니라 **(등급, 도로명)** 이다. 한 도로가 way 여러 개로
    # 쪼개져 있어(교차로마다 끊긴다) way 로 묶으면 '태평로'가 몇 줄씩 나온다 —
    # 삼매봉에서 80줄이 되어 읽을 수가 없었다. 이름 없는 길은 등급끼리 묶인다.
    grouped: dict[tuple[str, str], list[int]] = {}
    for i in hit:
        grouped.setdefault((str(_CLASS[i]), str(_NAME[i])), []).append(int(i))

    ways = _npz["way"]
    legs: list[Leg] = []
    for (way_class, name), rows in grouped.items():
        index = np.array(rows)
        # 폭·차선·노면은 도로(way)에 붙은 값이라 세그먼트가 아니라 way 로 찾는다.
        # 한 묶음 안에서 값이 갈리면(구간마다 차선이 다른 도로) **가장 좁은 쪽**을
        # 취한다 — 넓은 데를 말해 놓고 좁은 데서 막히는 것이 반대보다 나쁘다.
        way_index = np.unique(ways[index])
        lanes = _LANES[way_index]
        lanes = int(lanes[lanes > 0].min()) if (lanes > 0).any() else None
        width = _WIDTH[way_index]
        width = float(np.nanmin(width)) if not np.isnan(width).all() else None
        surface = next(
            (str(s) for s in _SURFACE[way_index] if str(s)), ""
        )
        # 가로등이 집계 반경 밖인 세그먼트는 NaN 으로 들어 있다 — 그것이 곧
        # '이 구간에는 빛이 없다'는 답이라, 평균에 섞지 않고 따로 답한다.
        lamp = _LAMP_M[index]
        median = float(np.nanmedian(lamp)) if not np.isnan(lamp).all() else None
        legs.append(
            Leg(
                way_class=way_class,
                name=name,
                nearest_m=float(distance[index].min()),
                length_m=float(index.size) * STEP_M,
                lamp_median_m=median,
                lanes=lanes,
                width_m=width,
                surface=surface,
            )
        )
    legs.sort(key=lambda leg: leg.nearest_m)
    return tuple(legs)


def measured(leg: Leg) -> str:
    """길 하나에 대해 **잰 값**만 한 줄로. 없는 것은 없다고 적는다.

    등급(`highway`)은 여기 넣지 않는다. 그것은 OSM 기여자가 고른 분류이지 잰 값이
    아니고, 그걸로 "들어갈 수 있다/없다"를 말하면 짐작이 사실처럼 읽힌다. 밤에
    초행으로 들어갈지를 가르는 것은 폭·교행 여지·노면인데, 그 셋은 대부분 비어
    있으므로 **비어 있다고 말하는 것**이 이 함수가 하는 가장 정직한 일이다.
    """
    parts = [f"구간 {_fmt_m(leg.length_m)}"]

    if leg.lamp_median_m is None:
        parts.append("가로등 없음")
    else:
        parts.append(f"가로등 최근접 중앙값 {leg.lamp_median_m:.0f}m")

    size = []
    if leg.width_m is not None:
        size.append(f"폭 {leg.width_m:g}m")
    if leg.lanes is not None:
        size.append(f"{leg.lanes}차선")
    parts.append(" · ".join(size) if size else "폭·차선 정보 없음")

    if leg.surface:
        parts.append(surface_label(leg.surface))
    return " · ".join(parts)


def describe_approach(legs: tuple[Leg, ...]) -> str:
    """접근 경로 한 줄 — 사람이 `road` 칸에 적을 초안.

    가장 가까운 길에 대해 **잰 값만** 적는다. 판정("주행 불가"·"어렵다")도, 등급을
    대신 내세우는 말도 하지 않는다 — 앞에서 차가 오면 비켜설 수 있는지는 폭 태그가
    없는 한 데이터가 모르고, 모르는 것을 아는 척하면 그게 제일 위험하다.
    그 자리는 위성사진과 로드뷰로 사람이 본다.
    """
    if not legs:
        return f"반경 {APPROACH_M / 1000:g}km 안에 도로가 없다"

    closest = legs[0]
    head = closest.name or "이름 없는 길"
    return f"{head} {_fmt_m(closest.nearest_m)} 앞 · {measured(closest)}"


#: 이 거리보다 멀면 그 구간은 '가로등 없는 길'로 본다. `core.lamps.NEAR_M` 과 같은
#: 눈금 — 눈에 직접 들어오는 거리라는 뜻이 두 모듈에서 같아야 한다.
_LIT_M = lamps.NEAR_M


def _fmt_m(metres: float) -> str:
    return f"{metres / 1000:.1f}km" if metres >= 1000 else f"{metres:.0f}m"
