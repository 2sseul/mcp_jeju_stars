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
from dataclasses import dataclass
from functools import lru_cache

from server import path

#: `walk_type` 이 이 말로 시작하면 오르막 산행이 필요한 곳으로 본다.
#: 63곳 중 "평지" 45 · "등반" 14 · 나머지 3곳은 "평지 + 계단" 류의 서술이라
#: 앞부분만 보면 갈린다.
_CLIMB_PREFIX = "등반"

#: `night_access` 가 이 값이면 야간에 언제든 들어갈 수 있다. 63곳 중 55곳이 여기고,
#: 나머지 8곳은 전부 조건이 붙은 자유 문장이라 "확인 필요"로 남긴다.
_ALWAYS_OPEN = "상시 개방"


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
    #: 주차 지점에서 관측 지점까지 **편도** 도보 시간(분). 실측 경로에서 잰 값.
    walk_minutes: float | None
    walk_climb_m: float | None
    walk_terrain: str | None
    #: 주차 지점 → 관측 지점 도보 경로의 점렬들. 지도에 선으로 그린다.
    #: 값(분·고도차)과 달리 이건 **모양**이라, 요약할 수 없어 원본을 그대로 든다.
    walk_paths: tuple[tuple[tuple[float, float], ...], ...]
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


def _walk_of(
    routes: list[dict] | None,
) -> tuple[float | None, float | None, str | None]:
    """도보 경로들 중 **가장 긴 것**을 대표로 삼는다. (분, 오름 m, 지형).

    경로가 여럿이면 짧은 쪽을 고르고 싶지만, 그러면 "10분이면 된다"고 답해 놓고
    실제로는 그 경로가 폐쇄·야간 통제일 수 있다. 보수적으로 긴 쪽을 말한다.
    """
    if not routes:
        return (None, None, None)
    top = max(routes, key=lambda r: r.get("minutes") or 0.0)
    return (top.get("minutes"), top.get("climb_m"), top.get("terrain"))


def _paths_of(routes: list[dict] | None) -> tuple[tuple[tuple[float, float], ...], ...]:
    """도보 경로들의 점렬. 점이 둘 미만인 경로는 선이 안 되므로 버린다."""
    out = []
    for route in routes or []:
        pts = tuple(
            (float(p[0]), float(p[1]))
            for p in (route.get("points") or [])
            if isinstance(p, (list, tuple)) and len(p) >= 2
        )
        if len(pts) > 1:
            out.append(pts)
    return tuple(out)


def _to_spot(raw: dict) -> Spot:
    minutes, climb, terrain = _walk_of(raw.get("walk_routes"))
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
        walk_minutes=minutes,
        walk_climb_m=climb,
        walk_terrain=terrain,
        walk_paths=_paths_of(raw.get("walk_routes")),
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
