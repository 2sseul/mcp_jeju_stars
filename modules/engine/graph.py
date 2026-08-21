"""엔진 — astro → weather → judge → darkness 를 LangGraph StateGraph 로 잇는다.

축을 '하나씩' 추가하며 확장한다 — 그때도 이 파일의 그래프 조립과 state 계약은
안 바뀐다(엣지·노드만 늘어남). 어둡기(광공해) 축이 darkness_node 로 그렇게 붙었다.
별 개수 축은 이후 단계.

계산 모듈은 `modules/core`(순수함수) · 네트워크는 `modules/clients` 로 나뉜다.
core 는 API·LLM 을 호출하지 않고, 이 파일이 둘을 조립한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from langgraph.graph import END, START, StateGraph

from modules.clients import open_meteo
from modules.core import astro
from modules.core import darkness as _darkness
from modules.core import judge as _judge
from modules.core import lamps as _lamps
from modules.core import nightlight as _nightlight
from modules.core import tonight as _tonight

from .state import EngineState

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
    """상태·총운량·시정 → 관측 등급(운영 정책). 광공해 상한을 함께 받는다.

    darkness_node 가 먼저 돌아야 상한이 채워진다(그래서 엣지가 darkness → judge 다).
    """
    result = _judge.judge(
        state.get("state_code"),
        state.get("cloud"),
        state.get("visibility"),
        state.get("darkness_cap"),
    )
    return {
        "verdict": result.verdict,
        "possible": result.possible,
        "reasons": list(result.reasons),
    }


def _darkness_numbers(site) -> dict | None:
    """Site(어둡기 종합) → numbers 조각(순간·밤 경로 공유). SQM 결측이면 None.

    세 신호를 평탄한 키로 편다 — 소비자(LLM)가 보는 키 모양을 한 겹으로 유지한다.
    """
    d = site.darkness
    if d is None:
        return None
    nums = {
        "sqm": d.sqm,
        "falchi_grade": d.falchi_grade,
        # 학술 라벨("하늘의 자연스러운 외관 상실")이 아니라 쉬운 말을 싣는다 —
        # 이 값을 읽는 것이 사람 아니면 작은 모델이고, 실제로 모델이 이 문자열을
        # 그대로 답에 옮겨 썼다(E-05). 등급 문자(i~vi)는 falchi_grade 에 그대로 있다.
        "falchi_label": _darkness.plain_label(d.falchi_grade),
        "bortle": d.bortle,
        "artificial_mcd": d.artificial_mcd,
        "light_pollution_ratio": d.ratio,
        "milky_way": d.milky_way,
        "darkness_score": site.score,
        "darkness_cap": site.cap,
        "lamp_nearest_m": site.lamps.nearest_m,
        "lamp_within_100m": site.lamps.near,
        "lamp_within_500m": site.lamps.mid,
        "lamp_within_1km": site.lamps.far,
    }
    if site.nightlight is not None:
        nums["viirs_near_max"] = site.nightlight.near_max
        nums["viirs_wide_max"] = site.nightlight.wide_max
    return nums


#: 어둡기 축이 쓰는 세 데이터의 귀속. 세 신호를 다 쓰므로 셋을 함께 싣는다.
_DARKNESS_SOURCES = [_darkness.SOURCE, _nightlight.SOURCE, _lamps.SOURCE]


def darkness_node(state: EngineState) -> dict:
    """광공해(어둡기) → 장소의 고정 속성. SQM·VIIRS·가로등 셋을 모아 점수·상한까지.

    정적 속성이라 시각과 무관하다. 여기서 낸 상한(cap)을 judge 가 받아 등급을
    끌어내린다 — 그래서 이 노드가 judge 보다 **먼저** 돈다.
    """
    site = _darkness.assess_site(state["lat"], state["lon"])
    nums = _darkness_numbers(site)
    if nums is None:
        # SQM(주 기준)이 없으면 점수를 내지 않는다. 응답 '모양'은 같게 유지한다.
        return {
            "numbers": {"darkness": None},
            "reasons": ["이 지점은 광공해 격자 밖이거나 데이터가 없어요(해상 등)"],
            "attribution": _DARKNESS_SOURCES,
        }
    return {
        "darkness_cap": site.cap,
        "numbers": nums,
        "reasons": _darkness.describe_site(site),
        "attribution": _DARKNESS_SOURCES,
    }


# --- 그래프 조립 --------------------------------------------------------------

def _build():
    g = StateGraph(EngineState)
    g.add_node("astro", astro_node)
    g.add_node("weather", weather_node)
    g.add_node("judge", judge_node)
    g.add_node("darkness", darkness_node)
    # 어둡기가 judge 보다 앞이다 — judge 가 그 상한(cap)을 받아 등급을 정하기 때문.
    g.add_edge(START, "astro")
    g.add_edge("astro", "weather")
    g.add_edge("weather", "darkness")
    g.add_edge("darkness", "judge")
    g.add_edge("judge", END)
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
         "darkness_reasons": [str, ...],
         "milky_way_caveat": str | None,
         "attribution": [...]}
        완전한 밤이 없거나(백야 등) 조회 실패면 summary 는 None. 광공해(darkness)는
        장소의 정적 속성이라 밤/조회 성패와 무관하게 항상 채운다(격자 밖이면 None).
    """
    attribution = ["천체력: JPL DE421 via Skyfield"]

    # 광공해는 정적(장소 속성)이라 밤 구간·조회와 독립. 한 번 구해 모든 반환에 싣는다.
    site = _darkness.assess_site(lat, lon)
    darkness = _darkness_numbers(site)
    if site.darkness is not None:
        caveat = _darkness.milky_way_caveat(site.darkness)
        darkness_reasons = _darkness.describe_site(site)
        attribution.extend(_DARKNESS_SOURCES)
    else:
        caveat = None
        darkness_reasons = ["이 지점은 광공해 격자 밖이거나 데이터가 없어요(해상 등)"]

    def _result(window, summary, extra_attr=None) -> dict:
        return {
            "window": window,
            "summary": summary,
            "darkness": darkness,
            "darkness_reasons": darkness_reasons,
            "milky_way_caveat": caveat,
            "attribution": attribution + (extra_attr or []),
        }

    window = astro.night_window(lat, lon, when)
    if window is None:
        return _result(None, None)
    start, end = window

    # 외부 I/O 는 실패해도 스키마를 깨지 않는다(순간 그래프의 weather_node 와 같은 규율).
    # 밤 창의 시작·끝은 대개 정시가 아니다(예: 20:03~05:15). fetch_series 는 구간을
    # 정시로 내림하므로 그대로 쓰면 ① 창 앞 정시(20:00)가 딸려 들어오고 ② 창 안의
    # 마지막 정시(05:00)가 빠진다. 끝을 한 시간 넉넉히 받아 두고, 창 안에 실제로
    # 들어오는 정시만 아래에서 걸러낸다(decisions.md §2.8).
    try:
        series = open_meteo.fetch_series(lat, lon, start, end + timedelta(hours=1))
        attribution.append("기상: Open-Meteo (open-meteo.com)")
    except Exception:  # noqa: BLE001 — 외부 I/O 경계, 스키마 보장이 우선
        return _result(_iso_window(start, end), None, ["기상: Open-Meteo (조회 실패)"])

    hours = []
    for row in series:
        t = row["time"]
        if t < start or t >= end:  # 밤 창 밖 정시는 집계에서 제외
            continue
        state = astro.twilight_state(lat, lon, t)
        # 밤 집계의 매 정시도 순간 판정과 같은 광공해 상한을 받는다(같은 장소이므로).
        result = _judge.judge(state, row["cloud_cover"], row["visibility"], site.cap)
        hours.append(
            _tonight.HourResult(t, result.verdict, result.possible, row["cloud_cover"])
        )

    return _result(_iso_window(start, end), _tonight.summarize(hours))


def _iso_window(start: datetime, end: datetime) -> dict:
    return {
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
    }
