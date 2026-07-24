"""제주 밤하늘 관측 MCP 서버 (P0 — 걷는 뼈대).

FastMCP · stateless · streamable HTTP `/mcp`. 도구는 evaluate_spot 하나.
엔진(LangGraph)이 astro→weather→judge 를 돌려 최종형 스키마로 답한다.

P0 범위: 좌표 직접 입력만(지오코딩·지명 없음), 제주 범위 밖은 프롬프트형 에러.
어둡기(SQM)·별 개수는 아직 numbers 에 없음 — P1/P3 에서 factor 로 추가한다.

실행:  uv run python -m server.mcp_server   → http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from server.engine import graph
from server.schema import Response

KST = ZoneInfo("Asia/Seoul")

# 제주도 공식 행정구역 범위. 밖이면 평가하지 않는다.
# 위도 33°11′27″~33°33′50″N, 경도 126°08′43″~126°58′20″E 를 십진 변환하고,
# 경계점이 포함되도록 최소는 내림·최대는 올림했다.
_LAT_MIN, _LAT_MAX = 33.1908, 33.5639
_LON_MIN, _LON_MAX = 126.1452, 126.9723

mcp = FastMCP("jeju-star", stateless_http=True)


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


@mcp.tool()
def evaluate_spot(
    lat: float, lon: float, date: str | None = None, time: str | None = None
) -> dict:
    """제주 특정 좌표의 별 관측 가능 여부를 평가한다.

    Args:
        lat: 위도 (제주 범위 내).
        lon: 경도 (제주 범위 내).
        date: 평가할 날짜 YYYY-MM-DD. 생략하면 오늘.
        time: 평가할 시각 24시간제 HH:MM(KST). 생략하면 22:00.
            date·time 모두 생략하면 현재 시각으로 평가한다.

    Returns:
        verdict/reasons/numbers/attribution/as_of 스키마(dict).
    """
    if not (_LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX):
        return _out_of_range(lat, lon)

    try:
        when = _resolve_when(date, time)
    except (ValueError, AttributeError):
        return _invalid_when(date, time)
    final = graph.run(lat, lon, when)

    reasons = list(final.get("reasons", []))
    # 관측 가능하면 오늘 완전히 어두운 시간대를 덤으로 알려준다.
    window = final.get("numbers", {}).get("dark_window")
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
    ).to_dict()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
