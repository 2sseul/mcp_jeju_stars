"""엔진 — astro → weather → darkness → moon → judge 를 LangGraph StateGraph 로 잇는다.

축을 '하나씩' 추가하며 확장한다 — 그때도 이 파일의 그래프 조립과 state 계약은
안 바뀐다(엣지·노드만 늘어남). 어둡기(광공해) 축이 darkness_node 로, 달빛 축이
moon_node 로 그렇게 붙었다.

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
from modules.core import moon as _moon
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
    """상태·총운량·시정 → 관측 등급(운영 정책). 광공해·달빛 상한을 함께 받는다.

    darkness_node·moon_node 가 먼저 돌아야 상한이 채워진다(그래서 엣지가
    darkness → moon → judge 다).
    """
    result = _judge.judge(
        state.get("state_code"),
        state.get("cloud"),
        state.get("visibility"),
        state.get("darkness_cap"),
        state.get("moon_cap"),
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
        # `darkness_cap` 은 응답에 싣지 않는다. 광공해만 봤을 때의 등급 **상한**이라
        # 최종 판정이 아닌데 값이 "최적"·"양호" 같은 판정 낱말이다. 응답 안에 판정처럼
        # 보이는 값이 둘이 되자 작은 모델이 엉뚱한 쪽을 집었다 — 도구는 "양호"라고
        # 했는데 답은 "판정은 '최적'"이라고 썼다(E-01). 그래프 상태에는 그대로 두므로
        # judge 는 계속 이 값을 받는다(아래 darkness_node 반환값).
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
            "site": None,
            "numbers": {"darkness": None},
            "reasons": ["이 지점은 광공해 격자 밖이거나 데이터가 없어요(해상 등)"],
            "attribution": _DARKNESS_SOURCES,
        }
    return {
        # site 를 상태에 남긴다 — moon_node 가 이 위에 달빛을 얹어야 하고, 격자 조회를
        # 두 번 하지 않는다.
        "site": site,
        "darkness_cap": site.cap,
        "numbers": nums,
        "reasons": _darkness.describe_site(site),
        "attribution": _DARKNESS_SOURCES,
    }


def _moon_numbers(m: _moon.Moon) -> dict:
    """Moon → numbers 조각. 어둡기와 같이 평탄한 키로 편다(순간 경로)."""
    return {
        "moon_altitude_deg": m.altitude_deg,
        "moon_azimuth_deg": m.azimuth_deg,
        "moon_illumination": m.illumination,
        "moon_phase_angle_deg": m.phase_angle_deg,
        "moon_added_mcd": m.added_mcd,
    }


def moon_node(state: EngineState) -> dict:
    """달빛 → 그 시각 하늘에 더해지는 밝기. 광공해 위에 얹어 등급 상한을 다시 낸다.

    광공해(정적)와 달리 **시각의 속성**이다. darkness_node 가 낸 Site 위에 달빛을
    더해(`darkness.assess_sky`) 상한을 다시 매기고, 그 상한을 judge 가 받는다 —
    그래서 이 노드가 darkness 뒤·judge 앞이다.

    어둡기 격자 밖이면 얹을 바탕이 없으므로 상한을 내지 않는다(숫자와 문구만 낸다).
    """
    m = _moon.assess(state["lat"], state["lon"], state["when"])
    nums = _moon_numbers(m)

    site = state.get("site")
    sky = _darkness.assess_sky(site, m.added_mcd) if site is not None else None
    if sky is None:
        return {"numbers": nums, "reasons": [_moon.describe(m)]}

    nums["sky_sqm"] = sky.sqm
    return {
        "moon_cap": sky.cap,
        # 은하수를 가린 것이 달인지 둘레 불빛인지 — 처방이 달라 문구가 갈린다
        # (`_apply_milky_way_correction`). added_mcd 는 0 이상이라 가시성은 같거나
        # 나빠지기만 하므로, 달라졌다면 달이 깎은 것이다.
        "moon_dimmed_mw": sky.milky_way != site.darkness.milky_way,
        # 달빛을 더한 뒤의 은하수 가시성으로 덮어쓴다 — 정적 값(darkness_node 가 넣은
        # milky_way)은 달이 없는 하늘의 값이라 그대로 두면 보름달 밤에 틀린다.
        "numbers": {**nums, "milky_way": sky.milky_way},
        "reasons": [_moon.describe(m)],
    }


# --- 그래프 조립 --------------------------------------------------------------

def _build():
    g = StateGraph(EngineState)
    g.add_node("astro", astro_node)
    g.add_node("weather", weather_node)
    g.add_node("judge", judge_node)
    g.add_node("darkness", darkness_node)
    g.add_node("moon", moon_node)
    # 어둡기·달빛이 judge 보다 앞이다 — judge 가 그 상한(cap)들을 받아 등급을 정하기
    # 때문. 달빛은 어둡기 위에 얹으므로 darkness 뒤다.
    g.add_edge(START, "astro")
    g.add_edge("astro", "weather")
    g.add_edge("weather", "darkness")
    g.add_edge("darkness", "moon")
    g.add_edge("moon", "judge")
    g.add_edge("judge", END)
    return g.compile()


_GRAPH = _build()


def _apply_milky_way_correction(state: EngineState) -> None:
    """광공해·달빛에 맞춰 '은하수까지 보인다'는 판정 문구를 정정한다(등급은 안 바꿈).

    완전한 밤(상태 0) 최적 판정만 은하수·성운 서술을 담으므로, 그 문구를 이 하늘의
    milky_way(가시성)에 맞춘 완결형 문구로 통째 교체한다. 어둡기 데이터가 없거나
    은하수가 여전히 보이는(visible) 곳이면 건드리지 않는다.

    **가린 것이 달이면 달 문구를 쓴다** — 처방이 다르다(자리를 옮겨라 ↔ 때를 옮겨라).
    """
    nums = state.get("numbers", {})
    mw = nums.get("milky_way")
    if not mw or mw == "visible":
        return
    if state.get("moon_dimmed_mw"):
        phrase = _moon.milky_way_phrase(mw)
    else:
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
         "moon": <_moon_night 요약 dict> | None,
         "moon_caveat": str | None,
         "attribution": [...]}
        완전한 밤이 없거나(백야 등) 조회 실패면 summary 는 None. 광공해(darkness)는
        장소의 정적 속성이라 밤/조회 성패와 무관하게 항상 채운다(격자 밖이면 None).
        달(moon)은 밤 구간이 정해져야 재므로 window 가 None 이면 함께 None 이지만,
        기상 조회 실패와는 무관하다(성표만 있으면 계산된다).
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

    def _result(window, summary, moon=None, moon_caveat=None, extra_attr=None) -> dict:
        return {
            "window": window,
            "summary": summary,
            "darkness": darkness,
            "darkness_reasons": darkness_reasons,
            "milky_way_caveat": caveat,
            "moon": moon,
            "moon_caveat": moon_caveat,
            "attribution": attribution + (extra_attr or []),
        }

    window = astro.night_window(lat, lon, when)
    if window is None:
        return _result(None, None)
    start, end = window

    # 달은 성표만 있으면 계산되므로 기상 조회보다 앞에서 구한다 — 구름을 못 받아도
    # "오늘 밤 달이 방해가 되나"는 답할 수 있다.
    moon_hours = _moon_hours(lat, lon, start, end)
    moon_night, moon_caveat, moon_caps = _moon_night(
        lat, lon, start, end, moon_hours, site
    )

    # 외부 I/O 는 실패해도 스키마를 깨지 않는다(순간 그래프의 weather_node 와 같은 규율).
    # 밤 창의 시작·끝은 대개 정시가 아니다(예: 20:03~05:15). fetch_series 는 구간을
    # 정시로 내림하므로 그대로 쓰면 ① 창 앞 정시(20:00)가 딸려 들어오고 ② 창 안의
    # 마지막 정시(05:00)가 빠진다. 끝을 한 시간 넉넉히 받아 두고, 창 안에 실제로
    # 들어오는 정시만 아래에서 걸러낸다(decisions.md §2.8).
    try:
        series = open_meteo.fetch_series(lat, lon, start, end + timedelta(hours=1))
        attribution.append("기상: Open-Meteo (open-meteo.com)")
    except Exception:  # noqa: BLE001 — 외부 I/O 경계, 스키마 보장이 우선
        return _result(
            _iso_window(start, end), None, moon_night, moon_caveat,
            ["기상: Open-Meteo (조회 실패)"],
        )

    hours = []
    for row in series:
        t = row["time"]
        if t < start or t >= end:  # 밤 창 밖 정시는 집계에서 제외
            continue
        state = astro.twilight_state(lat, lon, t)
        # 밤 집계의 매 정시도 순간 판정과 같은 광공해 상한을 받는다(같은 장소이므로).
        # 달빛 상한은 **정시마다 다르다** — 달이 뜬 시간과 진 시간의 등급이 같으면
        # "달이 지고 나면 나아진다"가 집계에 나타나지 않는다.
        result = _judge.judge(
            state, row["cloud_cover"], row["visibility"], site.cap, moon_caps.get(t)
        )
        hours.append(
            _tonight.HourResult(t, result.verdict, result.possible, row["cloud_cover"])
        )

    return _result(
        _iso_window(start, end), _tonight.summarize(hours), moon_night, moon_caveat
    )


def _moon_hours(
    lat: float, lon: float, start: datetime, end: datetime
) -> dict[datetime, _moon.Moon]:
    """밤 창 안의 각 정시에서 본 달. {정시: Moon}.

    정시를 고르는 규칙은 구름 집계와 같다 — 창 안에 실제로 들어오는 정시만
    (`decisions.md` §2.8). 두 축이 같은 정시를 봐야 등급이 어긋나지 않는다.
    """
    hours: dict[datetime, _moon.Moon] = {}
    t = start.replace(minute=0, second=0, microsecond=0)
    if t < start:
        t += timedelta(hours=1)
    while t < end:
        hours[t] = _moon.assess(lat, lon, t)
        t += timedelta(hours=1)
    return hours


def _moon_night(
    lat: float,
    lon: float,
    start: datetime,
    end: datetime,
    moon_hours: dict[datetime, _moon.Moon],
    site,
) -> tuple[dict, str | None, dict]:
    """밤 단위 달 요약 · 주의 문구 · 정시별 등급 상한.

    요약이 답하는 것은 "오늘 밤 달이 방해가 되나, 된다면 언제 비켜 주나"다. 그래서
    가장 밝을 때의 밝은 면 비율(얼마나 방해되나)·최고 고도·월출·월몰(언제 비키나)·
    달 없는 정시 수(얼마나 남나)를 함께 낸다.
    """
    moons = list(moon_hours.values())
    brightest = max(moons, key=lambda m: m.added_mcd) if moons else None

    # 정시마다 상한을 따로 낸다 — 달이 뜬 시간과 진 시간의 등급이 달라야 한다.
    caps: dict[datetime, str | None] = {}
    worst_sky = None
    for t, m in moon_hours.items():
        sky = _darkness.assess_sky(site, m.added_mcd)
        caps[t] = sky.cap if sky is not None else None
        if m is brightest:
            worst_sky = sky

    moonless = sum(1 for m in moons if not m.up)
    summary = {
        "illumination": brightest.illumination if brightest is not None else None,
        "max_altitude_deg": max((m.altitude_deg for m in moons), default=None),
        "moonless_hours": moonless,
        "events": _moon.window_events(lat, lon, start, end),
    }
    caveat = (
        _moon.caveat(worst_sky.milky_way, moonless)
        if worst_sky is not None and worst_sky.dimmed
        else None
    )
    return summary, caveat, caps


def _iso_window(start: datetime, end: datetime) -> dict:
    return {
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
    }
