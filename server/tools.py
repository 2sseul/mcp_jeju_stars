"""도구 본체 — 좌표·지명을 받아 고정 스키마 dict 를 돌려주는 **순수 파이썬 함수**.

여기에는 MCP 가 없다. 등록(`@mcp.tool`)과 전송(streamable HTTP)은 `server/app.py`
소관이고, 이 모듈은 "무엇을 판정하는가"만 안다. 갈라 둔 이유는 둘이다:

1. fastmcp v2 의 `@mcp.tool` 은 함수가 아니라 `FunctionTool` 객체를 돌려준다.
   도구 정의와 판정 로직이 한 파일에 있으면 테스트가 판정을 직접 부를 수 없어
   `.fn` 같은 SDK 내부 속성에 묶인다.
2. `core`(순수) · `clients`(네트워크) · `engine`(조립) 과 같은 결 — 전송 계층은
   맨 바깥 한 겹에만 둔다.

도구는 **사용자가 무엇을 묻는가**로 셋이다 (입력 형태가 아니다)
--------------------------------------------------------------------------
    recommend_spots  "어디로 갈까"   — 조건에 맞는 관측지를 골라 준다
    evaluate_place   "여기 별 보여?" — 지목한 장소 하나를 판정한다
    spot_details     "거기 어때?"    — 검증된 관측지의 접근성·편의를 답한다

좌표를 받느냐 지명을 받느냐로 가르지 않는다. 그건 **입력 형태**일 뿐이고 사용자의
질문 목적이 아니다 — `evaluate_place` 하나가 둘 다 받는다(`query` 또는 `lat`·`lon`).

등록된 곳과 아닌 곳
--------------------------------------------------------------------------
`data/jeju_spots.json` 의 63곳은 사람이 로드뷰·위성으로 확인한 자리다. 그 밖의 좌표도
날씨·광공해·천문 조건은 **똑같이** 판정할 수 있지만 주차·야간 출입·도보 난이도는
알 수 없다. 그래서 미등록 장소는 관측 가능 여부만 답하고 **접근성은 확인되지 않았음을
명시한다** — 모르는 것을 아는 척하지 않는다.

"무엇을 묻나"(한 시각 vs 밤 전체)는 여전히 도구가 아니라 **scope 파라미터**다:

    scope="moment"(기본) — 한 시각의 관측 등급(astro→weather→judge). time 사용.
    scope="night"        — 박명 포함 밤 전체를 시간별로 판정해 관측 가능 시간 수·
                           등급 분포·연속 창을 집계(graph.run_tonight). time 무시.

제주 범위 밖·형식 오류는 프롬프트형 에러. 별 개수 축은 아직 numbers 에 없다.
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from server import maps
from server.clients.geocode import geocode
from server.core import astro, darkness, parking, places, routing, spots, toilet
from server.core.mapview import Fact, Item, Marker
from server.engine import graph
from server.schema import Response

KST = ZoneInfo("Asia/Seoul")

# 제주도 공식 행정구역 범위. 밖이면 평가하지 않는다.
# 위도 33°11′27″~33°33′50″N, 경도 126°08′43″~126°58′20″E 를 십진 변환하고,
# 경계점이 포함되도록 최소는 내림·최대는 올림했다.
_LAT_MIN, _LAT_MAX = 33.1908, 33.5639
_LON_MIN, _LON_MAX = 126.1452, 126.9723

_SCOPES = ("moment", "night")

#: 좌표로 물었을 때 이 거리 안이면 등록된 관측지로 본다. 관측지 좌표와 사용자가
#: 찍은 좌표가 정확히 같을 리 없고, 주차장과 관측 지점도 이 정도는 떨어져 있다.
_SAME_SPOT_M = 300.0

#: 추천에서 날씨까지 재 볼 후보 수의 상한. 후보 63곳 전부에 예보를 조회하면 외부
#: 호출이 63번 나간다. 어둡기(정적 데이터, 조회 0회)로 먼저 줄인 뒤 이만큼만 잰다.
_WEATHER_POOL = 8

#: 추천이 한 번에 돌려주는 곳의 기본값·상한.
_LIMIT_DEFAULT = 3
_LIMIT_MAX = 10


def _in_jeju(lat: float, lon: float) -> bool:
    return _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX


def _now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="minutes")


# --- 입력 검증 (모두 프롬프트형 응답으로 환원한다) --------------------------------


def _resolve_when(date: str | None, time: str | None) -> datetime:
    """평가 시각을 KST datetime 으로 만든다.

    - date(YYYY-MM-DD) 생략 → 오늘
    - time(HH:MM, 24시간) 생략 → 22:00
    - date·time 모두 생략 → 현재 시각 그대로
    파싱 실패 시 ValueError.
    """
    now = datetime.now(KST)
    if date is None and time is None:
        return now
    y, m, d = (now.year, now.month, now.day) if date is None else (
        int(x) for x in date.split("-")
    )
    hh, mm = (22, 0) if time is None else (int(x) for x in time.split(":"))
    return datetime(y, m, d, hh, mm, tzinfo=KST)


def _resolve_night_when(date: str | None) -> datetime:
    """밤 집계의 기준 시각. date 가 있으면 그날 저녁(20:00), 없으면 현재.
    어느 쪽이든 night_window 가 '그 밤'을 찾는다. 파싱 실패 시 ValueError.
    """
    now = datetime.now(KST)
    if date is None:
        return now
    y, m, d = (int(x) for x in date.split("-"))
    return datetime(y, m, d, 20, 0, tzinfo=KST)


def _invalid_when(date: str | None, time: str | None) -> dict:
    """date/time 형식 오류에 대한 프롬프트형 응답."""
    return Response(
        verdict="입력 오류",
        reasons=[
            f"날짜/시각 형식을 이해하지 못했습니다 (date={date!r}, time={time!r}). "
            "date 는 YYYY-MM-DD, time 은 24시간제 HH:MM 형식으로 주세요 "
            "(예: date='2026-07-24', time='21:00')."
        ],
        numbers={},
        attribution=[],
        as_of=_now_iso(),
    ).to_dict()


def _out_of_ephemeris(when: datetime) -> dict:
    """천체력 지원 범위 밖 날짜에 대한 프롬프트형 응답.

    박명은 천체력(DE421)으로 계산하는데 그 파일이 덮는 기간이 유한하다. 범위 밖이면
    skyfield 가 예외를 던지므로, 도구 밖으로 새 나가기 전에 고정 스키마로 환원한다.
    """
    return Response(
        verdict="입력 오류",
        reasons=[
            f"{when.date().isoformat()} 는 천체력이 다루는 기간 밖이라 "
            "계산할 수 없어요. "
            f"{astro.EPHEM_START.date().isoformat()} ~ "
            f"{astro.EPHEM_END.date().isoformat()} 사이의 날짜로 다시 시도해 주세요."
        ],
        numbers={},
        attribution=["천체력: JPL DE421 via Skyfield"],
        as_of=_now_iso(),
    ).to_dict()


def _out_of_range(lat: float, lon: float) -> dict:
    """제주 범위 밖 입력에 대한 프롬프트형 응답."""
    return Response(
        verdict="지원 범위 밖",
        reasons=[
            "이 서비스는 제주 지역만 지원합니다 "
            f"(위도 {_LAT_MIN}~{_LAT_MAX}, 경도 {_LON_MIN}~{_LON_MAX}). "
            f"입력한 좌표 ({lat}, {lon})는 범위를 벗어났습니다. "
            "제주 안의 좌표로 다시 시도해 주세요."
        ],
        numbers={},
        attribution=[],
        as_of=_now_iso(),
    ).to_dict()


def _invalid_scope(scope) -> dict:
    """scope 값 오류에 대한 프롬프트형 응답."""
    return Response(
        verdict="입력 오류",
        reasons=[
            f"scope 값을 이해하지 못했습니다 (scope={scope!r}). "
            "'moment'(한 시각) 또는 'night'(밤 전체) 중 하나로 주세요."
        ],
        numbers={},
        attribution=[],
        as_of=_now_iso(),
    ).to_dict()


def _normalize_scope(scope: str | None) -> str | None:
    """scope 를 정규화한다. 알 수 없는 값이면 None."""
    s = (scope or "moment").strip().lower()
    return s if s in _SCOPES else None


def _validate_inputs(date: str | None, time: str | None, scope: str) -> dict | None:
    """좌표와 무관한 입력(scope·날짜·시각)을 검증한다. 문제 없으면 None.

    좌표 경로와 지명 경로가 **같은 판정**을 내리도록 이 하나를 공유한다. 지명 경로는
    이것을 지오코딩보다 먼저 불러, 잘못된 입력에 외부 호출을 낭비하지 않는다.
    """
    s = _normalize_scope(scope)
    if s is None:
        return _invalid_scope(scope)

    try:
        when = _resolve_night_when(date) if s == "night" else _resolve_when(date, time)
    except (ValueError, AttributeError):
        return _invalid_when(date, None if s == "night" else time)

    if not astro.supports(when):
        return _out_of_ephemeris(when)
    return None


# --- 순간(한 시각) 평가 ---------------------------------------------------------


def _evaluate_moment(
    lat: float,
    lon: float,
    date: str | None,
    time: str | None,
    resolved: dict | None = None,
    spot_rows: list[dict] | None = None,
) -> dict:
    """순간(한 시각) 평가 코어 — scope="moment" 경로."""
    try:
        when = _resolve_when(date, time)
    except (ValueError, AttributeError):
        return _invalid_when(date, time)

    if not astro.supports(when):
        return _out_of_ephemeris(when)

    final = graph.run(lat, lon, when)
    reasons = list(final.get("reasons", []))
    nums = final.get("numbers", {})

    # 관측 가능하면 오늘 완전히 어두운 시간대를 덤으로 알려준다.
    window = nums.get("dark_window")
    if final.get("possible") and window:
        reasons.append(
            f"참고로 오늘 완전히 어두운 시간대는 "
            f"{window['start'][11:16]}~{window['end'][11:16]}예요"
        )

    return Response(
        verdict=final.get("verdict") or "불가",
        reasons=reasons,
        numbers=nums,
        attribution=final.get("attribution", []),
        as_of=when.isoformat(timespec="minutes"),
        resolved=resolved,
        spots=spot_rows,
    ).to_dict()


# --- 밤 단위 평가 (scope="night") -----------------------------------------------


def _night_label(when: datetime) -> str:
    """밤 집계 문구의 날짜 라벨. 오늘이면 '오늘 밤', 아니면 'M월 D일 밤'."""
    if when.date() == datetime.now(KST).date():
        return "오늘 밤"
    return f"{when.month}월 {when.day}일 밤"


def _night_verdict(summary: dict | None, window: dict | None, label: str) -> str:
    """밤 집계를 한 줄 결론으로. 3시간 기준으로 가능/불가를 매기지 않는다 —
    관측 가능한 시간 수라는 사실만 문장으로 압축한다(0시간도 '불가'가 아닌 사실)."""
    if window is None:
        return "이 날짜에는 관측할 밤 구간을 찾지 못했어요"
    if summary is None:
        return "밤 기상 정보를 가져오지 못했어요"
    n = summary["observable_hours"]
    if n == 0:
        known = summary["total_hours"] - summary["unknown_hours"]
        if summary["unknown_hours"] and not known:
            return "밤 기상 정보를 가져오지 못했어요"
        return f"{label}은 구름으로 별 볼 만한 시간이 거의 없어요"
    return f"{label} 약 {n}시간 관측 가능"


def _night_reasons(summary: dict | None, window: dict | None, label: str) -> list[str]:
    """밤 집계의 사람이 읽는 근거. 판정이 아니라 시간 수·분포를 그대로 서술한다."""
    if window is None or summary is None:
        return []

    reasons = [
        f"{label} 어두운 구간(박명 포함)은 "
        f"{window['start'][11:16]}~{window['end'][11:16]}예요"
    ]

    for w in summary["windows"]:
        reasons.append(
            f"{w['start'][11:16]}~{w['end'][11:16]} 관측 가능 ({w['hours']}시간)"
        )

    by_grade = summary["by_grade"]
    if by_grade:
        parts = [f"{g} {h}시간" for g, h in by_grade.items()]
        reasons.append("등급별로는 " + ", ".join(parts) + "예요")

    reasons.append(
        f"맑은 시간(총운량 30% 이하) {summary['photometric_hours']}시간, "
        f"다소 맑은 시간(50% 이하) {summary['spectroscopic_hours']}시간"
    )

    if summary["unknown_hours"]:
        unknown = summary["unknown_hours"]
        reasons.append(f"구름 정보를 못 받은 시간이 {unknown}시간 있어요")

    return reasons


def _evaluate_night(
    lat: float,
    lon: float,
    date: str | None,
    resolved: dict | None = None,
    spot_rows: list[dict] | None = None,
) -> dict:
    """밤 집계 코어 — scope="night" 경로."""
    try:
        when = _resolve_night_when(date)
    except (ValueError, AttributeError):
        return _invalid_when(date, None)

    if not astro.supports(when):
        return _out_of_ephemeris(when)

    result = graph.run_tonight(lat, lon, when)
    window = result.get("window")
    summary = result.get("summary")
    label = _night_label(when)

    numbers: dict = {"night_window": window}
    if summary is not None:
        numbers["tonight"] = summary
    # 광공해(정적 장소 속성)는 순간 평가와 같은 필드로 밤 응답에도 노출한다
    # (도구 일관성).
    darkness = result.get("darkness")
    if darkness is not None:
        numbers.update(darkness)

    reasons = _night_reasons(summary, window, label)
    # 어둡기 설명(SQM·야간광·가로등) + 은하수 주의 문구. 관측 가능한 밤일 때만.
    if summary is not None and summary.get("observable_hours"):
        reasons.extend(result.get("darkness_reasons", []))
        if result.get("milky_way_caveat"):
            reasons.append(result["milky_way_caveat"])

    return Response(
        verdict=_night_verdict(summary, window, label),
        reasons=reasons,
        numbers=numbers,
        attribution=result.get("attribution", []),
        as_of=when.isoformat(timespec="minutes"),
        resolved=resolved,
        spots=spot_rows,
    ).to_dict()


def _evaluate(
    lat: float,
    lon: float,
    date: str | None,
    time: str | None,
    scope: str,
    resolved: dict | None = None,
    spot_rows: list[dict] | None = None,
) -> dict:
    """좌표 기준 공통 코어 — scope 로 순간/밤 평가를 라우팅한다."""
    s = _normalize_scope(scope)
    if s is None:
        return _invalid_scope(scope)
    if not _in_jeju(lat, lon):
        return _out_of_range(lat, lon)
    if s == "night":
        return _evaluate_night(lat, lon, date, resolved, spot_rows)
    return _evaluate_moment(lat, lon, date, time, resolved, spot_rows)


# --- 관측지를 응답에 싣는 모양 ----------------------------------------------------


def _spot_row(s: spots.Spot, *, detail: bool = False, route=None) -> dict:
    """관측지 하나를 응답용 dict 로. 값은 원문 그대로 싣는다.

    detail=False 는 추천 목록용 요약, True 는 상세조회용 전체다. 목록에 전부 실으면
    63곳 중 몇 곳만 돌려줘도 응답이 장문이 되어 호출한 LLM 이 요점을 놓친다.
    """
    row: dict = {
        "name": s.name,
        "region": s.region,
        "type": s.kind,
        "lat": s.lat,
        "lon": s.lon,
        "why": s.why,
        "walk_type": s.walk_type,
        "walk_minutes": (
            round(s.walk_minutes, 1) if s.walk_minutes is not None else None
        ),
        "walk_minutes_safe": (
            round(s.walk_minutes_safe, 1) if s.walk_minutes_safe is not None else None
        ),
        "walk_stair_m": s.walk_stair_m,
        "trail_grade": s.trail_grade,
        "bearing": s.bearing,
        "night_access": s.night_access,
        "parking": len(s.parking),
    }
    if route is not None:
        row["drive"] = route.to_dict()
    if not detail:
        return row

    row.update(
        {
            "name_en": s.name_en,
            "notes": s.notes,
            "access": s.access,
            "walk_climb_m": s.walk_climb_m,
            "walk_terrain": s.walk_terrain,
            "elevation_m": s.elevation_m,
            "slope_deg": s.slope_deg,
            "parking_places": s.parking,
            "toilet": s.toilet,
            "pets": s.pets,
            "fee": s.fee,
            "hours": s.hours,
            "cautions": s.cautions,
            "campsite": s.campsite,
            "store": s.store,
            "sources": s.sources,
        }
    )
    return row


def _walk_phrase(s: spots.Spot) -> str:
    """도보 구간을 한 문장으로. 시간은 **보수적** 값으로 말한다.

    논문 함수가 낸 중앙값을 그대로 주면 절반은 그보다 늦는다. 밤에 초행으로 걷는
    사람에게는 늦는 쪽이 위험하므로 오차 폭을 얹은 값을 앞세우고, 잰 값도 함께 적어
    어디서 온 숫자인지 보이게 한다(`spots.WALK_MARGIN_MIN_PER_KM`).
    """
    minutes = s.walk_minutes_safe or s.walk_minutes
    if minutes is None:
        return "도보 시간은 재지 못했어요"
    if minutes < 1:
        return "주차 후 바로 관측 가능해요"
    return (
        f"주차장에서 편도 약 {minutes:.0f}분 걸어요 "
        f"(넉넉히 잡은 값 · 잰 값 {s.walk_minutes:.0f}분)"
    )


def _terrain_phrase(s: spots.Spot) -> str | None:
    """길이 어떤지 한 줄. 걸을 게 없으면 None.

    도보 문장과 갈라 둔다 — 한 문장에 시간·지형·오르막·계단·난이도를 다 넣으면
    괄호가 길어져 어느 것도 안 읽힌다.
    """
    if not s.walk_minutes:
        return None
    bits = []
    if s.trail_grade:
        bits.append(f"난이도 {s.trail_grade}")
    if s.walk_climb_m:
        bits.append(f"오르막 {s.walk_climb_m:.0f}m")
    if s.walk_stair_m:
        bits.append(f"계단 {s.walk_stair_m:.0f}m")
    if s.walk_type:
        bits.append(s.walk_type)
    return "길: " + " · ".join(bits) if bits else None


# --- 지도 (경로·편의시설을 한 장에) ----------------------------------------------
#
# 좌표를 말로 설명하지 않는다(`plan.md` P13). "차로 29분" 다음에 사람이 실제로 묻는
# 것은 "어느 길로, 어디에 세우고, 거기서 얼마나 걷나"이고 그건 선으로 보여야 한다.

#: 등록되지 않은 자리에서 편의시설을 훑는 반경(m). `toilet.WALK_M` 과 같은 값이다 —
#: 차를 두고 다녀올 수 있고 밤에 손전등 하나로 오갈 만한 거리. **"있어요"라고 말하는
#: 기준**이라 넉넉히 잡지 않는다.
NEARBY_M: float = toilet.WALK_M

#: 지도에 **대안으로 찍어 두는** 반경(m). 말로 "있어요"라고 하는 것과 지도에 점을
#: 찍어 두는 것은 다르다 — 점은 "차를 옮기면 여기도 있다"까지 포함해도 오해가 없다.
#: 200m 로는 63곳 중 5곳에만 대안이 뜨고, 500m 면 22곳에 뜬다(1km 는 주차장만 129개라
#: 지도가 점으로 덮인다).
MAP_NEARBY_M: float = 500.0


def _amenity_markers(lat: float, lon: float, radius_m: float) -> list[Marker]:
    """반경 안의 주차장·화장실 마커. 등록 데이터가 없는 자리에서 쓴다.

    주차장은 두 출처를 합친다 — 공영 표준데이터는 오름·해변 주차장을 담지 않아
    카카오 수집분이 없으면 "주차할 데가 없다"고 잘못 답하게 된다. 같은 자리가 양쪽에
    있으면 가까운 쪽 하나만 남긴다(50m 안이면 같은 곳으로 본다).
    """
    out: list[Marker] = []
    seen: list[tuple[float, float]] = []

    def _dup(la: float, lo: float) -> bool:
        return any(_haversine_m(la, lo, a, b) < 50.0 for a, b in seen)

    for hit in parking.near(lat, lon, radius_m):
        seen.append((hit.parking.lat, hit.parking.lon))
        out.append(Marker(
            hit.parking.lat, hit.parking.lon, "parking", hit.parking.name,
            f"{hit.distance_m:.0f}m · {hit.parking.fee} · 공영",
        ))
    for hit in places.near(lat, lon, radius_m, source="parking"):
        if _dup(hit.place.lat, hit.place.lon):
            continue
        seen.append((hit.place.lat, hit.place.lon))
        out.append(Marker(
            hit.place.lat, hit.place.lon, "parking", hit.place.name,
            f"{hit.distance_m:.0f}m · 카카오맵",
        ))
    for hit in toilet.near(lat, lon, radius_m):
        out.append(Marker(
            hit.toilet.lat, hit.toilet.lon, "toilet", hit.toilet.name,
            f"{hit.distance_m:.0f}m · {hit.toilet.hours}"
            + (" · 비상벨" if hit.toilet.bell else ""),
        ))
    return out


def _amenity_reason(markers: list[Marker], radius_m: float) -> str:
    """편의시설 마커를 한 줄로. 없으면 없다고 말한다 — 모르는 것과 다르다."""
    n_park = sum(1 for m in markers if m.kind == "parking")
    n_toilet = sum(1 for m in markers if m.kind == "toilet")
    if not markers:
        return f"반경 {radius_m:.0f}m 안에 등록된 주차장·화장실이 없어요"
    parts = []
    if n_park:
        parts.append(f"주차장 {n_park}곳")
    if n_toilet:
        parts.append(f"화장실 {n_toilet}곳")
    return f"반경 {radius_m:.0f}m 안에 " + " · ".join(parts) + "이 있어요"


#: 각오해야 하는 쪽으로 넘어가는 문턱. 이보다 길면 계단을 붉게 표시한다.
#: 100m 는 아파트 30층 계단에 해당한다 — 밤에 짐을 들고 오르면 준비가 달라진다.
_STAIR_HARD_M: float = 100.0

#: 이 등급부터는 '각오해야 하는 것'으로 본다(국립공원공단 5등급 중 위 둘).
_HARD_GRADES: tuple[str, ...] = ("어려움", "매우어려움")


def _copula(word: str) -> str:
    """이름 뒤에 붙는 서술격 조사 — 받침이 있으면 '이에요', 없으면 '예요'.

    한글 음절은 (초성 19 · 중성 21 · 종성 28) 순서로 배열돼 있어, 코드포인트에서
    종성 자리를 나머지 연산으로 꺼낼 수 있다. 0이면 받침이 없다.
    """
    if not word:
        return "예요"
    last = word[-1]
    if "가" <= last <= "힣":
        return "예요" if (ord(last) - 0xAC00) % 28 == 0 else "이에요"
    # 숫자·영문으로 끝나면 읽는 소리를 알 수 없으므로 조사를 붙이지 않는다.
    return ""


def _toilet_status(spot: spots.Spot) -> tuple[str, str, str]:
    """화장실 상황 — (조각 글자, 결, 문장).

    **없으면 없다고 적는다.** 조용히 빼면 "안 적혀 있으니 있겠지"로 읽히는데, 밤에
    한참 걸어 올라간 뒤에 알게 되는 종류의 정보다.

    없을 때는 **얼마나 먼지**까지 말한다 — "없음"과 "3.3km 밖에 있음"은 계획이 다르다
    (`core.toilet.nearest` 가 반경과 무관하게 가장 가까운 곳을 준다).
    """
    if spot.toilet:
        names = ", ".join(t.get("name", "화장실") for t in spot.toilet)
        return "화장실 있음", "plain", f"화장실: {names}"

    near = toilet.near(spot.lat, spot.lon, MAP_NEARBY_M)
    if near:
        hit = near[0]
        return (
            f"화장실 {hit.distance_m:.0f}m", "plain",
            f"화장실: {hit.toilet.name} ({hit.distance_m:.0f}m · {hit.toilet.hours})",
        )

    nearest = toilet.nearest(spot.lat, spot.lon)
    if nearest is None:
        return "화장실 없음", "warn", "화장실: 확인된 곳이 없어요"
    km = nearest.distance_m / 1000.0
    return (
        f"화장실 {km:.1f}km", "warn",
        f"화장실: 근처에 없어요 — 가장 가까운 곳이 {km:.1f}km 떨어진 "
        f"{nearest.toilet.name}{_copula(nearest.toilet.name)}",
    )


def _spot_facts(spot: spots.Spot, route=None) -> tuple[Fact, ...]:
    """관측지 한 곳을 한눈에 견줄 짧은 조각들로.

    문장이 아니라 조각인 것은 **여러 곳을 나란히 놓고 고르기 위해서**다. 조각마다
    결(색)을 주는 것도 같은 이유다 — 전부 같은 회색이면 줄이 길어질수록 눈이 미끄러져
    아무것도 안 읽힌다. 파랑은 차, 주황은 걷기, 빨강은 각오해야 하는 것, 노랑은
    확인되지 않은 것이다.

    **모르는 것은 빼지 않고 '미상'으로 적는다.** 등급을 못 낸 곳(63곳 중 22곳)을 그냥
    비우면 "쉬운가 보다"로 읽힌다. 계단은 0m 도 적는다 — '없음'은 확인된 사실이다.

    도보는 논문 오차를 얹은 **보수적** 값을 쓴다(`spots.WALK_MARGIN_MIN_PER_KM`).
    중앙값을 그대로 내보내면 절반은 그보다 늦는다.
    """
    facts: list[Fact] = []
    if route is not None:
        facts.append(Fact(f"차 {route.minutes:.0f}분", "drive"))

    minutes = spot.walk_minutes_safe or spot.walk_minutes
    if minutes is not None:
        facts.append(Fact(f"도보 {minutes:.0f}분", "walk"))
    if spot.walk_climb_m:
        facts.append(Fact(f"오르막 {spot.walk_climb_m:.0f}m", "walk"))

    if spot.walk_stair_m is not None:
        if spot.walk_stair_m == 0:
            facts.append(Fact("계단 없음", "plain"))
        else:
            tone = "hard" if spot.walk_stair_m >= _STAIR_HARD_M else "walk"
            facts.append(Fact(f"계단 {spot.walk_stair_m:.0f}m", tone))
    else:
        facts.append(Fact("계단 미상", "warn"))

    if spot.trail_grade:
        tone = "hard" if spot.trail_grade in _HARD_GRADES else "plain"
        facts.append(Fact(f"난이도 {spot.trail_grade}", tone))
    else:
        facts.append(Fact("난이도 미상", "warn"))

    text, tone, _ = _toilet_status(spot)
    facts.append(Fact(text, tone))

    if not spot.always_open:
        facts.append(Fact("야간출입 확인필요", "warn"))
    if not spot.has_parking:
        facts.append(Fact("주차 미확인", "warn"))
    return tuple(facts)


def _where(spot: spots.Spot) -> str:
    """어디쯤인지 한 줄. 좌표에서 잰 8방위를 쓴다.

    데이터의 `region` 을 그대로 쓰면 "남·오름"처럼 붙어 읽히고, 그보다 나쁜 것은
    **틀린다**는 점이다 — 63곳 중 24곳에서 네 방위 표기가 실제 방위와 다르다.
    송악산·용머리해안은 '남'으로 적혀 있지만 남서쪽이다.

    `중산간` 은 방위가 아니라 높이라, 있으면 방위와 함께 적는다.
    """
    where = f"{spot.bearing}쪽"
    if spot.region == "중산간":
        where += " 중산간"
    return f"{where} · {spot.kind}"


def _spot_item(spot: spots.Spot, label: str, route=None) -> Item:
    """관측지를 목록 박스 한 줄로."""
    return Item(
        label=label,
        lat=spot.lat,
        lon=spot.lon,
        sub=_where(spot),
        facts=_spot_facts(spot, route),
    )


#: 국립공원공단 노면 낱말 → 사람이 읽는 말. 원문은 배점표의 이름이라 그대로 쓰면
#: "노면 포장"처럼 무엇을 밟는지가 안 보인다. 괄호 안은 원문 정의 그대로다.
_SURFACE_WORDS: dict[str, str] = {
    "포장": "데크·콘크리트 같은 단단한 길",
    "거의 흙": "거의 흙바닥",
    "비교적 흙": "흙바닥에 돌이 섞임",
    "비교적 돌": "돌바닥에 흙이 섞임",
    "거의 돌": "거의 돌바닥",
}

#: 암릉 낱말 → 사람이 읽는 말. '목재계단' 은 갈래 이름(계단)이 이미 말하므로 뺀다 —
#: "계단 · 노면 포장 · 목재계단"처럼 같은 말이 세 번 나오면 오히려 안 읽힌다.
_ROCK_WORDS: dict[str, str] = {
    "약간의 암반": "암반 조금",
    "로프·사다리": "로프·사다리를 잡고 오르는 구간",
    "손 사용": "손으로 잡고 오르내리는 구간",
}


def _segment_note(seg: spots.WalkSegment) -> str:
    """구간을 눌렀을 때 뜨는 한 줄 — 길이가 먼저다.

    "계단"만 떠서는 각오할 양을 모른다. 10m 계단과 260m 계단은 다른 이야기다.

    낱말은 국립공원공단 배점표의 이름을 그대로 쓰지 않는다. "노면 포장"은 무엇을 밟는지
    안 보이고, 계단인데 "노면 포장 · 목재계단"이라 적히면 오히려 헷갈린다. 갈래 이름이
    이미 말하는 것은 빼고, 노면은 어떤 땅인지로 풀어 쓴다.

    경사는 원본이 잰 구간만 붙는다(짐작으로 채우지 않는다).
    """
    parts = [f"{seg.metres:.0f}m"]

    # 계단·암반은 갈래 이름이 이미 무엇을 밟는지 말한다. 노면을 또 적지 않는다.
    if seg.kind in (spots.WALK_STAIR, spots.WALK_ROCK):
        extra = _ROCK_WORDS.get(seg.rock)
        if extra:
            parts.append(extra)
    elif seg.surface:
        parts.append(_SURFACE_WORDS.get(seg.surface, seg.surface))
    if seg.slope_deg is not None:
        # 평균은 양 끝만 보므로 올랐다 내려오면 상쇄된다. 구간 안 가장 가파른 창이
        # 그보다 크면 함께 적는다 — 안 적으면 그 비탈이 통째로 사라진다.
        steep = seg.slope_max_deg
        if steep is not None and abs(steep) > abs(seg.slope_deg) + 0.5:
            parts.append(f"평균 경사 {seg.slope_deg:.0f}° · 최대 {steep:.0f}°")
        else:
            parts.append(f"평균 경사 {seg.slope_deg:.0f}°")
    return " · ".join(parts)


def _walk_layers(spot: spots.Spot) -> list[tuple[list[tuple[float, float]], str, str]]:
    """도보 구간을 지도가 받는 모양으로."""
    return [
        (list(g.points), g.kind, _segment_note(g)) for g in spot.walk_segments
    ]


def _spot_map(spot: spots.Spot, route=None) -> str | None:
    """검증된 관측지 한 곳의 지도 — 도보 경로 + 주차·화장실.

    **주행 경로는 그리지 않는다.** 제주를 가로지르는 선이 들어오면 지도가 섬 전체로
    줌아웃되어, 정작 봐야 할 도보 경로와 계단 구간이 점으로 뭉개진다. 주행시간은
    숫자와 문장으로 답하고(`numbers.drive`·설명 줄), 지도는 도착한 다음을 맡는다.

    편의시설은 **사람이 확인한 것**을 쓴다(반경 검색이 아니라 `jeju_spots.json`).
    확인된 자리가 그 관측지에 실제로 쓰는 자리이기 때문이다.
    """
    markers = [Marker(spot.lat, spot.lon, "spot", spot.name, spot.kind)]
    walk_segments = _walk_layers(spot)

    for lot in spot.parking:
        if lot.get("lat") is None or lot.get("lon") is None:
            continue
        markers.append(Marker(
            float(lot["lat"]), float(lot["lon"]), "parking",
            lot.get("name", "주차장"), lot.get("fee", ""),
        ))
    for wc in spot.toilet:
        if wc.get("lat") is None or wc.get("lon") is None:
            continue
        markers.append(Marker(
            float(wc["lat"]), float(wc["lon"]), "toilet", wc.get("name", "화장실"),
        ))

    # 사람이 확인한 것 **말고도** 반경 안에 있는 것을 얹는다. 검증분은 "이 관측지에
    # 쓰는 자리"라 하나뿐인 경우가 많은데, 옆에 다른 주차장·화장실이 있으면 그것도
    # 선택지다. 이미 찍은 자리와 50m 안이면 같은 곳으로 보고 건너뛴다.
    placed = [(m.lat, m.lon) for m in markers]
    for extra in _amenity_markers(spot.lat, spot.lon, MAP_NEARBY_M):
        if any(_haversine_m(extra.lat, extra.lon, a, b) < 50.0 for a, b in placed):
            continue
        placed.append((extra.lat, extra.lon))
        markers.append(extra)
    caption_parts = []
    if route is not None:
        caption_parts.append(f"차로 약 {route.minutes:.0f}분 / {route.km:.0f}km")
    caption_parts.append(_walk_phrase(spot))

    return maps.write(
        title=f"{spot.name} 도착 이후",
        markers=markers,
        walk_segments=walk_segments,
        caption=" · ".join(caption_parts),
        items=[_spot_item(spot, spot.name, route)],
    )


def _place_map(
    lat: float,
    lon: float,
    name: str,
    route=None,
) -> tuple[str | None, list[Marker]]:
    """등록되지 않은 자리의 지도 — 그 점 + 반경 안 편의시설(+ 출발지면 주행 경로).

    도보 경로는 그리지 않는다. 어디에 세우고 어디로 걷는지는 사람이 확인한 곳에만
    있는 정보라, 없는 선을 그리면 있는 것처럼 보인다.
    """
    amenities = _amenity_markers(lat, lon, NEARBY_M)
    markers = [Marker(lat, lon, "spot", name, "등록되지 않은 지점"), *amenities]

    caption = f"반경 {NEARBY_M:.0f}m 안 편의시설"
    if route is not None:
        caption = f"차로 약 {route.minutes:.0f}분 / {route.km:.0f}km · " + caption

    return maps.write(
        title=f"{name} 주변",
        markers=markers,
        caption=caption,
    ), amenities


# --- 출발지 해석 ----------------------------------------------------------------


def _locate(query: str | None, lat: float | None, lon: float | None):
    """질의 또는 좌표를 (lat, lon, resolved) 로 만든다. 못 찾으면 None.

    등록된 관측지 이름이 먼저다 — "새별오름"을 지오코딩에 보내기 전에 우리 목록에서
    찾는다. 우리가 검증한 좌표가 외부 지오코더의 것보다 정확하고, 외부 호출도 아낀다.
    """
    if lat is not None and lon is not None:
        return float(lat), float(lon), None

    if not query or not query.strip():
        return None

    hit = spots.find(query)
    if hit is not None:
        return hit.lat, hit.lon, {
            "query": query,
            "matched_query": hit.name,
            "display_name": f"{hit.name} (검증된 관측지)",
            "lat": hit.lat,
            "lon": hit.lon,
        }

    try:
        geo = geocode(query)
    except Exception:
        geo = None
    if geo is None:
        return None
    return geo.lat, geo.lon, {
        "query": query,
        "matched_query": geo.matched_query,
        "display_name": geo.display_name,
        "lat": geo.lat,
        "lon": geo.lon,
    }


def _not_found(query: str) -> dict:
    """좌표를 못 찾았을 때의 프롬프트형 응답."""
    return Response(
        verdict="주소 확인 실패",
        reasons=[
            f"'{query}'의 위치를 제주에서 찾지 못했습니다. "
            "좌표(위도·경도)를 알면 lat·lon 으로 바로 평가할 수 있어요. "
            "아니면 더 구체적인 주소·지명으로 다시 시도해 주세요."
        ],
        numbers={},
        attribution=["지오코딩: Photon (OpenStreetMap)"],
        as_of=_now_iso(),
    ).to_dict()


# ==============================================================================
# 도구 1 — 관측지 추천
# ==============================================================================


def recommend_spots(
    origin: str | None = None,
    origin_lat: float | None = None,
    origin_lon: float | None = None,
    max_drive_minutes: float | None = None,
    region: str | None = None,
    no_climb: bool = False,
    max_walk_minutes: float | None = None,
    parking_required: bool = False,
    pets: bool = False,
    date: str | None = None,
    time: str | None = None,
    limit: int = 3,
) -> dict:
    """조건에 맞는 제주 별 관측지를 추천한다 (검증된 63곳 중에서).

    "지금 근처에서 별 보기 좋은 곳", "제주 동쪽에서 추천", "30분 안에 갈 수 있는 곳",
    "주차장에서 바로 보는 곳", "등산 없는 곳" 같은 질의를 처리한다.

    출발지를 주면 **실제 도로를 따라간 주행시간**으로 자르고 순위에 반영한다
    (직선거리가 아니다 — 제주는 가운데가 한라산이라 직선거리로 자르면 산 반대편을
    추천하게 된다). 정체는 반영하지 않는 야간 자유주행 기준이다.

    Args:
        origin: 출발지 지명·주소 (예: '제주공항', '애월읍'). origin_lat/lon 과 택일.
        origin_lat: 출발지 위도. origin_lon 과 함께 줄 때만 쓴다(현재 위치 등).
        origin_lon: 출발지 경도.
        max_drive_minutes: 이 시간 안에 갈 수 있는 곳만. 출발지가 있어야 동작한다.
        region: '동'·'서'·'남'·'북'·'중산간' 중 하나로 지역을 좁힌다.
        no_climb: True 면 오르막 산행이 필요한 곳을 뺀다("등산 없는 곳").
        max_walk_minutes: 주차 지점에서 관측 지점까지 편도 도보가 이 시간 이하인 곳만.
            0 을 주면 "주차하고 바로 보는 곳"에 가깝다.
        parking_required: True 면 주차장이 확인된 곳만.
        pets: True 면 반려동물 동반이 가능한 곳만.
        date: 판정 기준 날짜 YYYY-MM-DD (생략 시 오늘).
        time: 판정 기준 시각 HH:MM 24시간 KST (생략 시 22:00).
        limit: 돌려줄 곳 수. 기본 3, 최대 10.

    Returns:
        고정 스키마 dict. 추천 목록은 `spots` 배열에 있고 각 항목에 주행시간(`drive`)·
        도보(`walk_minutes`)·야간 출입(`night_access`)이 들어 있다.
    """
    invalid = _validate_inputs(date, time, "moment")
    if invalid is not None:
        return invalid

    try:
        n = max(1, min(int(limit), _LIMIT_MAX))
    except (TypeError, ValueError):
        n = _LIMIT_DEFAULT

    if region is not None and region.strip() and region.strip() not in spots.REGIONS:
        return Response(
            verdict="입력 오류",
            reasons=[
                f"region 값을 이해하지 못했습니다 (region={region!r}). "
                f"{' · '.join(spots.REGIONS)} 중 하나로 주세요."
            ],
            numbers={},
            attribution=[],
            as_of=_now_iso(),
        ).to_dict()

    # 1) 정적 조건으로 후보를 좁힌다 (외부 호출 0회).
    candidates = spots.filter_spots(
        region=(region or "").strip() or None,
        no_climb=no_climb,
        max_walk_minutes=max_walk_minutes,
        parking_required=parking_required,
        pets=pets,
    )
    attribution = [spots.source()]

    # 2) 출발지가 있으면 주행시간으로 자르고, 없으면 거리 축을 빼고 간다.
    origin_resolved = None
    routes: dict[str, object] = {}
    if origin or (origin_lat is not None and origin_lon is not None):
        found = _locate(origin, origin_lat, origin_lon)
        if found is None:
            return _not_found(origin or "")
        o_lat, o_lon, origin_resolved = found
        if not _in_jeju(o_lat, o_lon):
            return _out_of_range(o_lat, o_lon)

        legs = routing.drive_times(
            (o_lat, o_lon),
            [s.drive_target() for s in candidates],
            budget_minutes=max_drive_minutes,
        )
        attribution.append(routing.SOURCE)
        kept = []
        for s, leg in zip(candidates, legs, strict=True):
            if leg is None:
                continue
            routes[s.name] = leg
            kept.append(s)
        candidates = kept

    if not candidates:
        return Response(
            verdict="조건에 맞는 관측지를 찾지 못했어요",
            reasons=[_no_candidate_reason(max_drive_minutes, region, no_climb)],
            numbers={"candidates": 0},
            attribution=attribution,
            as_of=_now_iso(),
            resolved=origin_resolved,
            spots=[],
        ).to_dict()

    # 3) 어둡기(정적)로 먼저 줄인다 — 여기까지 외부 호출이 없다.
    #    점수는 0=완전 암흑 ~ 1=도심이라 작을수록 좋다.
    scored = []
    for s in candidates:
        site = darkness.assess_site(s.lat, s.lon)
        # 점수를 못 낸 곳(SQM 격자 밖)은 뒤로 보내되 버리지는 않는다.
        scored.append((site.score if site.score is not None else 1.0, s))
    scored.sort(key=lambda t: t[0])
    pool = [s for _, s in scored[: max(n, _WEATHER_POOL)]]

    # 4) 남은 후보만 날씨까지 실제로 판정한다 (외부 호출 = len(pool)).
    when = _resolve_when(date, time)
    judged = []
    for s in pool:
        final = graph.run(s.lat, s.lon, when)
        judged.append((s, final))
        for a in final.get("attribution", []):
            if a not in attribution:
                attribution.append(a)

    # 5) 관측 가능한 곳 먼저, 그다음 어두운 순, 그다음 가까운 순.
    def rank(item):
        s, final = item
        nums = final.get("numbers", {})
        score = nums.get("darkness_score")
        leg = routes.get(s.name)
        return (
            0 if final.get("possible") else 1,
            score if score is not None else 1.0,
            leg.minutes if leg is not None else 0.0,
        )

    judged.sort(key=rank)
    top = judged[:n]

    rows = []
    for s, final in top:
        row = _spot_row(s, route=routes.get(s.name))
        row["verdict"] = final.get("verdict") or "불가"
        row["cloud_cover"] = final.get("numbers", {}).get("cloud_cover")
        row["darkness_score"] = final.get("numbers", {}).get("darkness_score")
        row["bortle"] = final.get("numbers", {}).get("bortle")
        rows.append(row)

    # 지도 — 고른 곳들을 한 장에. 주행 경로는 긋지 않는다(섬 전체로 줌아웃된다).
    # 주행시간은 목록 박스의 `차 N분` 조각과 응답의 `drive` 로 답한다.
    markers = [
        Marker(s.lat, s.lon, "spot", f"{i}. {s.name}", f"{s.region}·{s.kind}")
        for i, (s, _) in enumerate(top, start=1)
    ]
    items = [
        _spot_item(s, f"{i}. {s.name}", routes.get(s.name))
        for i, (s, _) in enumerate(top, start=1)
    ]
    map_url = maps.write(
        title=f"관측지 추천 {len(rows)}곳",
        markers=markers,
        walk_segments=[layer for s, _ in top for layer in _walk_layers(s)],
        caption=_recommend_verdict(rows, origin_resolved),
        items=items,
    )

    reasons = _recommend_reasons(top, routes)
    if map_url:
        reasons.append(f"고른 곳들을 지도로 봤어요 → {map_url}")

    return Response(
        verdict=_recommend_verdict(rows, origin_resolved),
        reasons=reasons,
        numbers={
            "candidates": len(candidates),
            "evaluated": len(pool),
            "returned": len(rows),
            "when": when.isoformat(timespec="minutes"),
        },
        attribution=attribution,
        as_of=when.isoformat(timespec="minutes"),
        resolved=origin_resolved,
        spots=rows,
        map_url=map_url,
    ).to_dict()


def _no_candidate_reason(
    max_drive_minutes: float | None, region: str | None, no_climb: bool
) -> str:
    """왜 후보가 없는지 — 조건을 되짚어 준다. 어느 조건을 풀지 사용자가 정하게."""
    conds = []
    if max_drive_minutes is not None:
        conds.append(f"주행 {max_drive_minutes:.0f}분 이내")
    if region:
        conds.append(f"{region} 지역")
    if no_climb:
        conds.append("등산 없는 곳")
    if not conds:
        return "조건에 맞는 관측지가 없습니다."
    return (
        f"{' · '.join(conds)} 조건을 모두 만족하는 관측지가 없어요. "
        "조건을 하나 풀어서 다시 물어봐 주세요."
    )


def _recommend_verdict(rows: list[dict], origin_resolved: dict | None) -> str:
    if not rows:
        return "조건에 맞는 관측지를 찾지 못했어요"
    best = rows[0]
    head = f"'{best['name']}'을 추천해요"
    if "drive" in best:
        head += f" (차로 약 {best['drive']['minutes']:.0f}분)"
    if len(rows) > 1:
        head += f" — 조건에 맞는 곳 {len(rows)}곳을 골랐어요"
    return head


def _recommend_reasons(judged: list, routes: dict) -> list[str]:
    """추천 목록을 사람이 읽는 줄들로. 곳마다 왜 골랐는지 한 덩어리씩."""
    lines: list[str] = []
    for i, (s, final) in enumerate(judged, start=1):
        leg = routes.get(s.name)
        head = f"{i}. {s.name} ({s.region}·{s.kind})"
        if leg is not None:
            head += f" — 차로 약 {leg.minutes:.0f}분 / {leg.km:.0f}km"
        lines.append(head)
        lines.append(f"   판정: {final.get('verdict') or '불가'} · {s.why}")
        lines.append("   " + _walk_phrase(s))
        if s.night_access:
            lines.append(f"   야간 출입: {s.night_access}")
    return lines


# ==============================================================================
# 도구 2 — 특정 장소 관측 가능 여부
# ==============================================================================


def evaluate_place(
    query: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    origin: str | None = None,
    origin_lat: float | None = None,
    origin_lon: float | None = None,
    date: str | None = None,
    time: str | None = None,
    scope: str = "moment",
) -> dict:
    """지목한 제주 장소에서 별이 보이는지 판정한다.

    "오늘 1100고지에서 별 보여?", "지금 새별오름 가면 별 잘 보일까?" 같은 질의.
    장소는 이름(`query`)으로 주거나 좌표(`lat`·`lon`)로 준다 — 둘 중 하나면 된다.

    **등록되지 않은 장소도 판정한다.** 좌표만 알면 날씨·광공해·천문 조건은 똑같이
    계산된다. 다만 주차·야간 출입·도보 난이도는 검증된 관측지 63곳에만 있으므로,
    미등록 장소는 그 정보가 **확인되지 않았음을 응답에 명시**한다. 접근성까지 알고
    싶으면 `recommend_spots` 로 등록된 곳을 받거나 `spot_details` 로 조회한다.

    **출발지(현재 위치)를 주면 거기서 몇 분 걸리는지 함께 답한다.** 등록 여부와
    무관하다 — 주행시간은 좌표만 있으면 도로 그래프로 계산되기 때문이다. 미등록
    장소에서 답할 수 있는 접근성은 이 주행시간까지이고, 주차·야간 출입은 여전히
    모른다. 실제 도로 기준이며 정체는 반영하지 않는다(야간 자유주행).

    Args:
        query: 장소 이름·주소 (예: '1100고지', '새별오름', '제주시 애월읍').
        lat: 위도. lon 과 함께 줄 때만 쓴다. query 대신 좌표로 물을 때.
        lon: 경도.
        origin: 출발지 지명·주소 (예: '제주공항'). 주행시간을 함께 받고 싶을 때.
        origin_lat: 출발지 위도. origin_lon 과 함께 줄 때만 쓴다(현재 위치 등).
        origin_lon: 출발지 경도.
        date: YYYY-MM-DD (생략 시 오늘). 미래 날짜 가능(구름은 예보 지평 ~7일 안).
        time: HH:MM 24시간 KST. scope="moment" 에서만(생략 시 22:00; date·time 모두
            생략 시 현재). scope="night" 이면 무시.
        scope: "moment"(한 시각) | "night"(밤 전체 시간 수·등급 분포). 기본 "moment".

    Returns:
        고정 스키마 dict. 등록된 관측지면 `spots` 에 그 곳의 접근성 요약이 실리고,
        출발지를 줬으면 `numbers.drive` 에 주행시간·거리가 실린다.
    """
    invalid = _validate_inputs(date, time, scope)
    if invalid is not None:
        return invalid

    if (lat is None or lon is None) and not (query or "").strip():
        return Response(
            verdict="입력 오류",
            reasons=[
                "평가할 장소를 알려주세요. 이름(query='새별오름')이나 "
                "좌표(lat=33.36, lon=126.36) 중 하나면 됩니다."
            ],
            numbers={},
            attribution=[],
            as_of=_now_iso(),
        ).to_dict()

    found = _locate(query, lat, lon)
    if found is None:
        return _not_found(query or "")
    p_lat, p_lon, resolved = found

    # 등록된 관측지인지 본다 — 이름으로 찾았거나, 좌표가 등록된 곳 바로 옆이거나.
    known = spots.find(query) if query else None
    if known is None:
        known = _nearest_known(p_lat, p_lon)

    # 출발지가 있으면 주행시간을 잰다. 등록 여부와 무관하다 — 도로 그래프는 좌표만
    # 있으면 답한다(architecture §0 의 2×2: 출발지가 있으면 목적지를 지정했든 아니든
    # 걸리는 시간을 함께 답한다). 답하는 것은 **숫자와 문장**이고, 지도에는 싣지 않는다
    # — 섬을 가로지르는 선이 들어오면 지도가 줌아웃되어 도보 경로가 뭉개진다.
    # 차로 향할 지점은 등록된 곳이면 주차장, 아니면 그 좌표 자체다.
    route = None
    if origin or (origin_lat is not None and origin_lon is not None):
        o = _locate(origin, origin_lat, origin_lon)
        if o is not None and _in_jeju(o[0], o[1]):
            target = known.drive_target() if known is not None else (p_lat, p_lon)
            route = routing.drive_time((o[0], o[1]), target)

    spot_rows = [_spot_row(known, route=route)] if known is not None else None
    result = _evaluate(p_lat, p_lon, date, time, scope, resolved, spot_rows)

    # 실패 응답(범위 밖 등)에는 안내를 덧붙이지 않는다 — 이미 할 말이 정해져 있다.
    if result["verdict"] in ("지원 범위 밖", "입력 오류"):
        return result

    if route is not None:
        result["numbers"]["drive"] = route.to_dict()
        result.setdefault("attribution", []).append(routing.SOURCE)

    # 지도 — 등록된 곳은 사람이 확인한 주차·화장실과 도보 경로를, 등록되지 않은 곳은
    # 반경 안 편의시설만 그린다. 없는 선을 그리면 있는 것처럼 보인다.
    if known is not None:
        result["map_url"] = _spot_map(known, route)
        amenities = []
    else:
        label = (resolved or {}).get("display_name") or (query or "이 지점")
        result["map_url"], amenities = _place_map(p_lat, p_lon, str(label), route)
        for source in (parking.SOURCE, places.SOURCE, toilet.SOURCE):
            if source not in result.setdefault("attribution", []):
                result["attribution"].append(source)

    reasons = result.setdefault("reasons", [])
    if resolved is not None:
        matched = resolved.get("matched_query")
        if matched and matched != query:
            where = f"({resolved['lat']:.4f}, {resolved['lon']:.4f})"
            note = (
                f"'{query}'를 정확히 못 찾아 '{matched}'로 검색했어요 → "
                f"{resolved['display_name']} {where}"
            )
        else:
            note = (
                f"'{query}' → {resolved['display_name']} "
                f"({resolved['lat']:.4f}, {resolved['lon']:.4f})로 해석했어요"
            )
        reasons.insert(0, note)
        if known is None:
            attr = result.setdefault("attribution", [])
            attr.append("지오코딩: Photon (OpenStreetMap)")

    # 주행시간은 등록 여부와 무관하게 먼저 말한다 — 사용자가 가장 먼저 궁금해하는
    # 것이고, 미등록 장소에서 답할 수 있는 접근성이 이것 하나뿐이다.
    if route is not None:
        reasons.append(
            f"지금 위치에서 차로 약 {route.minutes:.0f}분 / {route.km:.0f}km 거리예요 "
            "(실제 도로 기준, 정체는 반영하지 않은 야간 자유주행)"
        )

    if known is not None:
        reasons.append(
            f"이곳은 검증된 관측지예요 — {_walk_phrase(known)}. "
            f"야간 출입: {known.night_access or '확인 필요'}. "
            f"자세한 접근성은 spot_details('{known.name}') 로 볼 수 있어요"
        )
        result.setdefault("attribution", []).append(spots.source())
    elif route is not None:
        reasons.append(_amenity_reason(amenities, NEARBY_M))
        reasons.append(
            "다만 이 위치는 검증된 관측지 목록에 없어요. 하늘 상태(날씨·광공해·박명)와 "
            "위 주행시간은 좌표만으로 계산되지만, **주차 가능 여부·야간 출입·진입로 "
            "상태·도보 난이도는 확인되지 않았습니다.** 초행에 밤에 가신다면 "
            "recommend_spots 로 검증된 곳을 받아 보시는 편이 안전해요"
        )
    else:
        reasons.append(_amenity_reason(amenities, NEARBY_M))
        reasons.append(
            "이 위치는 검증된 관측지 목록에 없어요. 하늘 상태(날씨·광공해·박명)는 "
            "위와 같이 판정했지만 **주차 가능 여부·야간 출입·진입로 상태·도보 난이도는 "
            "확인되지 않았습니다.** 초행에 밤에 가신다면 recommend_spots 로 검증된 "
            "곳을 받아 보시는 편이 안전해요"
        )

    if result.get("map_url"):
        reasons.append(f"경로와 주변을 지도로 봤어요 → {result['map_url']}")

    return result


def _nearest_known(lat: float, lon: float) -> spots.Spot | None:
    """좌표가 등록된 관측지 바로 옆인지 본다. 아니면 None."""
    best, best_m = None, _SAME_SPOT_M
    for s in spots.all_spots():
        d = _haversine_m(lat, lon, s.lat, s.lon)
        if d <= best_m:
            best, best_m = s, d
    return best


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(math.sqrt(a))


# ==============================================================================
# 도구 3 — 관측지 상세정보
# ==============================================================================


def spot_details(name: str, origin: str | None = None,
                 origin_lat: float | None = None,
                 origin_lon: float | None = None) -> dict:
    """검증된 관측지의 주차·도보·야간 출입·반려동물·화장실·주의사항을 조회한다.

    "매오름 많이 걸어야 해?", "강아지랑 갈 수 있어?", "새별오름 밤에 들어갈 수 있어?",
    "천아계곡까지 가기 어려워?" 같은 질의를 처리한다. 하늘 상태는 답하지 않는다 —
    그건 `evaluate_place` 소관이다.

    출발지를 주면 그곳까지의 주행시간도 함께 답한다.

    Args:
        name: 관측지 이름 (예: '새별오름', '매오름'). 띄어쓰기는 달라도 된다.
        origin: 출발지 지명·주소. 주행시간을 함께 받고 싶을 때.
        origin_lat: 출발지 위도 (origin_lon 과 함께).
        origin_lon: 출발지 경도.

    Returns:
        고정 스키마 dict. 상세는 `spots` 배열의 한 항목에 전부 들어 있다.
    """
    hit = spots.find(name or "")
    if hit is None:
        return Response(
            verdict="등록된 관측지가 아니에요",
            reasons=[
                f"'{name}'은 검증된 관측지 목록(63곳)에 없어요. "
                "이름을 다르게 불러 보시거나, recommend_spots 로 조건에 맞는 곳을 "
                "받아 보세요. 하늘 상태만 알고 싶으면 evaluate_place 로 물어보시면 "
                "미등록 장소도 판정합니다."
            ],
            numbers={},
            attribution=[spots.source()],
            as_of=_now_iso(),
            spots=[],
        ).to_dict()

    attribution = [spots.source()]
    route = None
    origin_resolved = None
    if origin or (origin_lat is not None and origin_lon is not None):
        found = _locate(origin, origin_lat, origin_lon)
        if found is not None:
            o_lat, o_lon, origin_resolved = found
            if _in_jeju(o_lat, o_lon):
                route = routing.drive_time((o_lat, o_lon), hit.drive_target())
                attribution.append(routing.SOURCE)
            else:
                # 제주 밖 출발지는 주행을 답하지 않으므로 지도에도 싣지 않는다.
                origin_resolved = None

    row = _spot_row(hit, detail=True, route=route)
    map_url = _spot_map(hit, route)

    reasons = [f"{hit.name} — {_where(hit)}"]
    if hit.why:
        reasons.append(hit.why)
    # `notes` 는 내보내지 않는다. 사람이 읽을 메모와 **좌표 교정 기록**이 한 칸에
    # 섞여 있어서다("좌표 교정(2026-08-05): ... scripts/check_spot_coords.py").
    # 63곳 중 3곳이 그렇다. 낱말로 걸러 낼 수는 있지만 그건 데이터가 섞인 것을
    # 코드로 덮는 일이라, 칸이 갈릴 때까지 `why`(큐레이션된 설명)만 쓴다.
    if route is not None:
        reasons.append(f"차로 약 {route.minutes:.0f}분 / {route.km:.0f}km 거리예요")
    if hit.parking:
        names = ", ".join(p.get("name", "주차장") for p in hit.parking)
        fee = hit.parking[0].get("fee")
        reasons.append(f"주차: {names}" + (f" ({fee})" if fee else ""))
    else:
        reasons.append("주차: 확인된 주차장이 없어요")
    reasons.append(_walk_phrase(hit))
    terrain = _terrain_phrase(hit)
    if terrain:
        reasons.append(terrain)
    if hit.access:
        reasons.append(f"진입: {hit.access}")
    reasons.append(f"야간 출입: {hit.night_access or '확인 필요'}")
    if hit.pets:
        reasons.append(f"반려동물: {hit.pets}")
    reasons.append(_toilet_status(hit)[2])
    if hit.fee:
        reasons.append(f"요금: {hit.fee}")
    for c in hit.cautions:
        reasons.append(f"주의: {c}")
    if map_url:
        reasons.append(f"주차 자리와 걷는 길을 지도로 봤어요 → {map_url}")

    return Response(
        verdict=f"{hit.name} 접근성 정보예요",
        reasons=reasons,
        numbers={
            "elevation_m": hit.elevation_m,
            "slope_deg": hit.slope_deg,
            "walk_minutes": row["walk_minutes"],
            "parking_count": len(hit.parking),
            "toilet_count": len(hit.toilet),
            **({"drive": route.to_dict()} if route is not None else {}),
        },
        attribution=attribution,
        as_of=_now_iso(),
        resolved=origin_resolved,
        spots=[row],
        map_url=map_url,
    ).to_dict()
