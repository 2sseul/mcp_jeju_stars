"""기상 서술 (순수 함수, 네트워크 없음).

`judge.py` 가 "별이 보이나"를 판정한다면, 이 모듈은 **"뭘 입고 나갈까"** 를 답한다.
기온·체감온도·습도·바람·강수·하늘 상태를 사람이 읽는 문장과 구조화 수치로 옮긴다.

판정에 관여하지 않는다 — 원칙
--------------------------------------------------------------------------
등급을 정하는 축은 여전히 어둡기(광공해·달빛)와 차폐다. 기온이 낮다고 별이 덜 보이지 않고,
바람이 분다고 등급이 내려가지도 않는다. 그래서 이 모듈의 값은 **어디에서도 verdict 를
바꾸지 않는다**. `judge.py` 가 시정을 "참고 문구만" 으로 두는 것과 같은 자리다
(`judge` 모듈 docstring 4절).

바꾸지 않는 대신 **빠짐없이 노출한다**. 관측지까지 차로 한 시간을 가는 사람에게
"오늘 밤 최저 2°C, 바람 7m/s" 는 등급만큼이나 실제 행동을 바꾸는 정보다.

하늘 상태(맑음/흐림/비)는 **해석표만 여기 두고, 말은 judge 가 한다**
--------------------------------------------------------------------------
WMO 코드 해석표(`WMO_LABEL`)와 판별(`sky_label`·`is_precipitating`)은 이 모듈이 갖는다 —
순수 표라서 여기가 제자리다. 하지만 그것으로 **문장을 만드는 것은 `judge`** 다.
비·눈은 차폐 축의 신호라 등급을 정하는 쪽이 함께 말해야 앞뒤가 맞기 때문이다
(`judge` docstring 2절, `decisions.md` §2.40).

그래서 이 모듈이 만드는 문장에는 맑음·흐림·비·안개가 **하나도 없다**. 기온·체감·습도·
바람뿐이다. 하늘 상태 라벨은 `numbers.sky` 로 **항상** 노출된다 — 호출자(LLM)가
"맑음"을 지어내지 않고 받게 하기 위해서다.

임계값은 전부 근거값이다
--------------------------------------------------------------------------
    WMO 4677 기상 코드      하늘 상태 라벨 (Open-Meteo Forecast API `weather_code`)
    보퍼트 풍력계급 4·6      바람 문구 경계 (WMO No.8 Guide, Part II Ch.5)
    0°C                     물의 어는점 — 결빙·서리
    25°C                    기상청 열대야 정의(밤 최저기온 25°C 이상)

'따뜻하다/춥다' 같은 자체 눈금은 만들지 않는다. 근거 없는 경계를 만드느니 **수치를
그대로** 문장에 넣는다(`기온 12°C · 체감 9°C`).
"""

from __future__ import annotations

from collections import Counter

__all__ = [
    "BEAUFORT_FRESH_MS",
    "BEAUFORT_STRONG_MS",
    "FOG_CODES",
    "FREEZING_C",
    "PRECIP_MIN_CODE",
    "SNOW_CODES",
    "TROPICAL_NIGHT_C",
    "WMO_LABEL",
    "describe",
    "describe_night",
    "is_precipitating",
    "precip_kind",
    "sky_label",
    "summarize_night",
]

# --- WMO 기상 코드 -------------------------------------------------------------

#: WMO 4677 코드 → 한국어 라벨. Open-Meteo `weather_code` 가 돌려주는 값의 해석표
#: (Open-Meteo Forecast API 문서 "WMO Weather interpretation codes (WW)").
#: 원문 등급(Slight/Moderate/Heavy)을 그대로 옮긴다 — 임의로 묶지 않는다.
WMO_LABEL: dict[int, str] = {
    0: "맑음",
    1: "대체로 맑음",
    2: "구름 조금",
    3: "흐림",
    45: "안개",
    48: "상고대 안개",
    51: "약한 이슬비",
    53: "이슬비",
    55: "짙은 이슬비",
    56: "약한 어는 이슬비",
    57: "짙은 어는 이슬비",
    61: "약한 비",
    63: "비",
    65: "강한 비",
    66: "약한 어는 비",
    67: "강한 어는 비",
    71: "약한 눈",
    73: "눈",
    75: "강한 눈",
    77: "싸락눈",
    80: "약한 소나기",
    81: "소나기",
    82: "강한 소나기",
    85: "약한 소낙눈",
    86: "강한 소낙눈",
    95: "뇌우",
    96: "우박 동반 뇌우",
    99: "강한 우박 동반 뇌우",
}

#: 안개 계열(시야를 가리지만 강수는 아니다). WMO 4677 의 45·48.
FOG_CODES: tuple[int, ...] = (45, 48)

#: 이 코드 이상은 전부 강수 계열이다(이슬비 51 부터). WMO 4677 의 배열이 그렇다 —
#: 0~48 은 무강수(청천·구름·안개), 51 부터가 이슬비·비·눈·소나기·뇌우다.
PRECIP_MIN_CODE: int = 51

#: 강수 계열 중 **눈**인 코드(WMO 4677). 71·73·75 눈, 77 싸락눈, 85·86 소낙눈.
#: 나머지 강수(이슬비·비·소나기·뇌우)는 비로 본다. 제주 저지대는 여름에 눈이 오지
#: 않으므로, 이 구분 없이 "비나 눈"으로 뭉뚱그리면 8월에 눈 예보를 말하게 된다.
SNOW_CODES: tuple[int, ...] = (71, 73, 75, 77, 85, 86)

# --- 바람 (보퍼트 풍력계급, WMO No.8 Guide Part II Ch.5) -----------------------

#: 보퍼트 4 '건들바람'(moderate breeze)의 하한. 먼지가 일고 종이가 날린다.
BEAUFORT_FRESH_MS: float = 5.5

#: 보퍼트 6 '된바람'(strong breeze)의 하한. 우산을 들기 어렵다.
BEAUFORT_STRONG_MS: float = 10.8

# --- 기온 표기 경계 (등급에 영향 없음, 문구만 바꾼다) -------------------------

#: 물의 어는점. 노면 결빙·서리의 경계.
FREEZING_C: float = 0.0

#: 기상청 열대야 정의 — 밤(18:01~다음날 09:00) 최저기온이 이 값 이상.
TROPICAL_NIGHT_C: float = 25.0


# --- 보조 ---------------------------------------------------------------------

def _c(v: float) -> str:
    """기온을 사람이 읽는 문자열로. 0.1°C 예보값을 정수로 반올림해 읽기 쉽게 한다."""
    return f"{round(v):.0f}°C"


def sky_label(code: int | None) -> str | None:
    """WMO 기상 코드 → 한국어 하늘 상태. 모르는 코드·결측이면 None."""
    if code is None:
        return None
    return WMO_LABEL.get(int(code))


def is_precipitating(code: int | None) -> bool:
    """비·눈·소나기·뇌우 계열인가(안개는 제외).

    `judge` 가 차폐 축의 상한(cap)을 정할 때 쓴다 — 참이면 그 정시는 '불가'다.
    """
    return code is not None and int(code) >= PRECIP_MIN_CODE


def precip_kind(codes: list[int]) -> str | None:
    """강수 코드들이 실제로 무엇인지 — "비" · "눈" · "비·눈". 강수가 없으면 None.

    여러 정시를 뭉뚱그려 말할 때 쓴다. 한 정시는 `sky_label` 로 정확한 이름
    ("약한 이슬비")을 그대로 부를 수 있지만, 밤 전체를 한 문장으로 말할 때는 종류만
    남긴다 — 그때 "비나 눈"으로 뭉치면 8월에도 눈 예보를 말하게 된다.
    """
    precip = [c for c in codes if is_precipitating(c)]
    if not precip:
        return None
    snow = any(c in SNOW_CODES for c in precip)
    rain = any(c not in SNOW_CODES for c in precip)
    if snow and rain:
        # 가운뎃점으로 잇는다 — "구름과 비와 눈 예보로"처럼 조사가 겹치지 않게.
        return "비·눈"
    return "눈" if snow else "비"


# --- 한 시각 서술 --------------------------------------------------------------

def describe(row: dict) -> list[str]:
    """정시 하나의 기상값을 사람이 읽는 문장 목록으로.

    **강수·안개·하늘 상태는 여기서 말하지 않는다** — 그건 차폐 축이라 `judge` 소관이다.
    이 함수가 답하는 것은 "뭘 입고 나갈까" 하나뿐이다(기온·체감·습도·바람). 한 응답에서
    같은 사실을 두 모듈이 각자 말하면 겹치거나 어긋난다(`decisions.md` §2.40).

    Args:
        row: `clients.open_meteo` 가 돌려주는 정시 행. 다음 키를 본다(전부 선택).
             temperature_c · apparent_c · humidity_pct · wind_ms.
             없는 키는 그 문장을 만들지 않는다 — 모르는 것을 지어내지 않는다.

    Returns:
        문장 목록. 값이 하나도 없으면 빈 목록.
    """
    lines: list[str] = []

    temp = row.get("temperature_c")
    apparent = row.get("apparent_c")
    humidity = row.get("humidity_pct")
    if temp is not None:
        parts = [f"기온 {_c(temp)}"]
        # 체감온도는 Open-Meteo 가 바람·습도·일사를 이미 반영해 준 값이다.
        # 기온과 같게 나오면(반올림 기준) 두 번 말하지 않는다.
        if apparent is not None and round(apparent) != round(temp):
            parts.append(f"체감 {_c(apparent)}")
        if humidity is not None:
            parts.append(f"습도 {humidity:.0f}%")
        lines.append(" · ".join(parts) + "예요")

    lines.extend(_wind_lines(row.get("wind_ms")))
    return lines


def _wind_lines(wind_ms: float | None) -> list[str]:
    """바람 문장. 보퍼트 4 미만은 말하지 않는다 — 관측에 영향이 없다."""
    if wind_ms is None or wind_ms < BEAUFORT_FRESH_MS:
        return []
    if wind_ms >= BEAUFORT_STRONG_MS:
        return [
            f"바람이 강해요 (풍속 {wind_ms:.1f}m/s) "
            "— 야외에 오래 서 있기 힘들고 삼각대도 흔들립니다"
        ]
    return [
        f"바람이 제법 불어요 (풍속 {wind_ms:.1f}m/s) "
        "— 체감온도가 더 떨어지니 바람막이를 챙기세요"
    ]


# --- 밤 단위 집계 --------------------------------------------------------------

def summarize_night(rows: list[dict]) -> dict | None:
    """밤 구간 정시들의 기상값을 밤 단위 요약으로 집계한다.

    `tonight.summarize` 가 관측 **시간 수**를 집계하는 것과 같은 층위에서, 이쪽은
    **기상값**을 집계한다. 둘을 한 함수에 넣지 않는 것은 축이 다르기 때문이다 —
    관측 가능 시간은 판정의 산물이고, 기온·바람은 판정과 무관한 사실이다.

    Args:
        rows: 밤 창 안 정시들의 기상 행(`clients.open_meteo` 형식).

    Returns:
        집계 dict. 쓸 수 있는 값이 하나도 없으면 None(호출자가 '기상 정보 없음'으로
        환원한다).
    """
    temps = [r["temperature_c"] for r in rows if r.get("temperature_c") is not None]
    apparents = [r["apparent_c"] for r in rows if r.get("apparent_c") is not None]
    winds = [r["wind_ms"] for r in rows if r.get("wind_ms") is not None]
    humidities = [r["humidity_pct"] for r in rows if r.get("humidity_pct") is not None]
    probs = [
        r["precipitation_probability_pct"]
        for r in rows
        if r.get("precipitation_probability_pct") is not None
    ]
    codes = [int(r["weather_code"]) for r in rows if r.get("weather_code") is not None]

    if not (temps or winds or probs or codes):
        return None

    code = _dominant_code(codes)
    return {
        "temp_min_c": round(min(temps), 1) if temps else None,
        "temp_max_c": round(max(temps), 1) if temps else None,
        "apparent_min_c": round(min(apparents), 1) if apparents else None,
        "humidity_max_pct": round(max(humidities)) if humidities else None,
        "wind_max_ms": round(max(winds), 1) if winds else None,
        "precipitation_probability_max_pct": round(max(probs)) if probs else None,
        "precipitation_hours": sum(1 for c in codes if is_precipitating(c)),
        "precipitation_kind": precip_kind(codes),
        "weather_code": code,
        "sky": sky_label(code),
    }


def _dominant_code(codes: list[int]) -> int | None:
    """밤을 대표하는 기상 코드. 최빈값, 동률이면 **코드가 큰 쪽**(더 나쁜 쪽)을 쓴다.

    동률 처리를 순서에 맡기지 않는 것은, 같은 밤을 두 번 물었을 때 답이 달라지지 않게
    하기 위해서다. 나쁜 쪽으로 기우는 것은 맨눈 관측에서 놓치는 쪽이 더 아프기 때문이다
    (`cloud.partial_weight` 의 기본값과 같은 방향).
    """
    if not codes:
        return None
    counts = Counter(codes)
    top = max(counts.values())
    return max(c for c, n in counts.items() if n == top)


def describe_night(summary: dict | None) -> list[str]:
    """밤 기상 요약을 사람이 읽는 문장 목록으로. 요약이 없으면 빈 목록."""
    if not summary:
        return []

    lines: list[str] = []
    lo, hi = summary.get("temp_min_c"), summary.get("temp_max_c")
    if lo is not None and hi is not None:
        span = _c(lo) if round(lo) == round(hi) else f"{_c(lo)}~{_c(hi)}"
        line = f"밤 기온은 {span}예요"
        # 체감은 **기온보다 낮을 때만** 덧붙인다. 이 값을 쓰는 이유가 방한 판단이라서다
        # — 습한 여름밤에는 체감이 기온보다 높게 나오는데(26°C), 그걸 "최저 체감"이라
        # 부르면 최저기온(23°C)보다 큰 수가 '최저'로 붙어 읽는 사람을 헷갈리게 한다.
        apparent = summary.get("apparent_min_c")
        if apparent is not None and round(apparent) < round(lo):
            line += f" (체감 {_c(apparent)})"
        lines.append(line)

        if lo <= FREEZING_C:
            lines.append("영하로 내려가니 노면 결빙과 서리를 조심하세요")
        elif lo >= TROPICAL_NIGHT_C:
            lines.append("열대야라 밤에도 25°C 아래로 안 내려가요")

    lines.extend(_night_precip_lines(summary))

    wind = summary.get("wind_max_ms")
    if wind is not None and wind >= BEAUFORT_FRESH_MS:
        lines.extend(_wind_lines(wind))

    return lines


def _night_precip_lines(summary: dict) -> list[str]:
    """밤 강수 문장. 강수 시간 수를 그대로 말하고 가능/불가를 매기지 않는다."""
    hours = summary.get("precipitation_hours") or 0
    prob = summary.get("precipitation_probability_max_pct")
    label = summary.get("sky")

    # 강수확률 0%는 말하지 않는다 — 비 올 일이 없다는 뜻이라 덧붙일 정보가 없다.
    tail = f" (최대 강수확률 {prob:.0f}%)" if prob else ""

    if hours:
        kind = summary.get("precipitation_kind") or "비"
        return [f"밤사이 {hours}시간은 {kind} 예보예요{tail}"]

    if label and not is_precipitating(summary.get("weather_code")):
        # 라벨을 그대로 인용한다. "대체로 맑음"에 '대체로'를 또 붙이면 말이 겹친다.
        # '가장 많다'는 것은 사실 그대로다 — 이 값은 밤 정시들의 최빈 코드다.
        return [f"밤 하늘은 '{label}' 예보가 가장 많아요{tail}"]

    return []
