"""P0 엔진 — astro → weather → judge 를 LangGraph StateGraph 로 잇는다.

각 노드는 계획서의 provider/factor 역할을 한다. 어둡기(SQM)·별 개수 같은 축은
아직 없고, P1/P3 에서 노드를 '하나씩' 추가하며 확장한다 — 그때도 이 파일의
그래프 조립과 state 계약은 안 바뀐다(엣지·노드만 늘어남).

계산 3모듈(data/script/{astro,judge,open_meteo})은 아직 PR 검토 중이라 옮기지
않고 import 만 한다. P1/P2 에서 server/providers·factors 로 정식 이관 예정.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from .state import EngineState

# --- 계산 모듈 import 브리지 (임시) -------------------------------------------
# data/script 를 패키지로 만들지 않고 경로만 추가해 셋을 그대로 재사용한다.
_CALC = Path(__file__).resolve().parents[2] / "data" / "script"
if str(_CALC) not in sys.path:
    sys.path.insert(0, str(_CALC))

import astro  # noqa: E402
import judge as _judge  # noqa: E402
import open_meteo  # noqa: E402

_STATE_NAMES = {0: "완전한 밤", 1: "천문박명", 2: "항해박명", 3: "시민박명", 4: "낮"}


# --- 노드 --------------------------------------------------------------------

def astro_node(state: EngineState) -> dict:
    """태양 고도 → 박명 구간·완전한 밤 구간(천문학적 사실)."""
    lat, lon, when = state["lat"], state["lon"], state["when"]
    code = astro.twilight_state(lat, lon, when)
    numbers: dict = {"twilight_state": code}
    reasons = [f"태양 고도 상태 {code}({_STATE_NAMES.get(code, code)})"]

    window = astro.dark_window(lat, lon, when)
    if window is not None:
        start, end = window
        numbers["dark_window"] = {
            "start": start.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
        }
        reasons.append(f"완전한 밤 {start:%H:%M}~{end:%H:%M}")

    return {
        "state_code": code,
        "numbers": numbers,
        "reasons": reasons,
        "attribution": ["천체력: JPL DE421 via Skyfield"],
    }


def weather_node(state: EngineState) -> dict:
    """Open-Meteo → 해당 정시의 저층운·시정."""
    data = open_meteo.fetch(state["lat"], state["lon"], state["when"])
    cl, vis = data["cloud_cover_low"], data["visibility"]
    return {
        "cloud_low": cl,
        "visibility": vis,
        "numbers": {"cloud_cover_low": cl, "visibility_m": vis},
        "attribution": ["기상: Open-Meteo (open-meteo.com)"],
    }


def judge_node(state: EngineState) -> dict:
    """상태·저층운·시정 → 관측 가능 여부(운영 정책)."""
    result = _judge.judge(
        state.get("state_code"), state.get("cloud_low"), state.get("visibility")
    )
    return {"possible": result.possible, "reasons": list(result.reasons)}


# --- 그래프 조립 --------------------------------------------------------------

def _build():
    g = StateGraph(EngineState)
    g.add_node("astro", astro_node)
    g.add_node("weather", weather_node)
    g.add_node("judge", judge_node)
    g.add_edge(START, "astro")
    g.add_edge("astro", "weather")
    g.add_edge("weather", "judge")
    g.add_edge("judge", END)
    return g.compile()


_GRAPH = _build()


def run(lat: float, lon: float, when: datetime) -> EngineState:
    """엔진 1회 실행. 누적된 최종 state 를 반환한다."""
    init: EngineState = {
        "lat": lat,
        "lon": lon,
        "when": when,
        "numbers": {},
        "reasons": [],
        "attribution": [],
    }
    return _GRAPH.invoke(init)
