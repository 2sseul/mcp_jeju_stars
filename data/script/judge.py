"""별 관측 가능/불가 판정 (순수 함수).

태양 고도 상태(astro.twilight_state)와 기상값(저층운·시정)만으로
"지금 별을 볼 수 있는가"를 판정한다. API 호출 없이 값만 받아 값만 반환하므로
단독 테스트가 가능하다.

판정 우선순위(리서치 star_observation_conditions.md):
    1. 완전한 밤인가 (태양 고도 −18° 이하, state==0)
    2. 저층운이 하늘을 덮지 않는가 — 저층운은 다른 모든 조건을 무의미하게 만든다
    3. 시정이 확보되는가 (안개·연무 배제)

구름·시정 임계값은 **문헌 상수가 아니라 운영 기준**이다(리서치 확정).
현장 피드백에 따라 조정할 수 있도록 모듈 상수로 노출한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- 운영 임계값(튜닝 가능) ---------------------------------------------------

#: 저층운(Open-Meteo cloud_cover_low, %)이 이 값을 초과하면 불가.
#: 저층운은 별빛을 직접 차단하므로 가장 엄격하게 본다.
CLOUD_LOW_MAX_PCT: float = 30.0

#: 시정(Open-Meteo visibility, m)이 이 값 미만이면 불가(안개·연무).
VISIBILITY_MIN_M: float = 10_000.0

#: 완전한 밤을 의미하는 twilight_state 값(astro.py와 동일 정의).
_NIGHT_STATE: int = 0

_STATE_LABELS = {
    0: "완전한 밤",
    1: "천문박명",
    2: "항해박명",
    3: "시민박명",
    4: "낮",
}


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Judgement:
    """판정 결과.

    possible: 관측 가능 여부.
    reasons:  판정 근거 문자열 목록. 불가면 막는 이유들, 가능이면 충족 근거들.
    """

    possible: bool
    reasons: list[str] = field(default_factory=list)


# --- 판정 ---------------------------------------------------------------------

def judge(
    state: int,
    cloud_low: float | None,
    visibility_m: float | None,
) -> Judgement:
    """상태·저층운·시정으로 관측 가능 여부를 판정한다.

    Args:
        state: astro.twilight_state 값(0=완전한 밤 ~ 4=낮).
        cloud_low: 저층운 비율(%, 0~100). 없으면 None.
        visibility_m: 시정(m). 없으면 None.

    Returns:
        Judgement(possible, reasons). 불가 사유는 모두 모아 반환한다.
    """
    blockers: list[str] = []

    # 1) 밤이 아니면 즉시 불가(다른 조건은 볼 것도 없음).
    if state != _NIGHT_STATE:
        label = _STATE_LABELS.get(state, f"상태 {state}")
        return Judgement(False, [f"아직 완전한 밤이 아님({label})"])

    # 2) 저층운 — 다른 모든 조건을 무의미하게 만드는 결정적 요인.
    if cloud_low is None:
        blockers.append("저층운 데이터 없음")
    elif cloud_low > CLOUD_LOW_MAX_PCT:
        blockers.append(f"저층운 {cloud_low:.0f}% (> {CLOUD_LOW_MAX_PCT:.0f}%)")

    # 3) 시정 — 안개·연무 배제.
    if visibility_m is None:
        blockers.append("시정 데이터 없음")
    elif visibility_m < VISIBILITY_MIN_M:
        blockers.append(
            f"시정 {visibility_m / 1000:.1f}km (< {VISIBILITY_MIN_M / 1000:.0f}km)"
        )

    if blockers:
        return Judgement(False, blockers)

    # 가능 — 충족 근거를 함께 반환한다.
    reasons = [
        "완전한 밤",
        f"저층운 {cloud_low:.0f}%",
        f"시정 {visibility_m / 1000:.1f}km",
    ]
    return Judgement(True, reasons)


# --- 검증 (API 불필요) --------------------------------------------------------

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cases = [
        ("한밤+맑음+좋은시정", 0, 5.0, 20_000.0),
        ("한밤+저층운많음", 0, 80.0, 20_000.0),
        ("한밤+연무(시정낮음)", 0, 10.0, 4_000.0),
        ("한밤+구름과연무동시", 0, 60.0, 3_000.0),
        ("아직낮", 4, 0.0, 30_000.0),
        ("천문박명(아직안됨)", 1, 0.0, 30_000.0),
        ("데이터일부없음", 0, None, 20_000.0),
    ]

    for name, st, cl, vis in cases:
        r = judge(st, cl, vis)
        mark = "가능 ✅" if r.possible else "불가 ❌"
        print(f"[{name}] -> {mark} : {', '.join(r.reasons)}")
