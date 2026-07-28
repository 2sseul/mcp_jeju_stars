"""P0 엔진 — astro → weather → judge → darkness 를 LangGraph StateGraph 로 잇는다.

각 노드는 계획서의 provider/factor 역할을 한다. 축을 '하나씩' 추가하며 확장한다 —
그때도 이 파일의 그래프 조립과 state 계약은 안 바뀐다(엣지·노드만 늘어남). P1 어둡기
(광공해) 축을 darkness_node 로 붙였다. 별 개수 등은 이후 단계.

계산 모듈(data/script/{astro,judge,open_meteo,darkness})은 아직 PR 검토 중이라 옮기지
않고 import 만 한다. P1/P2 에서 server/providers·factors 로 정식 이관 예정.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from .state import EngineState

# --- 계산 모듈 import 브리지 (임시) -------------------------------------------
# data/script 를 패키지로 만들지 않고 경로만 추가해 그대로 재사용한다.
_CALC = Path(__file__).resolve().parents[2] / "data" / "script"
if str(_CALC) not in sys.path:
    sys.path.insert(0, str(_CALC))

from server.core import astro
from server.core import darkness
from server.core import judge
from server.clients import open_meteo  # noqa: E402
from server.core import tonight


# --- 노드 --------------------------------------------------------------------

def astro_node(state: EngineState) -> dict:
    """태양 고도 → 박명 구간·완전한 밤 구간(천문학적 사실). 판정은 judge 소관.

    사람이 읽는 문장은 만들지 않는다 — 숫자만 numbers 에 담고, 등급·설명은
    judge 가 정한다(관심사 분리).
    """
    lat, lon, when = state["lat"], state["lon"], state["when"]
    code = astro.twilight_state(lat, lon, when)
    numbers: dict = {"twilight_state": code}

    window = astro.dark_window(lat, lon, when)
    if window is not None:
        start, end = window
        numbers["dark_window"] = {
            "start": start.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
        }

    return {
        "state_code": code,
        "numbers": numbers,
        "attribution": ["천체력: JPL DE421 via Skyfield"],
    }


def weather_node(state: EngineState) -> dict:
    """Open-Meteo → 해당 정시의 총운량·시정.

    외부 조회는 실패 가능한 경로다(타임아웃·429·예보 범위 밖 날짜 등). 예외가
    나도 '항상 고정 스키마 반환' 약속을 깨지 않도록 여기서 잡아 값을 None
    으로 흘려보낸다 — judge 가 None 을 '데이터 없음'으로 처리해 관측 불가 사유로
    환원한다. 즉 이 노드는 절대 예외를 밖으로 내보내지 않는다.
    """
    try:
        data = open_meteo.fetch(state["lat"], state["lon"], state["when"])
    except Exception:  # noqa: BLE001 — 외부 I/O 경계, 스키마 보장이 우선
        # 값을 None 으로 흘리면 judge 가 "정보를 가져오지 못했어요"로 환원한다.
        return {
            "cloud": None,
            "visibility": None,
            "numbers": {
                "cloud_cover": None,
                "visibility_m": None,
            },
            "attribution": ["기상: Open-Meteo (조회 실패)"],
        }

    cloud = data["cloud_cover"]
    vis = data["visibility"]
    numbers: dict = {
        "cloud_cover": cloud,
        "visibility_m": vis,
    }
    return {
        "cloud": cloud,
        "visibility": vis,
        "numbers": numbers,
        "attribution": ["기상: Open-Meteo (open-meteo.com)"],
    }


def judge_node(state: EngineState) -> dict:
    """상태·총운량·시정 → 관측 등급(운영 정책)."""
    result = _judge.judge(
        state.get("state_code"),
        state.get("cloud"),
        state.get("visibility"),
    )
    return {
        "verdict": result.verdict,
        "possible": result.possible,
        "reasons": list(result.reasons),
    }


def _darkness_numbers(d) -> dict | None:
    """Darkness 판정 → numbers 조각(순간·밤 경로 공유). 결측이면 None."""
    if d is None:
        return None
    return {
        "sqm": d.sqm,
        "falchi_grade": d.falchi_grade,
        "falchi_label": d.falchi_label,
        "bortle": d.bortle,
        "artificial_mcd": d.artificial_mcd,
        "light_pollution_ratio": d.ratio,
        "milky_way": d.milky_way,
    }


def darkness_node(state: EngineState) -> dict:
    """광공해(어둡기) → 장소의 고정 속성(SQM·Falchi·Bortle). 정적이라 시각과 무관.

    verdict 등급은 바꾸지 않는다(어둡기 판정 편입은 이후 단계) — 수치를 numbers 에
    담고 사람이 읽는 한 줄을 reasons 에 더한다. '은하수까지'라는 판정 문구의 정정은
    run() 이 milky_way 로 처리한다(judge 는 장소를 모르는 순수 함수로 유지).
    """
    d = _darkness.assess(state["lat"], state["lon"])
    nums = _darkness_numbers(d)
    if nums is None:
        return {
            "numbers": {"darkness": None},
            "reasons": ["이 지점은 광공해 격자 밖이거나 데이터가 없어요(해상 등)"],
            "attribution": [_darkness.SOURCE],
        }
    return {
        "numbers": nums,
        "reasons": [_darkness.describe(d)],
        "attribution": [_darkness.SOURCE],
    }


# --- 그래프 조립 --------------------------------------------------------------

def _build():
    g = StateGraph(EngineState)
    g.add_node("astro", astro_node)
    g.add_node("weather", weather_node)
    g.add_node("judge", judge_node)
    g.add_node("darkness", darkness_node)
    g.add_edge(START, "astro")
    g.add_edge("astro", "weather")
    g.add_edge("weather", "judge")
    g.add_edge("judge", "darkness")
    g.add_edge("darkness", END)
    return g.compile()


_GRAPH = _build()


def _apply_milky_way_correction(state: EngineState) -> None:
    """광공해에 맞춰 '은하수까지 보인다'는 판정 문구를 정정한다(등급은 안 바꿈).

    완전한 밤(상태 0) 최적 판정만 은하수·성운 서술을 담으므로, 그 문구를 이 장소의
    milky_way(가시성)에 맞춘 완결형 문구로 통째 교체한다. 어둡기 데이터가 없거나
    은하수가 여전히 보이는(visible) 곳이면 건드리지 않는다.
    """
    nums = state.get("numbers", {})
    mw = nums.get("milky_way")
    if not mw or mw == "visible":
        return
    phrase = _darkness.milky_way_phrase_from(mw, nums.get("falchi_grade", ""))
    if not phrase:
        return
    reasons = state.get("reasons", [])
    for i, r in enumerate(reasons):
        if "은하수" in r and "볼 수 있어요" in r:  # judge 의 상태0 은하수 서술
            reasons[i] = phrase
            return


def run(lat: float, lon: float, when: datetime) -> EngineState:
    """엔진 1회 실행("지금 별 보이나?"). 누적된 최종 state 를 반환한다."""
    init: EngineState = {
        "lat": lat,
        "lon": lon,
        "when": when,
        "numbers": {},
        "reasons": [],
        "attribution": [],
    }
    final = _GRAPH.invoke(init)
    _apply_milky_way_correction(final)
    return final


# --- 밤 단위 집계 ("오늘 밤 볼 수 있나?") -------------------------------------

def run_tonight(lat: float, lon: float, when: datetime) -> dict:
    """when 이 속한(또는 이후 도래하는) '박명 포함 밤'을 시간별로 판정해 집계한다.

    순간 판정 그래프(run)와 달리 밤 구간(astro.night_window)의 각 정시를 judge 로
    판정한 뒤 tonight.summarize 로 모은다. 3시간 기준으로 가능/불가를 매기지 않고
    관측 가능 시간 수·등급 분포·연속 창을 그대로 돌려준다.

    Returns:
        {"window": {"start": iso, "end": iso} | None,
         "summary": <tonight.summarize dict> | None,
         "darkness": <_darkness_numbers dict> | None,
         "milky_way_caveat": str | None,
         "attribution": [...]}
        완전한 밤이 없거나(백야 등) 조회 실패면 summary 는 None. 광공해(darkness)는
        장소의 정적 속성이라 밤/조회 성패와 무관하게 항상 채운다(격자 밖이면 None).
    """
    attribution = ["천체력: JPL DE421 via Skyfield"]

    # 광공해는 정적(장소 속성)이라 밤 구간·조회와 독립. 한 번 구해 모든 반환에 싣는다.
    d = _darkness.assess(lat, lon)
    darkness = _darkness_numbers(d)
    if d is not None:
        caveat = _darkness.milky_way_caveat(d)
        darkness_reason = _darkness.describe(d)
        attribution.append(_darkness.SOURCE)
    else:
        caveat = None
        darkness_reason = "이 지점은 광공해 격자 밖이거나 데이터가 없어요(해상 등)"

    def _result(window, summary, extra_attr=None) -> dict:
        return {
            "window": window,
            "summary": summary,
            "darkness": darkness,
            "darkness_reason": darkness_reason,
            "milky_way_caveat": caveat,
            "attribution": attribution + (extra_attr or []),
        }

    window = astro.night_window(lat, lon, when)
    if window is None:
        return _result(None, None)
    start, end = window

    # 외부 I/O 는 실패해도 스키마를 깨지 않는다(순간 그래프의 weather_node 와 같은 규율).
    try:
        series = open_meteo.fetch_series(lat, lon, start, end)
        attribution.append("기상: Open-Meteo (open-meteo.com)")
    except Exception:  # noqa: BLE001 — 외부 I/O 경계, 스키마 보장이 우선
        return _result(_iso_window(start, end), None, ["기상: Open-Meteo (조회 실패)"])

    hours = []
    for row in series:
        t = row["time"]
        state = astro.twilight_state(lat, lon, t)
        result = _judge.judge(state, row["cloud_cover"], row["visibility"])
        hours.append(
            _tonight.HourResult(t, result.verdict, result.possible, row["cloud_cover"])
        )

    return _result(_iso_window(start, end), _tonight.summarize(hours))


def _iso_window(start: datetime, end: datetime) -> dict:
    return {
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
    }
