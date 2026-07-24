"""LangGraph 엔진 공유 상태.

계획서의 엔진 원칙(고정3): factor(=노드)들을 순서대로 돌며 결과를 '누적'만 한다.
그 누적을 LangGraph StateGraph 의 리듀서로 표현한다 — 각 노드는 자기 조각만
반환하고, numbers/reasons/attribution 은 리듀서가 합친다. 스칼라(state_code 등)는
마지막 기록이 이긴다(overwrite).

factor 를 늘려도(P1 어둡기, P3 별개수 …) 이 상태와 엔진 루프는 안 바뀐다.
"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, TypedDict


def _merge(a: dict, b: dict) -> dict:
    """numbers 조각들을 얕게 합친다(뒤 노드가 같은 키면 덮어씀)."""
    return {**a, **b}


class EngineState(TypedDict, total=False):
    # 입력 ctx
    lat: float
    lon: float
    when: datetime

    # 노드가 채우는 중간 값(스칼라: overwrite)
    state_code: int | None  # 박명 구간 값(0=완전한 밤)
    cloud_low: float | None  # 저층운 %
    visibility: float | None  # 시정 m
    verdict: str | None  # 판정 등급(최적/양호/밝은 별 한정/불가)
    possible: bool | None  # 밝은 별이라도 볼 수 있는가

    # 누적(리듀서)
    numbers: Annotated[dict, _merge]
    reasons: Annotated[list[str], operator.add]
    attribution: Annotated[list[str], operator.add]
