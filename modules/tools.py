"""도구 본체 — 좌표·지명을 받아 고정 스키마 dict 를 돌려주는 **순수 파이썬 함수**.

여기에는 MCP 가 없다. 도구의 **계약**(이름·설명·인자)은 `modules/routes.py` 의 FastAPI
라우트가 들고, 전송(streamable HTTP)은 `app.py` 소관이다. 이 모듈은 "무엇을
판정하는가"만 안다. 갈라 둔 이유는 둘이다:

1. 도구 정의와 판정 로직이 한 파일에 있으면 테스트가 판정을 직접 부를 수 없어
   SDK 내부 표현에 묶인다. 여기 함수들은 평범한 파이썬 함수로 남는다.
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
`data/jeju_spots.json` 의 62곳은 사람이 로드뷰·위성으로 확인한 자리다. 그 밖의 좌표도
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

from modules import maps
from modules.clients.geocode import geocode
from modules.core import astro, darkness, parking, places, routing, spots, toilet
from modules.core.mapview import Fact, Item, Marker, Walk
from modules.engine import graph
from modules.schema import Response

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

#: 미등록 지점에서 "근처의 검증된 관측지"를 찾을 때의 주행 반경(분)과 개수 —
#: **운영값**. 이미 그 근처까지 온 사람이 밤에 옮겨갈 만한 거리로 잡았다. 개수를 둘로
#: 묶는 것은 이 자리가 추천 도구가 아니기 때문이다 — 조건 필터도 순위 옵션도 없이,
#: 미등록이라 답하지 못한 접근성을 메우는 꼬리말로만 둔다. 조건을 걸어 고르는 것은
#: `recommend_spots` 소관이다.
_ALT_DRIVE_MINUTES = 20.0
_ALT_MAX = 2

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

#: 시각을 안 준 질문("오늘 밤 별 보여?")에 쓰는 기준 시각.
#: 22:00 이었으나 23:00 으로 옮겼다 — 제주 여름 천문박명이 20:40 께 끝나 22시는
#: 아직 하늘이 덜 가라앉은 시각이고, 사람이 실제로 별을 보러 나가는 때는 그보다
#: 늦다. 24:00 은 쓰지 않는다: 날짜가 넘어가 "오늘 밤"이 전날 밤을 가리키게 된다.
DEFAULT_HOUR = 23


def _forecast_caveat(when: datetime) -> str:
    """예보로 판정했다는 것을 답 끝에 한 줄로 밝힌다.

    구름·시정은 **예보**지 관측값이 아니다. 그런데 응답 문장들이 "양호"·"최적"처럼
    단정형이라, 그대로 옮기면 사용자에게는 확정된 사실로 읽힌다. 제주는 한라산을
    사이에 두고 오름과 해안의 하늘이 갈리고(이 측정에서도 같은 시각 같은 섬 안에서
    구름 9%~99% 가 나왔다) 예보도 자주 갱신된다.

    날짜가 멀수록 세게 말한다 — 오늘 밤과 사흘 뒤를 같은 말로 덧붙이면, 그 말이
    아무 곳에나 붙는 상투구가 되어 정작 읽어야 할 때 안 읽힌다.

    `spot_details` 에는 붙이지 않는다. 주차·화장실·야간 출입은 예보가 아니라 사람이
    확인해 둔 값이라 이 주의가 해당하지 않는다.
    """
    days = (when.date() - datetime.now(KST).date()).days
    tail = "며칠 뒤 예보라 더 그래요 — " if days >= 2 else ""
    return (f"참고로 구름·시정은 예보값이에요. {tail}제주는 오름과 해안 사이에서도 "
            "하늘이 갈리고 예보가 자주 바뀌니, 떠나기 전에 한 번 더 확인해 보세요")



def _resolve_when(date: str | None, time: str | None) -> datetime:
    """평가 시각을 KST datetime 으로 만든다.

    - date(YYYY-MM-DD) 생략 → 오늘
    - time(HH:MM, 24시간) 생략 → DEFAULT_HOUR(23:00)
    - date·time 모두 생략 → 현재 시각 그대로
    파싱 실패 시 ValueError.
    """
    now = datetime.now(KST)
    if date is None and time is None:
        return now
    y, m, d = (now.year, now.month, now.day) if date is None else (
        int(x) for x in date.split("-")
    )
    hh, mm = (DEFAULT_HOUR, 0) if time is None else (int(x) for x in time.split(":"))
    return datetime(y, m, d, hh, mm, tzinfo=KST)


def _resolve_plan_when(date: str | None, time: str | None) -> datetime:
    """추천이 쓰는 기준 시각. date 생략 → 오늘, time 생략 → DEFAULT_HOUR.

    `_resolve_when` 과 **한 군데가 다르다**: 둘 다 생략해도 '지금'으로 떨어지지 않는다.
    추천은 "어디로 갈까"를 묻는 도구라 낮에도 부른다. 지금 시각으로 판정하면 오후
    네 시에 물었을 때 전부 '불가'가 나오는데, 그건 하늘이 아니라 질문을 잘못 읽은
    것이다. (평가는 다르다 — "지금 별 보여?"는 지금이 맞다.)

    파싱 실패 시 ValueError.
    """
    now = datetime.now(KST)
    y, m, d = (now.year, now.month, now.day) if date is None else (
        int(x) for x in date.split("-")
    )
    hh, mm = (DEFAULT_HOUR, 0) if time is None else (int(x) for x in time.split(":"))
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

    # 판정을 **완결된 문장 한 줄**로 산문 맨 앞에 둔다.
    #
    # 두 번 틀렸다. (1) "판정: 양호" 라는 딱지만 두었더니 모델이 낱말 "판정"은 가져가면서
    # 값은 다른 데서 집어 왔다 — `numbers.darkness_cap` 에 "최적" 이 들어 있었기 때문이다
    # (그 필드는 응답에서 뺐다). (2) 그래서 "판정: 양호 · 구름 20% · 어둡기 4단계" 로
    # 세 값을 한 줄에 묶었더니, 모델이 **숫자만 집고 등급 낱말은 풀어 썼다** — 그전까지
    # 잘 옮기던 E-04·E-07 까지 놓치기 시작했다. 숫자는 제 줄에 이미 있으므로 여기서는
    # 등급 하나만, 인용부호를 붙인 완결 문장으로 둔다. 딱지보다 문장이 옮겨진다.
    if final.get("verdict"):
        reasons.insert(0, f"이곳의 관측 조건은 '{final['verdict']}' 입니다")

    # 관측 가능하면 오늘 완전히 어두운 시간대를 덤으로 알려준다.
    window = nums.get("dark_window")
    if final.get("possible") and window:
        reasons.append(
            f"참고로 오늘 완전히 어두운 시간대는 "
            f"{window['start'][11:16]}~{window['end'][11:16]}예요"
        )

    reasons.append(_forecast_caveat(when))

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
        f"구름이 거의 없는 시간(구름 30% 이하) {summary['photometric_hours']}시간, "
        f"조금 있는 시간(50% 이하) {summary['spectroscopic_hours']}시간"
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

    reasons.append(_forecast_caveat(when))

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
    사람에게는 늦는 쪽이 위험하므로 오차 폭을 얹은 값을 쓴다
    (`spots.WALK_MARGIN_MIN_PER_KM`).

    한때 "(넉넉히 잡은 값 · 잰 값 20분)"을 괄호로 달았는데 뺐다. 어디서 온 숫자인지는
    문서가 말할 일이고, 화면에서는 **얼마나 걸리나** 하나만 읽히는 편이 낫다.
    잰 값이 필요하면 응답의 `numbers`·`spots` 에 둘 다 있다.
    """
    minutes = s.walk_minutes_safe or s.walk_minutes
    if minutes is None:
        return "도보 시간은 재지 못했어요"
    if minutes < spots.IMMEDIATE_WALK_MIN:
        return "주차 후 바로 관측 가능해요"
    return f"주차장에서 관측지까지 예상 소요시간: 약 {minutes:.0f}분"


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
    elif s.walk_too_short:
        bits.append("걸을 것 없음")
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


def _toilet_status(spot: spots.Spot) -> tuple[str, str, str]:
    """화장실 상황 — (조각 글자, 결, 문장).

    **없으면 없다고 적는다.** 조용히 빼면 "안 적혀 있으니 있겠지"로 읽히는데, 밤에
    한참 걸어 올라간 뒤에 알게 되는 종류의 정보다.

    `MAP_NEARBY_M`(500m) 밖은 **없는 것으로 친다.** 한때 가장 가까운 곳까지의 거리를
    적었는데("3.3km 떨어진 표선충혼묘지"), 밤에 관측하다 3km 를 되돌아 나가지는 않는다 —
    쓸 수 없는 거리를 숫자로 적으면 있는 것처럼 읽히기만 한다.
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

    return (
        "화장실 없음", "warn",
        f"화장실: {MAP_NEARBY_M:.0f}m 안에 없어요",
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
    elif spot.walk_too_short:
        # 등급이 없어도 걱정할 일이 아니다 — 경사를 못 잴 만큼 짧다는 뜻이다.
        # '난이도 미상'(노랑)으로 두면 차에서 내려 바로인 자리가 경고로 읽힌다.
        facts.append(Fact("걸을 것 없음", "plain"))
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


#: 이보다 완만한 내리막은 방향을 적지 않는다. 3° 에서는 내려가나 올라가나 준비가
#: 달라지지 않는데, 내리막 19개 중 13개가 거기 걸려 "(내리막)"이 뜻 없이 반복된다.
#: 밤에 조심해야 하는 내리막은 송악산 전망대의 14° 같은 것이다.
_DOWNHILL_DEG = 5


def _slope_words(seg: spots.WalkSegment) -> str:
    """구간의 경사 한 조각. 못 잰 구간은 빈 문자열 — 아무것도 적지 않는다.

    **최대를 적는다. 평균이 아니다.** 평균은 양 끝만 보므로 올랐다 내려오면 상쇄된다 —
    송악산 전망대의 593m 구간은 평균 -0.9° 라 거의 평지처럼 읽히는데 그 안에 14.1°
    내리막이 들어 있고, 새별오름의 555m 는 평균 8.4° 인데 실제로는 21.4° 까지 선다.
    밤에 초행으로 오르는 사람이 각오할 것은 그 비탈이지 상쇄된 평균이 아니다.

    평균을 함께 적지 않는 것은 줄이 길어져서만이 아니다. 걷는 데 드는 시간은 이미
    도막마다의 경사로 따로 계산해(`elevation.walk_minutes`) `도보 N분` 으로 나가므로,
    평균이 답하던 몫은 그쪽이 더 정확하게 답하고 있다.

    최대를 아직 안 잰 자료는 가진 것을 **평균이라고 밝혀서** 적는다. 평균을 최대인
    척 내보내면 비탈을 낮춰 말하게 된다.
    """
    steep, average = seg.slope_max_deg, seg.slope_deg
    value = steep if steep is not None else average
    if value is None:
        return ""

    degrees = round(abs(value))
    if degrees == 0:
        # 재 보니 평평한 것과 아예 안 잰 것은 다른 말이다. 0° 를 그냥 지우면 둘이
        # 같아 보이고, `-0°` 라고 적으면 읽는 사람이 오타로 읽는다.
        return "거의 평평함"

    label = "최대 경사" if steep is not None else "평균 경사"
    down = "(내리막)" if value < 0 and degrees >= _DOWNHILL_DEG else ""
    return f"{label} {degrees}°{down}"


def _segment_note(seg: spots.WalkSegment) -> str:
    """구간을 눌렀을 때 뜨는 한 줄 — 길이가 먼저다.

    "계단"만 떠서는 각오할 양을 모른다. 10m 계단과 260m 계단은 다른 이야기다.

    낱말은 국립공원공단 배점표의 이름을 그대로 쓰지 않는다. "노면 포장"은 무엇을 밟는지
    안 보이고, 계단인데 "노면 포장 · 목재계단"이라 적히면 오히려 헷갈린다. 갈래 이름이
    이미 말하는 것은 빼고, 노면은 어떤 땅인지로 풀어 쓴다.

    경사는 가장 가파른 데 하나만 적는다 — 무엇을 왜 적는지는 `_slope_words` 에.
    사람이 적어 둔 말이 있으면 맨 뒤에 그대로 붙인다.
    """
    parts = [f"{seg.metres:.0f}m"]

    # 계단·암반은 갈래 이름이 이미 무엇을 밟는지 말한다. 노면을 또 적지 않는다.
    if seg.kind in (spots.WALK_STAIR, spots.WALK_ROCK):
        extra = _ROCK_WORDS.get(seg.rock)
        if extra:
            parts.append(extra)
    elif seg.surface:
        parts.append(_SURFACE_WORDS.get(seg.surface, seg.surface))
    slope = _slope_words(seg)
    if slope:
        parts.append(slope)

    # 사람이 그 구간에 적어 둔 말은 **맨 뒤에 그대로** 붙인다. 배점표 낱말로는 담기지
    # 않는 것이 여기 들어간다 — "좌측의 벤치에서 쉬어갈 수 있음", "해충기피제 분사기
    # 존재", 야자매트 같은 노면 보강. 줄이거나 고쳐 쓰지 않는다.
    if seg.note:
        parts.append(seg.note)
    return " · ".join(parts)


def _walk_layers(spot: spots.Spot, base: int = 0) -> list[Walk]:
    """도보 구간을 지도가 받는 모양으로.

    `base` 는 경로 번호를 어디서부터 매길지다. 번호는 **지도 한 장 안에서** 유일해야
    한다 — 여러 곳을 한 장에 그릴 때 각자의 0번 경로가 같은 번호로 들어가면, 서로
    상관없는 두 산길이 한 줄로 이어져 그 사이 허공에 방향 화살표가 생긴다.
    """
    return [
        Walk(
            points=tuple(g.points),
            kind=g.kind,
            note=_segment_note(g),
            route=base + g.route,
            landmark=g.landmark,
        )
        for g in spot.walk_segments
    ]


def _walk_layers_of(chosen: list[spots.Spot]) -> list[Walk]:
    """여러 곳의 도보 구간을 한 장에. 경로 번호가 곳끼리 겹치지 않게 이어 매긴다."""
    out: list[Walk] = []
    for spot in chosen:
        base = out[-1].route + 1 if out else 0
        out.extend(_walk_layers(spot, base))
    return out


def _origin_marker(
    origin: tuple[float, float],
    resolved: dict | None,
    route=None,
    toward: str = "",
) -> Marker:
    """출발지 점 하나. 선은 긋지 않는다 — 점만으로 "얼마나 떨어져 있나"가 보인다.

    거리·시간은 팝업에 적는다. 제주를 가로지르는 선을 그으면 지도가 섬 전체로
    줌아웃되어 정작 봐야 할 도보 경로가 뭉개진다(§2.31).

    `toward` 는 그 시간이 **어디까지**인지다. 여러 곳을 그린 지도에서 그냥 "차로 36분"
    이라고만 적으면 넷 중 어디까지인지 알 수 없다.
    """
    name = (resolved or {}).get("display_name") or "출발지"
    note = ""
    if route is not None:
        where = f"{toward}까지 " if toward else ""
        note = f"여기서 {where}차로 약 {route.minutes:.0f}분 / {route.km:.0f}km"
    return Marker(origin[0], origin[1], "origin", str(name), note)


def _facility_markers(
    spot: spots.Spot,
    placed: dict[str, list[tuple[float, float]]],
) -> list[Marker]:
    """관측지 하나에 딸린 주차·화장실 마커. `placed` 에 찍은 자리를 쌓아 간다.

    검증분(`jeju_spots.json`)이 먼저다 — 사람이 "이 관측지에 쓰는 자리"로 확인한
    것이라 이름·요금이 정확하다. 그다음 반경 안에 있는 것을 얹는다. 검증분은 하나뿐인
    경우가 많은데 옆에 다른 주차장·화장실이 있으면 그것도 선택지이기 때문이다.

    같은 곳인지는 **갈래 안에서만** 따진다. 주차장 20m 옆 화장실은 주차장의 중복이
    아니라 다른 시설이다 — 갈래를 안 가리고 걸렀더니 성판악 주차장에서 500m 안
    화장실 3곳 중 2곳이 지워졌다.

    `placed` 를 밖에서 받는 것은 **여러 곳을 한 장에 그릴 때** 필요해서다. 가까운
    관측지 둘이 같은 화장실을 공유하면 핀이 두 번 찍힌다.
    """
    out: list[Marker] = []

    def _put(marker: Marker) -> None:
        same = placed.setdefault(marker.kind, [])
        if any(_haversine_m(marker.lat, marker.lon, a, b) < 50.0 for a, b in same):
            return
        same.append((marker.lat, marker.lon))
        out.append(marker)

    for lot in spot.parking:
        if lot.get("lat") is None or lot.get("lon") is None:
            continue
        _put(Marker(
            float(lot["lat"]), float(lot["lon"]), "parking",
            lot.get("name", "주차장"), lot.get("fee", ""),
        ))
    for wc in spot.toilet:
        if wc.get("lat") is None or wc.get("lon") is None:
            continue
        _put(Marker(
            float(wc["lat"]), float(wc["lon"]), "toilet", wc.get("name", "화장실"),
        ))
    for extra in _amenity_markers(spot.lat, spot.lon, MAP_NEARBY_M):
        _put(extra)
    return out


def _spot_map(
    spot: spots.Spot,
    route=None,
    origin: tuple[float, float] | None = None,
    origin_resolved: dict | None = None,
) -> str | None:
    """검증된 관측지 한 곳의 지도 — 도보 경로 + 주차·화장실.

    **주행 경로는 그리지 않는다.** 제주를 가로지르는 선이 들어오면 지도가 섬 전체로
    줌아웃되어, 정작 봐야 할 도보 경로와 계단 구간이 점으로 뭉개진다. 주행시간은
    숫자와 문장으로 답하고(`numbers.drive`·설명 줄), 지도는 도착한 다음을 맡는다.
    """
    markers = [Marker(spot.lat, spot.lon, "spot", spot.name, _where(spot))]
    placed = {"spot": [(spot.lat, spot.lon)]}
    markers.extend(_facility_markers(spot, placed))
    if origin is not None:
        markers.append(_origin_marker(origin, origin_resolved, route))

    # 설명 문단을 따로 두지 않는다 — 목록 한 줄의 조각(차 N분·도보 N분·계단…)이
    # 같은 내용을 이미 말한다. 두 번 적으면 패널만 길어진다.
    return maps.write(
        title=f"{spot.name} 도착 이후",
        markers=markers,
        walk_segments=_walk_layers(spot),
        items=[_spot_item(spot, spot.name, route)],
    )


def _place_map(
    lat: float,
    lon: float,
    name: str,
    route=None,
    origin: tuple[float, float] | None = None,
    origin_resolved: dict | None = None,
) -> tuple[str | None, list[Marker]]:
    """등록되지 않은 자리의 지도 — 그 점 + 반경 안 편의시설(+ 출발지면 주행 경로).

    도보 경로는 그리지 않는다. 어디에 세우고 어디로 걷는지는 사람이 확인한 곳에만
    있는 정보라, 없는 선을 그리면 있는 것처럼 보인다.
    """
    amenities = _amenity_markers(lat, lon, NEARBY_M)
    markers = [Marker(lat, lon, "spot", name, "등록되지 않은 지점"), *amenities]
    if origin is not None:
        markers.append(_origin_marker(origin, origin_resolved, route))

    facts = [Fact(f"반경 {NEARBY_M:.0f}m 안 편의시설", "plain")]
    if route is not None:
        facts.insert(0, Fact(f"차 {route.minutes:.0f}분", "drive"))
    facts.append(Fact("등록되지 않은 지점", "warn"))

    return maps.write(
        title=f"{name} 주변",
        markers=markers,
        items=[Item(label=name, lat=lat, lon=lon, sub="등록되지 않은 지점",
                    facts=tuple(facts))],
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

    출발지를 주면 **실제 도로를 따라간 주행시간**으로 자르고 순위에 반영한다
    (직선거리가 아니다 — 제주는 가운데가 한라산이라 직선거리로 자르면 산 반대편을
    추천하게 된다). 정체는 반영하지 않는 야간 자유주행 기준이다.

    인자 설명(외부 LLM 이 읽는 계약)은 `modules/routes.py` 에 있다 — 한 곳에만 둔다.

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
        empty_conditions = _conditions_phrase(
            origin_resolved, max_drive_minutes, region, no_climb,
            max_walk_minutes, parking_required, pets,
            _resolve_plan_when(date, time),
        )
        return Response(
            verdict=_recommend_verdict([], empty_conditions),
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
    when = _resolve_plan_when(date, time)
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
    # 번호를 점 위에 찍는다. 전부 같은 ★ 이면 지도만 보고는 어느 점이 목록 몇 번인지
    # 알 수 없다. 부제도 목록과 같은 말(`_where`)을 써야 둘을 오가며 읽힌다.
    markers = [
        Marker(s.lat, s.lon, "spot", f"{i}. {s.name}", _where(s), glyph=str(i))
        for i, (s, _) in enumerate(top, start=1)
    ]
    # 곳마다 주차·화장실도 함께 찍는다. 눌러서 들여다볼 때 "여기 어디에 세우나"가
    # 바로 보여야 고를 수 있다. `placed` 를 하나로 돌려, 가까운 두 곳이 같은 화장실을
    # 공유해도 핀이 두 번 찍히지 않게 한다.
    placed = {"spot": [(s.lat, s.lon) for s, _ in top]}
    for s, _ in top:
        markers.extend(_facility_markers(s, placed))
    if origin_resolved is not None:
        o = (float(origin_resolved["lat"]), float(origin_resolved["lon"]))
        markers.append(_origin_marker(
            o, origin_resolved, routes.get(top[0][0].name), toward="1번"
        ))
    items = [
        _spot_item(s, f"{i}. {s.name}", routes.get(s.name))
        for i, (s, _) in enumerate(top, start=1)
    ]
    conditions = _conditions_phrase(
        origin_resolved, max_drive_minutes, region, no_climb,
        max_walk_minutes, parking_required, pets, when,
    )
    map_url = maps.write(
        title=f"관측지 추천 {len(rows)}곳",
        markers=markers,
        walk_segments=_walk_layers_of([s for s, _ in top]),
        items=items,
    )

    reasons = _recommend_reasons(top, routes, show_pets=pets)
    if map_url:
        reasons.append(f"지도(고른 곳 전부): {map_url}")
    reasons.append(_forecast_caveat(when))

    return Response(
        verdict=_recommend_verdict(rows, conditions),
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


def _conditions_phrase(
    origin_resolved: dict | None,
    max_drive_minutes: float | None,
    region: str | None,
    no_climb: bool,
    max_walk_minutes: float | None,
    parking_required: bool,
    pets: bool,
    when: datetime,
) -> str:
    """사용자가 건 조건을 사람이 읽는 한 줄로. 조건이 없으면 시각만.

    무엇으로 골랐는지를 결과와 함께 보여 준다 — 조건을 안 적으면 왜 이 네 곳인지
    알 수 없고, 조건을 잘못 넘겼을 때(지역을 잘못 읽었다든지) 그것도 드러나지 않는다.
    """
    parts: list[str] = []
    if origin_resolved:
        where = origin_resolved.get("matched_query") or origin_resolved.get("query")
        if where:
            parts.append(f"{where} 출발")
    if max_drive_minutes is not None:
        parts.append(f"차로 {max_drive_minutes:.0f}분 이내")
    if region:
        # 중산간은 방위가 아니라 높이라 '중산간쪽'이 되면 이상하다.
        parts.append("중산간" if region == "중산간" else f"{region}쪽 지역")
    if no_climb:
        parts.append("등산 없는 곳")
    if max_walk_minutes is not None:
        if max_walk_minutes < 1:
            parts.append("주차 후 바로 관측")
        else:
            parts.append(f"도보 {max_walk_minutes:.0f}분 이내")
    if parking_required:
        parts.append("주차 가능한 곳")
    if pets:
        parts.append("반려동물 동반 가능")

    label = _night_label(when)
    parts.append(f"{label} {when:%H시} 기준")
    return " · ".join(parts)


def _recommend_verdict(rows: list[dict], conditions: str) -> str:
    """추천 결과의 한 줄 결론 — **조건이 먼저, 결과가 뒤**다.

    한때 "'따라비오름'을 추천해요 (차로 약 48분)" 처럼 1등을 앞세웠는데, 목록이 이미
    순서대로 있어서 같은 말을 두 번 하는 셈이었다. 대신 무엇으로 골랐는지를 적는다.
    """
    if not rows:
        return f"{conditions} — 조건에 맞는 관측지를 찾지 못했어요"
    return f"{conditions} — 조건에 맞는 관측지 {len(rows)}곳을 추천드립니다"


def _recommend_reasons(judged: list, routes: dict, show_pets: bool = False) -> list[str]:
    """추천 목록을 사람이 읽는 줄들로. 곳마다 왜 골랐는지 한 덩어리씩.

    **수치를 이 문장들 안에 넣는다.** 구름·등급은 `spots[]` 에도 실리지만, 이 응답을
    읽는 쪽이 작은 모델일 때 구조화 배열은 잘 안 읽히고 산문만 읽힌다. 실제로
    측정에서 모델이 곳 이름만 옮기고 숫자는 전부 흘렸다 — 숫자가 문장 안에 있어야
    인용된다. `spots[]` 는 그대로 두므로 프로그램이 읽는 쪽은 달라지지 않는다.

    `why` 는 판정 줄에서 떼어 뒤로 뺐다. 한 줄에 등급·구름·이유가 같이 있으면 이유가
    길어 숫자가 문장 끝으로 밀린다.

    `show_pets` — 반려동물 조건으로 걸러 달라고 했을 때만 각 곳의 `pets` 원문을 함께
    싣는다. 거르기는 파생 축(`spots.pets_allowed`)이 하지만, 답에는 원문이 실려야
    사용자가 "목줄 필수" 같은 단서를 볼 수 있다. 조건으로 안 물었을 때까지 붙이면
    줄만 길어지므로 물었을 때만 붙인다.
    """
    lines: list[str] = []
    for i, (s, final) in enumerate(judged, start=1):
        leg = routes.get(s.name)
        nums = final.get("numbers", {})
        # 곳마다의 수치를 **이름 줄에 붙인다.** 아래 별도 줄에 두었더니 모델이 세 곳을
        # "모두 구름이 적고 밤하늘이 어둡며" 로 뭉개고 숫자를 통째로 흘렸다(R-02·03·
        # 05·07). 이름은 언제나 옮겨지므로, 숫자를 이름에 붙이면 같이 딸려 온다.
        bits = []
        if leg is not None:
            bits.append(f"차로 약 {leg.minutes:.0f}분 / {leg.km:.0f}km")
        cloud = nums.get("cloud_cover")
        if cloud is not None:
            bits.append(f"구름 {cloud:.0f}%")
        bortle = nums.get("bortle")
        if bortle is not None:
            bits.append(f"어둡기 {bortle}단계")
        bits.append(f"판정 {final.get('verdict') or '불가'}")
        lines.append(f"{i}. {s.name} ({s.region}·{s.kind}) — " + " · ".join(bits))

        lines.append("   " + _walk_phrase(s))
        if show_pets and s.pets:
            lines.append(f"   반려동물: {s.pets}")
        if s.night_access:
            lines.append(f"   야간 출입: {s.night_access}")
        if s.why:
            lines.append(f"   고른 이유: {s.why}")
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

    인자 설명(외부 LLM 이 읽는 계약)은 `modules/routes.py` 에 있다 — 한 곳에만 둔다.

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
    origin_pt: tuple[float, float] | None = None
    origin_resolved: dict | None = None
    if origin or (origin_lat is not None and origin_lon is not None):
        o = _locate(origin, origin_lat, origin_lon)
        if o is not None and _in_jeju(o[0], o[1]):
            origin_pt = (o[0], o[1])
            origin_resolved = o[2]
            target = known.drive_target() if known is not None else (p_lat, p_lon)
            route = routing.drive_time(origin_pt, target)

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
        result["map_url"] = _spot_map(known, route, origin_pt, origin_resolved)
        amenities = []
    else:
        label = (resolved or {}).get("display_name") or (query or "이 지점")
        result["map_url"], amenities = _place_map(
            p_lat, p_lon, str(label), route, origin_pt, origin_resolved
        )
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
    else:
        reasons.append(_amenity_reason(amenities, NEARBY_M))
        if route is not None:
            reasons.append(
                "다만 이 위치는 검증된 관측지 목록에 없어요. 하늘 상태(날씨·광공해·"
                "박명)와 위 주행시간은 좌표만으로 계산되지만, **주차 가능 여부·야간 "
                "출입·진입로 상태·도보 난이도는 확인되지 않았습니다.**"
            )
        else:
            reasons.append(
                "이 위치는 검증된 관측지 목록에 없어요. 하늘 상태(날씨·둘레 불빛·어둡기)는 "
                "위와 같이 판정했지만 **주차 가능 여부·야간 출입·진입로 상태·도보 "
                "난이도는 확인되지 않았습니다.**"
            )

        # 답하지 못한 접근성을, 답할 수 있는 곳으로 메운다. 어두운 곳이 근처에
        # 없으면 아무 말도 하지 않는다 — 없는 대안을 지어내는 것보다 낫다.
        alternatives = _darker_nearby(
            p_lat, p_lon, result.get("numbers", {}).get("darkness_score")
        )
        if alternatives:
            reasons.append(_alternatives_reason(alternatives))
            attr = result.setdefault("attribution", [])
            for source in (spots.source(), routing.SOURCE):
                if source not in attr:
                    attr.append(source)
        else:
            reasons.append(
                "초행에 밤에 가신다면 검증된 관측지 중에서 고르시는 편이 안전해요"
            )

    if result.get("map_url"):
        reasons.append(f"지도(경로와 주변): {result['map_url']}")

    return result


def _nearest_known(lat: float, lon: float) -> spots.Spot | None:
    """좌표가 등록된 관측지 바로 옆인지 본다. 아니면 None."""
    best, best_m = None, _SAME_SPOT_M
    for s in spots.all_spots():
        d = _haversine_m(lat, lon, s.lat, s.lon)
        if d <= best_m:
            best, best_m = s, d
    return best


def _darker_nearby(
    lat: float, lon: float, here_score: float | None
) -> list[tuple[spots.Spot, routing.Route, float | None]]:
    """미등록 지점 근처에서 **여기보다 어두운** 검증된 관측지 몇 곳.

    미등록 장소에서 답하지 못하는 것은 접근성 하나뿐이고(하늘 상태는 좌표만으로
    계산된다), 근처의 검증된 관측지는 바로 그 접근성을 갖고 있다. 그래서 못 답한
    자리에 답할 수 있는 곳을 놓는다.

    거리는 `routing.drive_times` 로 잰다 — 직선거리로 자르면 한라산 반대편이 가깝게
    나온다. 63곳 전부를 재도 다익스트라는 **한 번**이라 비용은 한 건과 같다.

    `here_score` 보다 **엄격히** 낮은 곳만 남긴다(점수는 낮을수록 어둡다). 같거나
    높은 곳을 끼워 넣으면 "여기보다 어둡다"가 거짓이 되고, 밝은 곳으로 사람을
    보내게 된다. 기준값이 없으면(광공해 격자 밖) 비교할 수 없으므로 아무 말도
    하지 않는다.

    Returns:
        (관측지, 주행, SQM) 을 **어두운 순**으로 최대 `_ALT_MAX` 개. 가까운 순이
        아닌 것은, 이미 반경 안으로 자른 뒤라 남은 축이 어둡기뿐이어서다.
    """
    if here_score is None:
        return []

    candidates = spots.all_spots()
    legs = routing.drive_times(
        (lat, lon),
        [s.drive_target() for s in candidates],
        budget_minutes=_ALT_DRIVE_MINUTES,
    )

    rows = []
    for spot, leg in zip(candidates, legs, strict=True):
        if leg is None:
            continue
        site = darkness.assess_site(spot.lat, spot.lon)
        if site.score is None or site.score >= here_score:
            continue
        sqm = site.darkness.sqm if site.darkness is not None else None
        rows.append((site.score, spot, leg, sqm))

    rows.sort(key=lambda r: r[0])
    return [(spot, leg, sqm) for _, spot, leg, sqm in rows[:_ALT_MAX]]


def _alternatives_reason(
    rows: list[tuple[spots.Spot, routing.Route, float | None]],
) -> str:
    """근처 대안을 한 줄로. 이름·주행시간·어둡기·야간 출입만 — 도보 난이도까지
    적으면 `spot_details` 를 옮겨 온 것이 된다."""
    parts = []
    for spot, leg, sqm in rows:
        bits = [f"차로 약 {leg.minutes:.0f}분"]
        if sqm is not None:
            bits.append(f"하늘 밝기 {sqm:.2f} (클수록 어두움)")
        bits.append(f"야간 출입 {spot.night_access or '확인 필요'}")
        parts.append(f"{spot.name}({' · '.join(bits)})")
    return (
        "대신 근처에 **이 지점보다 어둡고 접근성이 확인된** 관측지가 있어요 — "
        + ", ".join(parts)
        + ". 자세한 접근성은 그 이름으로 물어보시면 됩니다"
    )


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

    인자 설명(외부 LLM 이 읽는 계약)은 `modules/routes.py` 에 있다 — 한 곳에만 둔다.

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
    origin_pt: tuple[float, float] | None = None
    origin_resolved = None
    if origin or (origin_lat is not None and origin_lon is not None):
        found = _locate(origin, origin_lat, origin_lon)
        if found is not None:
            o_lat, o_lon, origin_resolved = found
            if _in_jeju(o_lat, o_lon):
                origin_pt = (o_lat, o_lon)
                route = routing.drive_time(origin_pt, hit.drive_target())
                attribution.append(routing.SOURCE)
            else:
                # 제주 밖 출발지는 주행을 답하지 않으므로 지도에도 싣지 않는다.
                origin_resolved = None

    row = _spot_row(hit, detail=True, route=route)
    map_url = _spot_map(hit, route, origin_pt, origin_resolved)

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
        reasons.append(f"지도(주차 자리와 걷는 길): {map_url}")

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
