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
from modules.core import constellation as _constellation
from modules.core import darkness as _darkness
from modules.core import elevation as _elevation
from modules.core import horizon as _horizon
from modules.core import judge as _judge
from modules.core import lamps as _lamps
from modules.core import moon as _moon
from modules.core import nightlight as _nightlight
from modules.core import tonight as _tonight
from modules.core import weather as _weather

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


def _round(v: float | None, digits: int) -> float | int | None:
    """결측을 흘려보내며 반올림한다. digits=0 이면 int 로 되돌린다."""
    if v is None:
        return None
    return round(v) if digits == 0 else round(v, digits)


def _weather_numbers(row: dict) -> dict:
    """기상 행 → numbers 조각. 판정 축(운량·시정)과 참고 축(기온·바람 등)을 함께 편다.

    소비자(LLM)가 보는 키를 한 겹으로 유지한다(`_darkness_numbers` 와 같은 결).
    하늘 상태 라벨(`sky`)까지 여기서 붙인다 — 코드 숫자만 주면 호출자가 "맑음" 을
    지어내야 하기 때문이다.

    기온·풍속은 예보 해상도(0.1)에 맞춰 자른다. 부동소수점 원값(23.59749984741211)을
    그대로 내보내면 없는 정밀도를 있는 것처럼 읽히게 한다.
    """
    code = row.get("weather_code")
    return {
        "cloud_cover": row.get("cloud_cover"),
        "visibility_m": row.get("visibility"),
        "temperature_c": _round(row.get("temperature_c"), 1),
        "apparent_temperature_c": _round(row.get("apparent_c"), 1),
        "humidity_pct": _round(row.get("humidity_pct"), 0),
        "wind_speed_ms": _round(row.get("wind_ms"), 1),
        "precipitation_probability_pct": _round(
            row.get("precipitation_probability_pct"), 0
        ),
        "weather_code": code,
        "sky": _weather.sky_label(code),
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
        empty = open_meteo.empty_row(state["when"])
        return {
            "cloud": None,
            "visibility": None,
            "weather": empty,
            "numbers": _weather_numbers(empty),
            "attribution": ["기상: Open-Meteo (조회 실패)"],
        }

    cloud = data["cloud_cover"]
    vis = data["visibility"]
    numbers: dict = _weather_numbers(data)
    return {
        "cloud": cloud,
        "visibility": vis,
        "weather": data,
        "numbers": numbers,
        "attribution": ["기상: Open-Meteo (open-meteo.com)"],
    }


#: 기상 서술을 붙이는 태양 고도 상태. judge 가 날씨를 보기 시작하는 구간과 같다
#: (3=시민박명·4=낮 은 하늘이 밝아 이미 '불가'이므로, 기온·바람을 말해 봐야 소음이다).
_WEATHER_STATES = (0, 1, 2)


def constellation_node(state: EngineState) -> dict:
    """별자리 → 지금 하늘 어디에 무엇이 있는가. **등급은 바꾸지 않는다.**

    judge 뒤에 둔다(`comfort_node` 와 같은 이유). 하늘이 밝은 시간대(시민박명·낮)에는
    아무것도 내지 않는다 — 안 보이는 별자리를 나열해 봐야 소음이다.

    한계등급은 **달빛까지 더한** 하늘밝기에서 낸다(`sky_sqm`). 그래서 보름달 밤에는
    잡히는 별이 저절로 줄어든다. 달빛을 못 구했으면 정적 광공해 등급으로 물러선다.

    지형 지평선(`horizon.profile`)도 함께 넘긴다 — 그러면 하늘에 떠 있어도 오름·한라산에
    가린 별자리가 목록에서 빠진다. 표고 격자가 없는 배포에서는 지평선이 None 이라
    예전처럼 "가릴 수 있어요"까지만 말한다.
    """
    if state.get("state_code") not in _WEATHER_STATES:
        return {}

    nums = state.get("numbers", {})
    sqm = nums.get("sky_sqm")
    bortle = _darkness.bortle_of(sqm) if sqm is not None else nums.get("bortle")

    prof = _horizon.profile(state["lat"], state["lon"])
    got = _constellation.assess(
        state["lat"], state["lon"], state["when"], bortle, horizon=prof
    )
    # 알아볼 만한 것만 싣는다. 지평 아래·너무 흐린 것까지 실으면 88개가 그대로 나가
    # 호출자가 읽을 것이 아니라 걸러낼 것을 받게 된다.
    rows = [
        {
            "name": c.korean,
            "bearing": c.bearing,
            "altitude_deg": c.altitude_deg,
            "low": c.low,
            "brightest": c.brightest,
        }
        for c in got if c.naked_eye
    ]
    numbers: dict = {"constellations": rows}
    attribution = list(_constellation.SOURCES)
    reasons = _constellation.describe(got)
    if prof is not None:
        numbers["horizon"] = prof
        reasons.extend(_horizon.describe(prof))
        attribution.append(_elevation.SOURCE)
    return {
        "numbers": numbers,
        "reasons": reasons,
        "attribution": attribution,
    }


def comfort_node(state: EngineState) -> dict:
    """기상값 → 사람이 읽는 기상 문장(기온·체감·바람).

    judge **뒤에** 둔다. 두 가지 이유다.
    1) 등급에 관여하지 않음을 배치로 못박는다 — judge 는 이 노드의 결과를 보지 못한다.
    2) reasons 는 노드 순서대로 쌓이므로, 판정 근거가 먼저 오고 참고 정보가 뒤에 온다.
    """
    if state.get("state_code") not in _WEATHER_STATES:
        return {}
    return {"reasons": _weather.describe(state.get("weather") or {})}


def judge_node(state: EngineState) -> dict:
    """상태·총운량·시정 → 관측 등급(운영 정책). 광공해·달빛 상한을 함께 받는다.

    darkness_node·moon_node 가 먼저 돌아야 상한이 채워진다(그래서 엣지가
    darkness → moon → judge 다).
    """
    w = state.get("weather") or {}
    result = _judge.judge(
        state.get("state_code"),
        state.get("cloud"),
        state.get("visibility"),
        state.get("darkness_cap"),
        state.get("moon_cap"),
        weather_code=w.get("weather_code"),
        precip_prob_pct=w.get("precipitation_probability_pct"),
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
    g.add_node("comfort", comfort_node)
    g.add_node("constellation", constellation_node)
    # 어둡기·달빛이 judge 보다 앞이다 — judge 가 그 상한(cap)들을 받아 등급을 정하기
    # 때문. 달빛은 어둡기 위에 얹으므로 darkness 뒤다.
    g.add_edge(START, "astro")
    g.add_edge("astro", "weather")
    g.add_edge("weather", "darkness")
    g.add_edge("darkness", "moon")
    g.add_edge("moon", "judge")
    # 기상 서술(comfort)은 judge 뒤다 — 등급에 관여하지 않음을 배치로 못박는다.
    # judge 뒤에 참고 축 둘이 붙는다 — 무엇이 보이나(별자리), 뭘 입나(기상).
    # 둘 다 등급에 관여하지 않으므로 judge 는 이들의 결과를 보지 못한다.
    g.add_edge("judge", "constellation")
    g.add_edge("constellation", "comfort")
    g.add_edge("comfort", END)
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

    def _result(window, summary, moon=None, moon_caveat=None, extra_attr=None,
                weather=None) -> dict:
        return {
            "window": window,
            "summary": summary,
            "weather": weather,
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
    inside = []
    for row in series:
        t = row["time"]
        if t < start or t >= end:  # 밤 창 밖 정시는 집계에서 제외
            continue
        inside.append(row)
        state = astro.twilight_state(lat, lon, t)
        # 밤 집계의 매 정시도 순간 판정과 같은 광공해 상한을 받는다(같은 장소이므로).
        # 달빛 상한은 **정시마다 다르다** — 달이 뜬 시간과 진 시간의 등급이 같으면
        # "달이 지고 나면 나아진다"가 집계에 나타나지 않는다.
        result = _judge.judge(
            state,
            row["cloud_cover"],
            row["visibility"],
            site.cap,
            moon_caps.get(t),
            weather_code=row.get("weather_code"),
            precip_prob_pct=row.get("precipitation_probability_pct"),
        )
        hours.append(
            _tonight.HourResult(t, result.verdict, result.possible, row["cloud_cover"])
        )

    # 기상 집계는 판정과 **같은 정시 집합**(밤 창 안)을 본다. 창 밖 정시가 섞이면
    # "밤 기온 최저"가 해 지기 전 값이 되어 실제보다 따뜻하게 읽힌다.
    return _result(
        _iso_window(start, end), _tonight.summarize(hours), moon_night, moon_caveat,
        weather=_weather.summarize_night(inside)
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
