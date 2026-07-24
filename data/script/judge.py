"""별 관측 판정 (순수 함수, 정책).

태양 고도 상태와 기상값(저층운·시정)만으로 "지금 별이 얼마나 보이나"를 등급으로
판정한다. API 호출 없이 값만 받아 값만 반환하므로 단독 테스트가 가능하다.

하늘 준비도는 단계적이다 — 완전한 밤(−18°)이어야만 별이 보이는 게 아니라, 해가
지고 어두워지면서 밝은 별부터 단계적으로 보이기 시작한다. (근거: Patat 2006
A&A 455, 385 / NOAA·USNO 박명 정의 / Crumey 2014 MNRAS 442, 2600 —
common/star_observation_conditions.md [T-1]~[T-5])

    태양 고도 상태(astro.twilight_state)      판정
    0 완전한 밤 (< −18°)        최적          은하수·성운까지
    1 천문박명 (−18~−12°)       양호          대부분의 맨눈 별
    2 항해박명 (−12~−6°)        밝은 별 한정   밝은 별·별자리 보이기 시작
    3 시민박명 (−6~0°)          불가          아직 하늘이 밝음
    4 낮                        불가          해가 떠 있음

단, 구름·안개는 하늘이 아무리 어두워도 별을 물리적으로 가린다 → 날씨가 나쁘면
어둡기 등급과 무관하게 불가로 끌어내린다. 구름·시정 임계값은 문헌 상수가 아니라
운영 기준이다(현장 피드백으로 조정 가능).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- 운영 임계값(튜닝 가능) ---------------------------------------------------

#: 저층운(Open-Meteo cloud_cover_low, %)이 이 값을 초과하면 하늘을 덮은 것으로 본다.
CLOUD_LOW_MAX_PCT: float = 30.0

#: 시정(Open-Meteo visibility, m)이 이 값 미만이면 안개·연무로 본다.
VISIBILITY_MIN_M: float = 10_000.0

# --- 판정 등급 ----------------------------------------------------------------

OPTIMAL = "최적"
GOOD = "양호"
LIMITED = "밝은 별 한정"
IMPOSSIBLE = "불가"

#: 태양 고도 상태 → (등급, 사람이 읽는 하늘 설명). 근거: 위 docstring 참조.
_SKY = {
    0: (OPTIMAL, "완전한 밤이라 은하수·성운까지 볼 수 있어요"),
    1: (GOOD, "하늘이 충분히 어두워 대부분의 별이 보여요"),
    2: (LIMITED, "아직 완전히 어둡진 않지만 밝은 별과 별자리는 보이기 시작해요"),
    3: (IMPOSSIBLE, "해가 진 지 얼마 안 돼 하늘이 밝아요 — 가장 밝은 별·행성만 겨우 보입니다"),
    4: (IMPOSSIBLE, "아직 낮이에요 — 해가 떠 있습니다"),
}


def _km(m: float) -> str:
    return f"{m / 1000:.1f}km"


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Judgement:
    """판정 결과.

    verdict:  등급(최적/양호/밝은 별 한정/불가).
    possible: 밝은 별이라도 볼 수 있는가(최적·양호·밝은 별 한정이면 True).
    reasons:  사람이 읽는 근거 문자열 목록.
    """

    verdict: str
    possible: bool
    reasons: list[str] = field(default_factory=list)


# --- 판정 ---------------------------------------------------------------------

def judge(
    state: int,
    cloud_low: float | None,
    visibility_m: float | None,
) -> Judgement:
    """태양 고도 상태·저층운·시정으로 관측 등급을 판정한다.

    Args:
        state: astro.twilight_state 값(0=완전한 밤 ~ 4=낮).
        cloud_low: 저층운 비율(%, 0~100). 없으면 None.
        visibility_m: 시정(m). 없으면 None.

    Returns:
        Judgement(verdict, possible, reasons).
    """
    sky_verdict, sky_msg = _SKY.get(
        state, (IMPOSSIBLE, f"하늘 상태를 알 수 없어요(상태 {state})")
    )

    # 애초에 별을 볼 시간대가 아니면(낮·시민박명) 날씨를 볼 것도 없다.
    if sky_verdict == IMPOSSIBLE:
        return Judgement(IMPOSSIBLE, False, [sky_msg])

    # 구름·안개는 어둡기와 무관하게 별을 가린다 → 하나라도 걸리면 불가.
    blockers: list[str] = []
    if cloud_low is None:
        blockers.append("구름 정보를 가져오지 못했어요")
    elif cloud_low > CLOUD_LOW_MAX_PCT:
        blockers.append(f"낮은 구름이 하늘을 덮고 있어요 (저층운 {cloud_low:.0f}%)")
    if visibility_m is None:
        blockers.append("시야 정보를 가져오지 못했어요")
    elif visibility_m < VISIBILITY_MIN_M:
        blockers.append(f"안개·연무로 시야가 흐려요 (시정 {_km(visibility_m)})")

    if blockers:
        return Judgement(IMPOSSIBLE, False, blockers)

    # 관측 가능 — 하늘 등급 + 좋은 날씨 근거를 함께 반환한다.
    reasons = [
        sky_msg,
        f"구름 적음 (저층운 {cloud_low:.0f}%)",
        f"공기 맑음 (시정 {_km(visibility_m)})",
    ]
    return Judgement(sky_verdict, True, reasons)


# --- 검증 (API 불필요) --------------------------------------------------------

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cases = [
        ("완전한밤+맑음", 0, 5.0, 20_000.0),
        ("천문박명+맑음", 1, 5.0, 20_000.0),
        ("항해박명+맑음", 2, 5.0, 20_000.0),
        ("시민박명(너무밝음)", 3, 0.0, 30_000.0),
        ("낮", 4, 0.0, 30_000.0),
        ("완전한밤+저층운많음", 0, 80.0, 20_000.0),
        ("완전한밤+안개", 0, 10.0, 400.0),
        ("천문박명+안개", 1, 10.0, 400.0),
        ("완전한밤+데이터없음", 0, None, 20_000.0),
    ]

    for name, st, cl, vis in cases:
        r = judge(st, cl, vis)
        mark = "가능" if r.possible else "불가"
        print(f"[{name}] -> {r.verdict}({mark}) : {', '.join(r.reasons)}")
