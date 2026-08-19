"""관측지 목록 — 사람이 검증해 둔 63곳 (순수 함수 + 정적 JSON 조회).

`data/jeju_spots.json` 은 격자에서 뽑은 좌표가 아니라 **로드뷰·위성으로 사람이 하나씩
확인한** 자리다(`plan.md` P9). 그래서 어둡기 말고도 주차·야간 출입·도보·반려동물 같은,
격자에서 나오지 않는 것들이 들어 있다.

원문을 그대로 내보내는 이유
--------------------------------------------------------------------------
`night_access`·`pets` 같은 필드는 대부분 정해진 말("상시 개방")이지만 예외가 자유
문장이다 — "예약한 야영객만 머문다 — 18시 이후 도착은 노쇼 처리라...". 이걸 참/거짓으로
접으면 **그 문장이 담은 조건이 사라진다.** 그래서 값은 원문을 싣고, 거르기용으로만
파생 축(`needs_climb`·`always_open`)을 따로 둔다. 거르는 것과 답하는 것은 다르다.

파생 축은 **거르기에만** 쓴다
--------------------------------------------------------------------------
"등산 없는 곳"을 물으면 `needs_climb` 로 후보를 좁히되, 답에는 `walk_type` 원문과
실측 도보 시간(`walk_minutes`)을 실어 보낸다. 사용자가 읽는 것은 파생 축이 아니라
원문이다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache

from server import path
from server.core import trail

#: `walk_type` 이 이 말로 시작하면 오르막 산행이 필요한 곳으로 본다.
#: 63곳 중 "평지" 45 · "등반" 14 · 나머지 3곳은 "평지 + 계단" 류의 서술이라
#: 앞부분만 보면 갈린다.
_CLIMB_PREFIX = "등반"

#: `night_access` 가 이 값이면 야간에 언제든 들어갈 수 있다. 63곳 중 55곳이 여기고,
#: 나머지 8곳은 전부 조건이 붙은 자유 문장이라 "확인 필요"로 남긴다.
_ALWAYS_OPEN = "상시 개방"

#: 도보 구간의 갈래. 지도에서 색으로 가르는 축이라 **밟는 것** 순으로 본다 —
#: 같은 흙길이라도 계단이 놓였으면 밟는 것은 계단이다.
WALK_STAIR = "계단"
WALK_ROCK = "암반"
WALK_STONE = "돌길"
WALK_PAVED = "포장"
WALK_DIRT = "흙길"
WALK_UNKNOWN = "모름"

#: 노면 낱말 → 갈래. `core.trail.SURFACE` 의 값을 그대로 받는다.
_SURFACE_KIND = {
    "포장": WALK_PAVED,
    "거의 흙": WALK_DIRT,
    "비교적 흙": WALK_DIRT,
    "비교적 돌": WALK_STONE,
    "거의 돌": WALK_STONE,
}


@dataclass(frozen=True)
class WalkSegment:
    """도보 경로의 한 구간 — 점렬과 그 위를 무엇으로 걷는가.

    경로 전체를 한 색으로 그으면 "20분 걷는다"까지만 보이고 **어디서 계단이 시작되는지**
    가 안 보인다. 밤에 초행으로 오르는 사람에게는 그게 준비를 가르는 정보다.
    """

    points: tuple[tuple[float, float], ...]
    kind: str
    surface: str
    rock: str


def _segment_kind(surface: str, rock: str) -> str:
    """무엇을 밟는가. 계단이 놓였으면 노면보다 계단이 먼저다."""
    if trail.is_stairs(rock):
        return WALK_STAIR
    if rock == "약간의 암반":
        return WALK_ROCK
    return _SURFACE_KIND.get(surface or "", WALK_UNKNOWN)


@dataclass(frozen=True)
class Spot:
    """검증된 관측지 한 곳. 값은 원문 그대로다(없으면 None·빈 목록)."""

    name: str
    name_en: str | None
    lat: float
    lon: float
    region: str
    kind: str
    why: str
    notes: str
    access: str | None
    walk_type: str | None
    #: 주차 지점에서 관측 지점까지 **편도** 도보 시간(분). 경로가 여럿이면
    #: 가장 오래 걸리는 것 — 아래 세 항목과 함께 '가장 힘든 경로 기준'이다.
    walk_minutes: float | None
    walk_climb_m: float | None
    walk_terrain: str | None
    #: 대표 경로에 깔린 목재계단 길이(m). 0 이면 계단이 없다는 **확인된 사실**이고,
    #: None 이면 재지 않았다는 뜻이다 — 둘을 같게 보이면 안 된다.
    walk_stair_m: float | None
    #: 국립공원공단 탐방로 등급(매우쉬움~매우어려움). 네 항목 중 하나라도 비면
    #: None — 짐작으로 채우면 밤에 초행으로 걷는 사람이 그 짐작을 읽는다.
    trail_grade: str | None
    #: 주차 지점 → 관측 지점 도보 경로를 **구간별로** 쪼갠 것. 지도가 갈래마다 다른
    #: 색으로 긋는다. 값(분·고도차)과 달리 이건 모양이라 요약할 수 없다.
    walk_segments: tuple[WalkSegment, ...]
    elevation_m: float | None
    slope_deg: float | None
    parking: list[dict]
    toilet: list[dict]
    pets: str | None
    night_access: str | None
    fee: str | None
    hours: str | None
    cautions: list[str]
    campsite: bool
    store: bool
    sources: list[str]

    # --- 거르기용 파생 축 (답에는 원문을 쓴다) ---

    @property
    def needs_climb(self) -> bool:
        """오르막 산행이 필요한가. "등산 없는 곳" 질의를 거르는 데만 쓴다."""
        return (self.walk_type or "").startswith(_CLIMB_PREFIX)

    @property
    def always_open(self) -> bool:
        """야간에 조건 없이 들어갈 수 있나. 아니면 원문에 조건이 적혀 있다."""
        return self.night_access == _ALWAYS_OPEN

    @property
    def has_parking(self) -> bool:
        return bool(self.parking)

    @property
    def has_toilet(self) -> bool:
        return bool(self.toilet)

    def coord(self) -> tuple[float, float]:
        return (self.lat, self.lon)

    def drive_target(self) -> tuple[float, float]:
        """차로 향하는 지점. 주차장이 있으면 그 좌표다.

        관측 지점 자체는 오름 정상일 수 있어 도로에서 멀다. 주행시간은 **차를 세우는
        곳**까지 재야 맞다 — 남은 구간은 `walk_minutes` 가 따로 답한다.
        """
        if self.parking:
            p = self.parking[0]
            if p.get("lat") is not None and p.get("lon") is not None:
                return (float(p["lat"]), float(p["lon"]))
        return self.coord()


def _walk_worst(routes: list[dict] | None) -> dict:
    """도보 축을 **가장 힘든 경로 기준**으로 모은다.

    경로마다 최댓값을 따로 고른다 — 한 경로만 대표로 뽑으면 실제로 있는 위험이
    사라진다. 따라비오름이 그 예다: 경로가 둘인데 시간이 긴 쪽은 계단 0m·보통이고
    짧은 쪽이 계단 260m·어려움이다. 시간으로 대표를 고르면 260m 계단을 안 말하게 된다.

    밤에 초행으로 걷는 사람이 읽는 값이라, 어느 길로 가든 **각오해야 하는 쪽**을
    말한다. 쉬운 길도 있다는 사실은 경로 수(`walk_paths`)로 드러난다.

    Returns:
        {"minutes", "climb_m", "terrain", "stair_m", "grade"} — 못 재면 그 항목은 None.
    """
    out: dict = {
        "minutes": None, "climb_m": None, "terrain": None,
        "stair_m": None, "grade": None,
    }
    if not routes:
        return out

    def _max(key: str):
        vals = [r[key] for r in routes if r.get(key) is not None]
        return max(vals) if vals else None

    out["minutes"] = _max("minutes")
    out["climb_m"] = _max("climb_m")
    out["stair_m"] = _max("stair_m")

    # 지형은 값이 아니라 이름이라 최댓값이 없다. 가장 오래 걸리는 경로의 것을 쓴다.
    longest = max(routes, key=lambda r: r.get("minutes") or 0.0)
    out["terrain"] = longest.get("terrain")

    # 등급은 점수로 견준다(문자열 비교는 순서가 없다). 가장 힘든 것을 남긴다.
    hardest = None
    for route in routes:
        scored = _grade_of(route)
        if scored is not None and (hardest is None or scored[0] > hardest[0]):
            hardest = scored
    out["grade"] = hardest[1] if hardest else None
    return out


def _grade_of(route: dict) -> tuple[float, str] | None:
    """경로 하나의 탐방로 (점수, 등급). 항목이 하나라도 비면 None.

    등급 계산은 `core.trail`(국립공원공단 기준)이 한다 — 힘든 정도를 우리가 만든
    눈금으로 말하면 근거가 없다. 여기서는 경로 데이터를 그 함수의 인자로 옮기기만
    한다. `slope_deg` 는 각도라 배점표가 쓰는 백분율로 바꾼다.
    """
    surface, rock = trail.worst(route.get("segments") or [])
    slope_deg, distance_m = route.get("slope_deg"), route.get("over_m")
    if slope_deg is None or distance_m is None:
        return None
    result = trail.assess(
        slope_percent=math.tan(math.radians(float(slope_deg))) * 100.0,
        distance_m=float(distance_m),
        terrain=route.get("terrain") or "",
        surface=surface,
        rock=rock,
    )
    return None if result is None else (result.score, result.grade)


def _segments_of(routes: list[dict] | None) -> tuple[WalkSegment, ...]:
    """도보 경로들을 구간 단위로 편다. 점이 둘 미만인 조각은 선이 안 되므로 버린다.

    `segments` 의 `from`·`to` 는 그 경로 `points` 의 인덱스다. 구간 정보가 아예 없는
    경로는 통째로 한 조각(갈래 '모름')으로 둔다 — 색을 못 정한다고 길을 안 그리면
    "여기는 걸어갈 데가 없다"로 읽힌다.
    """
    out: list[WalkSegment] = []
    for route in routes or []:
        pts = [
            (float(p[0]), float(p[1]))
            for p in (route.get("points") or [])
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
        if len(pts) < 2:
            continue

        parts = route.get("segments") or []
        if not parts:
            out.append(
                WalkSegment(tuple(pts), WALK_UNKNOWN, surface="", rock="")
            )
            continue

        for part in parts:
            lo, hi = part.get("from"), part.get("to")
            if lo is None or hi is None:
                continue
            # 인덱스가 경로 밖으로 나가는 자료가 있어 잘라 쓴다.
            lo, hi = max(0, int(lo)), min(len(pts) - 1, int(hi))
            if hi - lo < 1:
                continue
            surface, rock = part.get("surface") or "", part.get("rock") or ""
            out.append(
                WalkSegment(
                    points=tuple(pts[lo : hi + 1]),
                    kind=_segment_kind(surface, rock),
                    surface=surface,
                    rock=rock,
                )
            )
    return tuple(out)


def _to_spot(raw: dict) -> Spot:
    walk = _walk_worst(raw.get("walk_routes"))
    return Spot(
        name=raw["name_ko"],
        name_en=raw.get("name_en"),
        lat=float(raw["lat"]),
        lon=float(raw["lon"]),
        region=raw.get("region", ""),
        kind=raw.get("type", ""),
        why=raw.get("why", ""),
        notes=raw.get("notes", ""),
        access=raw.get("access"),
        walk_type=raw.get("walk_type"),
        walk_minutes=walk["minutes"],
        walk_climb_m=walk["climb_m"],
        walk_terrain=walk["terrain"],
        walk_stair_m=walk["stair_m"],
        trail_grade=walk["grade"],
        walk_segments=_segments_of(raw.get("walk_routes")),
        elevation_m=raw.get("elevation_m"),
        slope_deg=raw.get("slope_deg"),
        parking=list(raw.get("parking") or []),
        toilet=list(raw.get("toilet") or []),
        pets=raw.get("pets"),
        night_access=raw.get("night_access"),
        fee=raw.get("fee"),
        hours=raw.get("hours"),
        cautions=list(raw.get("cautions") or []),
        campsite=bool(raw.get("campsite")),
        store=bool(raw.get("store")),
        sources=list(raw.get("sources") or []),
    )


@lru_cache(maxsize=1)
def _load() -> tuple[tuple[Spot, ...], str]:
    """(관측지들, 데이터 귀속). 파일은 한 번만 읽는다."""
    doc = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    spots = tuple(_to_spot(r) for r in doc["spots"])
    meta = doc.get("meta", {})
    source = str(meta.get("source") or "관측지: 자체 구축(로드뷰·위성 검증)")
    return spots, source


def all_spots() -> tuple[Spot, ...]:
    """검증된 관측지 전부."""
    return _load()[0]


def source() -> str:
    """attribution 최상위에 실을 데이터 귀속."""
    return _load()[1]


REGIONS: tuple[str, ...] = ("동", "서", "남", "북", "중산간")


def _normalize(text: str) -> str:
    """이름 비교용 정규화 — 공백·가운뎃점을 지운다.

    "새별 오름"·"새별오름"·"1100 고지"를 같은 것으로 본다. 사용자가 띄어쓰기를
    맞춰 줄 이유가 없다.
    """
    return "".join(text.split()).replace("·", "").replace("-", "").lower()


def find(query: str) -> Spot | None:
    """이름으로 관측지 하나를 찾는다. 못 찾으면 None.

    완전 일치 → 부분 일치 순으로 본다. 부분 일치가 여럿이면 **가장 짧은 이름**을
    고른다 — "오름"으로 물었을 때 이름이 긴 쪽이 더 특수한 곳이기 때문이다.
    """
    if not query or not query.strip():
        return None
    q = _normalize(query)
    spots = all_spots()

    for s in spots:
        if _normalize(s.name) == q or (s.name_en and _normalize(s.name_en) == q):
            return s

    hits = [s for s in spots if q in _normalize(s.name) or _normalize(s.name) in q]
    if not hits:
        hits = [s for s in spots if s.name_en and q in _normalize(s.name_en)]
    if not hits:
        return None
    return min(hits, key=lambda s: len(s.name))


def filter_spots(
    region: str | None = None,
    no_climb: bool = False,
    max_walk_minutes: float | None = None,
    parking_required: bool = False,
    pets: bool = False,
    always_open: bool = False,
) -> list[Spot]:
    """조건으로 후보를 좁힌다. 주행시간은 여기서 보지 않는다(도로 그래프 소관).

    조건을 안 주면 전부 돌려준다 — 거르는 것은 호출자의 질의에 있는 것만이다.
    """
    out = []
    for s in all_spots():
        if region and s.region != region:
            continue
        if no_climb and s.needs_climb:
            continue
        if max_walk_minutes is not None:
            # 도보 시간을 모르는 곳은 남긴다. 모르는 것과 오래 걸리는 것은 다르다.
            if s.walk_minutes is not None and s.walk_minutes > max_walk_minutes:
                continue
        if parking_required and not s.has_parking:
            continue
        if pets and "가능" not in (s.pets or ""):
            continue
        if always_open and not s.always_open:
            continue
        out.append(s)
    return out
