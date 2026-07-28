"""제주 밤하늘 관측 MCP 서버 (P0 — 걷는 뼈대).

FastMCP · stateless · streamable HTTP `/mcp`. 도구는 **입력 방식**으로만 둘이다:

    evaluate_spot(좌표)      — 좌표를 직접 받는다.
    evaluate_place(주소·지명) — geocode 로 좌표화한 뒤 evaluate_spot 과 동일 처리.

"무엇을 묻나"(한 시각 vs 밤 전체)는 도구가 아니라 **scope 파라미터**로 고른다:

    scope="moment"(기본) — 한 시각의 관측 등급(astro→weather→judge). time 사용.
    scope="night"        — 박명 포함 밤 전체를 시간별로 판정해 관측 가능 시간 수·
                           등급 분포·연속 창을 집계(graph.run_tonight). time 무시.

("밤이냐"와 "지오코딩이냐"는 직교하는 축이라, 밤을 별도 도구로 빼면 지오코딩 래핑이
중복된다. scope 로 접어 두 도구가 두 질의를 모두 처리한다.) 밤 집계는 3시간 같은 기준으로
가능/불가를 매기지 않고 시간 수를 그대로 돌려준다 — 충분한지는 호출자가 정한다.

제주 범위 밖·형식 오류는 프롬프트형 에러. 별 개수 축은 아직 numbers 에 없다.

실행:  uv run python -m server.mcp_server   → http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from server.engine import graph
from server.clients import geocode
from server.schema import Response

KST = ZoneInfo("Asia/Seoul")

# 제주도 공식 행정구역 범위. 밖이면 평가하지 않는다.
# 위도 33°11′27″~33°33′50″N, 경도 126°08′43″~126°58′20″E 를 십진 변환하고,
# 경계점이 포함되도록 최소는 내림·최대는 올림했다.
_LAT_MIN, _LAT_MAX = 33.1908, 33.5639
_LON_MIN, _LON_MAX = 126.1452, 126.9723

mcp = FastMCP("jeju-star", stateless_http=True)


def _in_jeju(lat: float, lon: float) -> bool:
    return _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX


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
        as_of=datetime.now(KST).isoformat(timespec="minutes"),
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
        as_of=datetime.now(KST).isoformat(timespec="minutes"),
    ).to_dict()


def _evaluate_moment(
    lat: float,
    lon: float,
    date: str | None,
    time: str | None,
    resolved: dict | None = None,
) -> dict:
    """순간(한 시각) 평가 코어 — scope="moment" 경로.

    resolved 는 지오코딩으로 해석된 위치 메타데이터다. evaluate_place 만 채워 넘기고
    evaluate_spot 은 None 이다. 어느 쪽이든 Response 가 항상 키를 내보내 응답 '모양'이
    같게 유지된다(고정 스키마).
    """
    if not _in_jeju(lat, lon):
        return _out_of_range(lat, lon)

    try:
        when = _resolve_when(date, time)
    except (ValueError, AttributeError):
        return _invalid_when(date, time)

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
        numbers=final.get("numbers", {}),
        attribution=final.get("attribution", []),
        as_of=when.isoformat(timespec="minutes"),
        resolved=resolved,
    ).to_dict()


_SCOPES = ("moment", "night")


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
        as_of=datetime.now(KST).isoformat(timespec="minutes"),
    ).to_dict()


def _evaluate(
    lat: float,
    lon: float,
    date: str | None,
    time: str | None,
    scope: str,
    resolved: dict | None = None,
) -> dict:
    """좌표 기준 공통 코어 — scope 로 순간/밤 평가를 라우팅한다.

    evaluate_spot 은 좌표를, evaluate_place 는 지오코딩한 좌표를 넘겨 이 하나를 공유한다.
    (지오코딩과 순간/밤은 직교하므로 도구를 넷으로 쪼개지 않고 여기서 갈래만 나눈다.)
    """
    s = (scope or "moment").strip().lower()
    if s not in _SCOPES:
        return _invalid_scope(scope)
    if s == "night":
        return _evaluate_night(lat, lon, date, resolved)
    return _evaluate_moment(lat, lon, date, time, resolved)


@mcp.tool()
def evaluate_spot(
    lat: float,
    lon: float,
    date: str | None = None,
    time: str | None = None,
    scope: str = "moment",
) -> dict:
    """제주 특정 좌표의 별 관측 조건을 평가한다.

    scope 로 두 질의를 고른다:
      - "moment"(기본): 한 시각의 관측 등급(astro→weather→judge). time 사용.
      - "night": 박명 포함 밤 전체를 시간별로 판정해 **관측 가능 시간 수·등급 분포·
        연속 창**을 집계(3시간 같은 기준으로 가능/불가를 매기지 않음). time 무시.

    Args:
        lat: 위도 (제주 범위 내).
        lon: 경도 (제주 범위 내).
        date: 평가할 날짜 YYYY-MM-DD. 생략하면 오늘. 미래 날짜도 가능(구름은 예보
            지평 ~7일 안에서만, 박명·광공해는 지평 없음).
        time: 평가할 시각 24시간제 HH:MM(KST). scope="moment" 에서만 쓴다(생략 시 22:00;
            date·time 모두 생략 시 현재). scope="night" 이면 무시.
        scope: "moment" | "night". 기본 "moment".

    Returns:
        verdict/reasons/numbers/attribution/as_of/resolved 스키마(dict).
        좌표를 직접 받으므로 resolved 는 항상 None.
    """
    return _evaluate(lat, lon, date, time, scope)


@mcp.tool()
def evaluate_place(
    query: str,
    date: str | None = None,
    time: str | None = None,
    scope: str = "moment",
) -> dict:
    """주소·지명으로 별 관측 조건을 평가한다(제주).

    query 를 좌표로 변환(지오코딩)한 뒤 evaluate_spot 과 동일하게 평가한다.
    예: '제주시 애월읍', '성산일출봉', '한라산 1100고지'.

    Args:
        query: 제주 안의 주소 또는 지명.
        date: YYYY-MM-DD (생략 시 오늘). 미래 날짜 가능.
        time: HH:MM 24시간 KST. scope="moment" 에서만(생략 시 22:00; date·time 모두
            생략 시 현재). scope="night" 이면 무시.
        scope: "moment" | "night". 기본 "moment". (evaluate_spot 참조)
    """
    try:
        hit = geocode(query)
    except Exception:  # noqa: BLE001 — 외부 지오코딩 실패도 스키마로 환원
        hit = None
    if hit is None:
        # 좌표를 못 찾으면 이 서버는 여기까지. 좌표를 알아내는 건 Host 몫이다
        # (웹검색 등으로 좌표를 구해 evaluate_spot(lat, lon) 을 호출).
        return Response(
            verdict="주소 확인 실패",
            reasons=[
                f"'{query}'의 위치를 제주에서 찾지 못했습니다. "
                "좌표(위도·경도)를 알면 evaluate_spot 으로 바로 평가할 수 있어요. "
                "아니면 더 구체적인 주소·지명으로 다시 시도해 주세요."
            ],
            numbers={},
            attribution=["지오코딩: Photon (OpenStreetMap)"],
            as_of=datetime.now(KST).isoformat(timespec="minutes"),
        ).to_dict()

    resolved = {
        "query": query,
        "matched_query": hit.matched_query,
        "display_name": hit.display_name,
        "lat": hit.lat,
        "lon": hit.lon,
    }
    result = _evaluate(hit.lat, hit.lon, date, time, scope, resolved=resolved)
    if hit.matched_query and hit.matched_query != query:
        note = (
            f"'{query}'를 정확히 못 찾아 '{hit.matched_query}'로 검색했어요 → "
            f"{hit.display_name} ({hit.lat:.4f}, {hit.lon:.4f})"
        )
    else:
        note = f"'{query}' → {hit.display_name} ({hit.lat:.4f}, {hit.lon:.4f})로 해석했어요"
    result.setdefault("reasons", []).insert(0, note)
    result.setdefault("attribution", []).append("지오코딩: Photon (OpenStreetMap)")
    return result


# --- 밤 단위 평가 코어 (scope="night") ---------------------------------------

def _resolve_night_when(date: str | None) -> datetime:
    """밤 집계의 기준 시각을 만든다. date 가 주어지면 그날 저녁(20:00)을, 없으면
    현재 시각을 쓴다 — 어느 쪽이든 night_window 가 '그 밤'을 찾는다.
    파싱 실패 시 ValueError.
    """
    now = datetime.now(KST)
    if date is None:
        return now
    y, m, d = (int(x) for x in date.split("-"))
    return datetime(y, m, d, 20, 0, tzinfo=KST)


def _night_label(when: datetime) -> str:
    """밤 집계 문구의 날짜 라벨. 오늘이면 '오늘 밤', 아니면 'M월 D일 밤'.

    미래 계획(예: '내일 밤')을 '오늘 밤'으로 잘못 부르지 않도록 date 로 구분한다.
    """
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
        if summary["unknown_hours"] and not summary["total_hours"] - summary["unknown_hours"]:
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
        reasons.append(f"구름 정보를 못 받은 시간이 {summary['unknown_hours']}시간 있어요")

    return reasons


def _evaluate_night(
    lat: float, lon: float, date: str | None, resolved: dict | None = None
) -> dict:
    """밤 집계 코어 — scope="night" 경로(_evaluate 가 라우팅)."""
    if not _in_jeju(lat, lon):
        return _out_of_range(lat, lon)

    try:
        when = _resolve_night_when(date)
    except (ValueError, AttributeError):
        return _invalid_when(date, None)

    result = graph.run_tonight(lat, lon, when)
    window = result.get("window")
    summary = result.get("summary")
    label = _night_label(when)

    numbers: dict = {"night_window": window}
    if summary is not None:
        numbers["tonight"] = summary
    # 광공해(정적 장소 속성)는 순간 평가와 같은 필드로 밤 응답에도 노출한다(도구 일관성).
    darkness = result.get("darkness")
    if darkness is not None:
        numbers.update(darkness)

    reasons = _night_reasons(summary, window, label)
    # 어둡기 설명 한 줄 + (은하수 제약 시) 주의 문구. 관측 가능한 밤일 때만 덧붙인다.
    if summary is not None and summary.get("observable_hours"):
        if result.get("darkness_reason"):
            reasons.append(result["darkness_reason"])
        if result.get("milky_way_caveat"):
            reasons.append(result["milky_way_caveat"])

    return Response(
        verdict=_night_verdict(summary, window, label),
        reasons=reasons,
        numbers=numbers,
        attribution=result.get("attribution", []),
        as_of=when.isoformat(timespec="minutes"),
        resolved=resolved,
    ).to_dict()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
