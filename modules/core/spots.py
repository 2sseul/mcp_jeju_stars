"""관측지 목록 — 사람이 검증해 둔 62곳 (순수 함수 + 정적 JSON 조회).

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
import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise

from modules import path
from modules.core import elevation, trail

#: `walk_type` 이 이 말로 시작하면 오르막 산행이 필요한 곳으로 본다.
#: 62곳 중 "평지" 45 · "등반" 14 · 나머지 3곳은 "평지 + 계단" 류의 서술이라
#: 앞부분만 보면 갈린다.
_CLIMB_PREFIX = "등반"

#: `night_access` 가 이 값이면 야간에 언제든 들어갈 수 있다. 62곳 중 55곳이 여기고,
#: 나머지 8곳은 전부 조건이 붙은 자유 문장이라 "확인 필요"로 남긴다.
_ALWAYS_OPEN = "상시 개방"

#: 반려동물 동반 가부. `pets` 원문이 자유 문장이라 파생 축으로 접어 둔다.
#:
#: **부분 문자열로 "가능"을 찾으면 안 된다** — "반려견 동반 불가능" 안에 "가능"이
#: 들어 있어, `"가능" in text` 는 동반 불가인 16곳을 전부 통과시킨다(실제로 그랬다:
#: "강아지 데리고 갈 수 있는 곳"에 1100고지 휴게소가 추천됐다). 반대로 "반려동물
#: 동행시 목줄 착용 필수" 3곳은 "가능"이 없다는 이유로 빠졌다.
#: 그래서 **부정을 먼저 보고**, 그 다음에 긍정을 본다. "확인불가"도 "불가"를 품고
#: 있으므로 부정보다 앞에서 걸러 낸다.
_PETS_UNKNOWN = ("확인불가", "확인 불가", "확인되지")
_PETS_NO = ("불가", "금지", "불허", "안 되", "안되", "안 돼", "안돼", "출입 제한")
_PETS_YES = ("가능", "허용", "동행시", "동반시")

#: 한 문장 안에 허용과 불가가 같이 오는 경우가 있어 **절 단위로** 가른다.
#: 예: "한라산은 애견 동반이 안 되지만 1100고지에서 관측은 가능하며, 탐방로는 불가능"
_PETS_CLAUSE = re.compile(r"[,·]|지만|으나|이나(?=\s)|하나(?=\s)|며\s|\(|\)")


def pets_allowed(text: str | None) -> bool | None:
    """반려동물 동반 가부. True 허용 · False 불가 · None 모름.

    **부분 문자열로 "가능"을 찾으면 안 된다** — "반려견 동반 불가능" 안에 "가능"이
    들어 있어, `"가능" in text` 는 동반 불가인 16곳을 전부 통과시켰다(실제로 그랬다:
    "강아지 데리고 갈 수 있는 곳"에 1100고지 휴게소가 추천됐다).

    그렇다고 부정을 무조건 앞세울 수도 없다. 원문에 허용과 불가가 **같이** 오는 곳이
    있기 때문이다 — "한라산은 애견 동반이 안 되지만 1100고지에서 관측은 가능하며,
    탐방로는 불가능". 통째로 부정으로 접으면 관측이 되는 곳을 못 내놓는다.

    그래서 **절 단위로 가르고, 허용하는 절이 하나라도 있으면 허용으로 본다.** 대신
    답에는 언제나 `pets` 원문을 함께 싣는다(`tools._recommend_reasons` 의 `show_pets`,
    `spot_details` 의 "반려동물:" 줄) — "탐방로는 불가능" 같은 단서를 사람이 읽고
    판단할 수 있어야 하기 때문이다. 거르는 것과 답하는 것은 다르다(모듈 설명 참조).
    """
    t = (text or "").strip()
    if not t:
        return None
    if any(k in t for k in _PETS_UNKNOWN):
        return None

    saw_no = False
    for clause in _PETS_CLAUSE.split(t):
        c = clause.strip()
        if not c:
            continue
        # 절 안에서는 부정이 앞선다 — "동반 불가능" 의 "가능"에 걸리지 않게.
        if any(k in c for k in _PETS_NO):
            saw_no = True
        elif any(k in c for k in _PETS_YES):
            return True
    return False if saw_no else None


#: "주차하고 바로" 로 치는 도보 시간(분). 아래 값 미만이면 걸어간다고 하지 않는다.
#:
#: 이 상수가 없어서 계약이 깨져 있었다. 도구 설명은 `max_walk_minutes=0` 을 "주차하고
#: 바로 보는 곳"이라고 광고했는데, 필터는 `walk_minutes > 0` 을 전부 잘라냈다. 62곳
#: 중 도보 0분인 곳은 **하나도 없다**(최소 0.10분). 그래서 0 을 주면 도보 시간을
#: **모르는 2곳**(관음사 야영장·화순방파제)만 남았다 — 물어본 것과 정반대다.
#: `tools._walk_phrase` 는 이미 1분 미만을 "주차 후 바로 관측 가능해요"로 말하고
#: 있었으므로, 거르는 쪽을 말하는 쪽에 맞춘다.
IMMEDIATE_WALK_MIN = 1.0

#: 방위를 재는 기준점 — 제주 행정구역 범위(`tools._LAT_MIN` 등)의 한가운데.
#: 한라산 정상을 쓰지 않는 것은, 정상이 섬 중심에서 남쪽으로 치우쳐 있어 북쪽
#: 관측지가 실제보다 더 북쪽으로 읽히기 때문이다.
_CENTER_LAT = (33.1908 + 33.5639) / 2
_CENTER_LON = (126.1452 + 126.9723) / 2

#: 8방위. 데이터의 `region` 은 동·서·남·북·중산간 다섯뿐이라 "남"이 실제로는 남서인
#: 곳이 많다 — 62곳 중 24곳이 그렇다(송악산·용머리해안·알뜨르비행장 등이 '남'인데
#: 남서다). 어디쯤인지를 말할 때는 좌표에서 잰 이 값을 쓴다.
_BEARINGS = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")

#: 도보 시간에 얹는 여유(분/km). Márquez-Pérez(2017)가 밝힌 오차의 **위쪽 끝**을
#: 그대로 쓴다(`elevation.WALK_ERROR_MIN_PER_KM[1]`). 중앙값을 그대로 내보내면
#: 절반은 늦는다 — 밤에 초행으로 걷는 사람에게는 늦는 쪽이 위험하다.
#: 없는 계수를 지어내지 않고, 논문이 스스로 밝힌 폭을 쓴다.
WALK_MARGIN_MIN_PER_KM: float = elevation.WALK_ERROR_MIN_PER_KM[1]

#: 도보 구간의 갈래. 지도에서 색으로 가르는 축이라 **밟는 것** 순으로 본다 —
#: 같은 흙길이라도 계단이 놓였으면 밟는 것은 계단이다.
WALK_STAIR = "계단"
WALK_ROCK = "암반"
WALK_STONE = "돌길"
WALK_PAVED = "포장길"
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

    길이는 원본의 `over_m` 이 아니라 **그려지는 점렬에서 직접 잰다**. 지도에 보이는
    선과 팝업의 숫자가 어긋나면 어느 쪽을 믿어야 할지 알 수 없다.
    """

    points: tuple[tuple[float, float], ...]
    kind: str
    surface: str
    rock: str
    #: 이 구간의 길이(m). 점렬을 따라 잰 값.
    metres: float
    #: 구간 평균 경사(도) — 양 끝 고도차를 걸은 거리로 나눈 값. 안 잰 구간은 None.
    slope_deg: float | None
    #: 구간 안 가장 가파른 창의 경사(도). 평균이 상쇄로 가리는 비탈을 드러낸다.
    slope_max_deg: float | None
    #: 그 구간에 대해 사람이 적어 둔 말("좌측의 벤치에서 쉬어갈 수 있음", "야자매트").
    #: 배점표 낱말로는 담기지 않는, 그 자리에 가 본 사람만 아는 것이 여기 들어간다.
    note: str
    #: 같은 경로에서 나온 조각끼리 같은 값. 조각은 원래 한 줄이던 길을 노면별로 자른
    #: 것이라, **다시 이어 붙여야 하는 쪽**이 있다 — 진행 방향 화살표가 그렇다. 조각마다
    #: 따로 얹으면 1100고지의 10m 계단 같은 짧은 조각에는 하나도 안 들어간다.
    #: 한 관측지에 오르는 길이 여럿이면(다랑쉬는 둘) 그 길들도 서로 다른 값이다.
    route: int = 0
    #: 그 자리에 있는 것의 짧은 이름("벤치"·"평상"·"사슴동상"). `note` 의 문장을 지도
    #: 위에 그대로 얹으면 라벨이 길을 덮으므로, 화면에 찍을 말은 사람이 따로 적는다.
    #: 코드가 문장을 잘라 만들지 않는다 — "…의자가 있" 같은 것이 나온다.
    landmark: str = ""


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
    #: 가장 오래 걸리는 것 — 아래 항목들과 함께 '가장 힘든 경로 기준'이다.
    #: 이건 논문 함수가 낸 **중앙값**이라 절반은 이보다 늦는다.
    walk_minutes: float | None
    #: 위 값에 논문의 오차 폭(2.3분/km)을 얹은 **보수적** 시간. 계획은 이 값으로
    #: 세운다 — 밤에 초행으로 걷는 사람에게는 늦는 쪽이 위험하다.
    walk_minutes_safe: float | None
    walk_climb_m: float | None
    walk_terrain: str | None
    #: 대표 경로에 깔린 목재계단 길이(m). 0 이면 계단이 없다는 **확인된 사실**이고,
    #: None 이면 재지 않았다는 뜻이다 — 둘을 같게 보이면 안 된다.
    walk_stair_m: float | None
    #: 좌표에서 잰 8방위(북·북동·동·남동·남·남서·서·북서). 데이터의 `region` 이
    #: 네 방위뿐이라 "남"이 실제로는 남서인 곳이 많아, 어디쯤인지는 이 값으로 말한다.
    bearing: str
    #: 국립공원공단 탐방로 등급(매우쉬움~매우어려움). 네 항목 중 하나라도 비면
    #: None — 짐작으로 채우면 밤에 초행으로 걷는 사람이 그 짐작을 읽는다.
    trail_grade: str | None
    #: 등급이 없는 이유가 **경로가 표고 격자로 잴 수 없을 만큼 짧아서**인가.
    #: 이게 참이면 등급이 없어도 걱정할 일이 아니다 — 차에서 내려 바로다.
    #: 거짓인데 등급도 없으면 그건 아직 확인하지 않은 것이라, 둘을 갈라야 한다.
    walk_too_short: bool
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
        "minutes": None, "minutes_safe": None, "climb_m": None,
        "terrain": None, "stair_m": None, "grade": None, "too_short": False,
    }
    if not routes:
        return out

    def _max(key: str):
        vals = [r[key] for r in routes if r.get(key) is not None]
        return max(vals) if vals else None

    out["minutes"] = _max("minutes")
    out["climb_m"] = _max("climb_m")
    out["stair_m"] = _max("stair_m")

    # 보수적 시간 — 가장 오래 걸리는 경로의 시간에 그 경로 길이만큼 여유를 얹는다.
    longest_by_time = max(routes, key=lambda r: r.get("minutes") or 0.0)
    base = longest_by_time.get("minutes")
    over_m = longest_by_time.get("over_m")
    if base is not None:
        margin = 0.0
        if over_m is not None:
            margin = WALK_MARGIN_MIN_PER_KM * float(over_m) / 1000.0
        out["minutes_safe"] = round(float(base) + margin, 1)

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

    # 등급을 못 낸 이유가 "짧아서"인지 가른다. 경사·길이는 표고 격자가 두 칸보다
    # 짧으면 못 재는데(`elevation.MIN_M`, 약 62m), 그건 확인이 덜 된 것이 아니라
    # **걸을 것이 없다**는 뜻이다. 62곳 중 19곳이 이 경우이고 전부 1분 미만·평지다.
    if out["grade"] is None:
        out["too_short"] = all(
            r.get("slope_deg") is None or r.get("over_m") is None for r in routes
        )
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


_EARTH_M = 6_371_000.0


def _path_metres(points: tuple[tuple[float, float], ...]) -> float:
    """점렬을 따라 잰 길이(m)."""
    total = 0.0
    for (a_lat, a_lon), (b_lat, b_lon) in pairwise(points):
        p1, p2 = math.radians(a_lat), math.radians(b_lat)
        dp = p2 - p1
        dl = math.radians(b_lon - a_lon)
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * _EARTH_M * math.asin(math.sqrt(h))
    return total


def _segments_of(routes: list[dict] | None) -> tuple[WalkSegment, ...]:
    """도보 경로들을 구간 단위로 편다. 점이 둘 미만인 조각은 선이 안 되므로 버린다.

    `segments` 의 `from`·`to` 는 그 경로 `points` 의 인덱스다. 구간 정보가 아예 없는
    경로는 통째로 한 조각(갈래 '모름')으로 둔다 — 색을 못 정한다고 길을 안 그리면
    "여기는 걸어갈 데가 없다"로 읽힌다.
    """
    out: list[WalkSegment] = []
    for rid, route in enumerate(routes or []):
        pts = [
            (float(p[0]), float(p[1]))
            for p in (route.get("points") or [])
            if isinstance(p, (list, tuple)) and len(p) >= 2
        ]
        if len(pts) < 2:
            continue

        parts = route.get("segments") or []
        if not parts:
            whole = tuple(pts)
            out.append(WalkSegment(
                points=whole, kind=WALK_UNKNOWN, surface="", rock="",
                metres=_path_metres(whole), slope_deg=None, slope_max_deg=None,
                note="", route=rid,
            ))
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
            piece = tuple(pts[lo : hi + 1])
            out.append(
                WalkSegment(
                    points=piece,
                    kind=_segment_kind(surface, rock),
                    surface=surface,
                    rock=rock,
                    metres=_path_metres(piece),
                    slope_deg=part.get("slope_deg"),
                    slope_max_deg=part.get("slope_max_deg"),
                    note=str(part.get("note") or ""),
                    route=rid,
                    landmark=str(part.get("landmark") or ""),
                )
            )
    return tuple(out)


def _bearing_of(lat: float, lon: float) -> str:
    """섬 한가운데에서 본 8방위. 북이 0도이고 시계방향으로 잰다."""
    dy = lat - _CENTER_LAT
    dx = (lon - _CENTER_LON) * math.cos(math.radians(_CENTER_LAT))
    angle = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    return _BEARINGS[int((angle + 22.5) % 360.0 // 45)]


def _to_spot(raw: dict) -> Spot:
    walk = _walk_worst(raw.get("walk_routes"))
    lat, lon = float(raw["lat"]), float(raw["lon"])
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
        bearing=_bearing_of(lat, lon),
        walk_minutes=walk["minutes"],
        walk_minutes_safe=walk["minutes_safe"],
        walk_climb_m=walk["climb_m"],
        walk_terrain=walk["terrain"],
        walk_stair_m=walk["stair_m"],
        trail_grade=walk["grade"],
        walk_too_short=bool(walk["too_short"]),
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

#: 장소 유형 묶음 — 데이터의 `type` 을 묻는 말에 맞춰 추린 것.
#:
#: 원본 값은 "오름"·"해안/섬"·"평야/역사터"처럼 스물한 가지로 갈라져 있어 그대로
#: 도구 인자로 내보내면 부르는 쪽이 고를 수 없다. 사람은 "오름 추천해줘"라고 묻지
#: "해안/평지"라고 묻지 않는다.
#:
#: 대조는 **슬래시로 끊은 조각의 완전 일치**다. 부분 문자열로 보면 "관측소/천문공원"이
#: 공원에 딸려 들어간다. 한 곳이 두 묶음에 들어가는 것은 막지 않는다 — "오름/습지"는
#: 오름이기도 하다.
PLACE_TYPES: dict[str, frozenset[str]] = {
    "오름": frozenset({"오름"}),
    "해안": frozenset({"해안", "해안도로", "섬", "포구"}),
    "숲/계곡": frozenset({"숲", "계곡"}),
    "공원/야영장": frozenset({"공원", "야영장"}),
    "고지/전망": frozenset({"고지", "전망"}),
    "관측소": frozenset({"관측소", "천문공원"}),
    "목장/초지": frozenset({"목장", "초지"}),
    "주차장": frozenset({"주차장"}),
    "평지": frozenset({"평지", "평야", "역사터", "저수지"}),
}


def is_kind(spot: "Spot", place_type: str) -> bool:
    """이 관측지가 그 유형 묶음에 드는가."""
    tokens = PLACE_TYPES.get(place_type)
    if tokens is None:
        return False
    return any(part.strip() in tokens for part in spot.kind.split("/"))


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
    place_type: str | None = None,
    no_climb: bool = False,
    max_walk_minutes: float | None = None,
    parking_required: bool = False,
    pets: bool = False,
    toilet_required: bool = False,
    campsite: bool = False,
    always_open: bool = False,
    name_contains: str | None = None,
) -> list[Spot]:
    """조건으로 후보를 좁힌다. 주행시간은 여기서 보지 않는다(도로 그래프 소관).

    조건을 안 주면 전부 돌려준다 — 거르는 것은 호출자의 질의에 있는 것만이다.
    """
    out = []
    for s in all_spots():
        if region and s.region != region:
            continue
        if place_type and not is_kind(s, place_type):
            continue
        if no_climb and s.needs_climb:
            continue
        if max_walk_minutes is not None:
            # 0(또는 1분 미만)은 "주차하고 바로"라는 뜻이다. 실측값이 0인 곳은 없으므로
            # 글자 그대로 받으면 아무 곳도 남지 않는다 — 말하는 쪽과 같은 문턱을 쓴다.
            limit = max(max_walk_minutes, IMMEDIATE_WALK_MIN)
            # 도보 시간을 **모르는** 곳은 여기서만 거른다. 일반적으로는 모르는 것과 오래
            # 걸리는 것이 다르지만, 질문 자체가 "얼마나 걷나"일 때 모르는 곳은 답이 아니다
            # (반려동물 조건과 같은 판단).
            if s.walk_minutes is None or s.walk_minutes > limit:
                continue
        if parking_required and not s.has_parking:
            continue
        # 모름(None)도 거른다 — "데려가도 되는 곳"을 물었는데 확인이 안 된 곳을
        # 내놓으면 답이 아니다. 도보 시간과 반대로 두는 이유는 §위 주석에 있다.
        if pets and pets_allowed(s.pets) is not True:
            continue
        # 화장실은 **확인된 것만** 남긴다. 밤에 몇 시간 머무는 질문이라 "아마 있을
        # 것"으로는 답이 되지 않는다(반려동물과 같은 판단).
        if toilet_required and not s.toilet:
            continue
        if campsite and not s.campsite:
            continue
        if always_open and not s.always_open:
            continue
        if name_contains:
            needle = _normalize(name_contains)
            haystack = _normalize(s.name) + _normalize(s.name_en or "")
            if needle not in haystack:
                continue
        out.append(s)
    return out
