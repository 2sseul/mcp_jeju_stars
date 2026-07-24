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

단, 저층운은 하늘이 아무리 어두워도 별을 물리적으로 가린다 → 저층운이 하늘을
덮으면 어둡기 등급과 무관하게 불가로 끌어내린다.

시정은 판정에 관여하지 않는다 — 참고 정보로만 노출한다. 이유는 셋이다.

1) 물리량이 다르다. 예보 시정은 지표 20 m 층의 *수평* 시정인데, 별을 보는 건
   *수직* 방향이다. 관측 지침도 이 둘을 구분해, 하늘이 차폐돼 운고를 못 낼 때
   수평시정이 아니라 수직시정(VV)으로 대체한다.
2) 저층운과 중복이다. 안개는 지면에 닿은 층운이므로, 하늘을 가릴 만큼 두꺼우면
   그 사실이 이미 cloud_cover_low 에 반영된다. 반대로 두께 수십 m 의 얕은
   복사안개는 수평시정만 무너뜨리고 수직으로는 투과한다. 실제로 한 모델 안에서
   두 변수는 일관된다(metno: 저층운 98%/시정 140 m, GFS: 0%/24 km) — 시정이
   독립적으로 더해주는 정보가 없다.
3) 예보 성능이 낮다. ECMWF 는 자사 시정 진단을 "an experimental product ...
   expectations regarding the quality of this product should remain low" 로
   명시하고, 저시정은 "orographic features that are not resolved by the model"
   에 좌우된다고 밝힌다(ECMWF Forecast User Guide, Visibility Parameter).
   한라산 1100고지(모델 격자 해발 1106 m)는 동일 시각 시정이 모델에 따라
   140 m ~ 24 km 로 갈린다.

임계값은 문헌 상수가 아니라 운영 기준이다(현장 피드백으로 조정 가능). 다만 안개
경계 1 km 는 WMO 의 안개 정의를 따른다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --- 운영 임계값(튜닝 가능) ---------------------------------------------------

#: 저층운(Open-Meteo cloud_cover_low, %)이 이 값을 초과하면 하늘을 덮은 것으로 본다.
CLOUD_LOW_MAX_PCT: float = 30.0

#: 수평시정(m) 표기 경계 — 등급에는 영향이 없고 안내 문구만 바꾼다.
#: 1 km 는 WMO 의 안개(fog) 정의 경계.
VISIBILITY_FOG_M: float = 1_000.0
VISIBILITY_HAZE_M: float = 10_000.0

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
    """시정을 사람이 읽는 문자열로. 반올림이 경계를 넘어 실제보다 좋아 보이지
    않도록 절사한다(9,999 m 를 '10.0km' 로 쓰지 않는다)."""
    if m < 1_000:
        return f"{m:.0f}m"
    return f"{math.floor(m / 100) / 10:.1f}km"


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

    # 저층운만이 차단 조건이다 — 어둡기와 무관하게 하늘을 물리적으로 덮는다.
    if cloud_low is None:
        return Judgement(IMPOSSIBLE, False, ["구름 정보를 가져오지 못했어요"])
    if cloud_low > CLOUD_LOW_MAX_PCT:
        return Judgement(
            IMPOSSIBLE,
            False,
            [f"낮은 구름이 하늘을 덮고 있어요 (저층운 {cloud_low:.0f}%)"],
        )

    reasons = [sky_msg, f"구름 적음 (저층운 {cloud_low:.0f}%)"]

    # 시정은 등급에 관여하지 않는다 — 참고 정보로만 덧붙인다(사유는 모듈 docstring).
    if visibility_m is None:
        pass
    elif visibility_m < VISIBILITY_FOG_M:
        reasons.append(
            f"지상에 안개가 낄 수 있어요 (수평시정 {_km(visibility_m)}) "
            "— 하늘이 열려 있어도 발밑은 뿌옇게 보일 수 있어요"
        )
    elif visibility_m < VISIBILITY_HAZE_M:
        reasons.append(f"연무가 낄 수 있어요 (수평시정 {_km(visibility_m)})")
    else:
        reasons.append(f"공기 맑음 (수평시정 {_km(visibility_m)})")

    return Judgement(sky_verdict, True, reasons)


# --- 검증 (API 불필요) --------------------------------------------------------

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cases = [
        # (이름, 상태, 저층운, 시정, 기대 등급)
        ("완전한밤+맑음", 0, 5.0, 20_000.0, OPTIMAL),
        ("천문박명+맑음", 1, 5.0, 20_000.0, GOOD),
        ("항해박명+맑음", 2, 5.0, 20_000.0, LIMITED),
        ("시민박명(너무밝음)", 3, 0.0, 30_000.0, IMPOSSIBLE),
        ("낮", 4, 0.0, 30_000.0, IMPOSSIBLE),
        # 저층운 = 유일한 차단 조건
        ("완전한밤+저층운많음", 0, 80.0, 20_000.0, IMPOSSIBLE),
        ("완전한밤+구름데이터없음", 0, None, 20_000.0, IMPOSSIBLE),
        # 시정 = 참고 정보. 어떤 값이든 등급을 바꾸지 않는다.
        ("완전한밤+안개", 0, 10.0, 400.0, OPTIMAL),
        ("천문박명+안개", 1, 10.0, 400.0, GOOD),
        ("항해박명+안개", 2, 10.0, 400.0, LIMITED),
        ("완전한밤+연무", 0, 10.0, 5_000.0, OPTIMAL),
        ("완전한밤+시정데이터없음", 0, 10.0, None, OPTIMAL),
        # 경계값 — 문구만 바뀌고 등급은 동일해야 한다.
        ("시정 999m(안개 문구)", 0, 10.0, 999.0, OPTIMAL),
        ("시정 1000m(연무 문구)", 0, 10.0, 1_000.0, OPTIMAL),
        ("시정 9999m(연무 문구)", 0, 10.0, 9_999.0, OPTIMAL),
        ("시정 10000m(맑음 문구)", 0, 10.0, 10_000.0, OPTIMAL),
        ("저층운 30%(통과)", 0, 30.0, 20_000.0, OPTIMAL),
        ("저층운 31%(차단)", 0, 31.0, 20_000.0, IMPOSSIBLE),
        # 실제 사례: 1100고지 2026-07-27 01:00 (저층운 다수모델 0%, 시정 140m)
        ("1100고지 07-27 01시", 0, 0.0, 140.0, OPTIMAL),
    ]

    failed = 0
    for name, st, cl, vis, expected in cases:
        r = judge(st, cl, vis)
        ok = r.verdict == expected
        failed += not ok
        mark = "가능" if r.possible else "불가"
        print(f"{'PASS' if ok else 'FAIL'} [{name}] -> {r.verdict}({mark})"
              f"{'' if ok else f', 기대={expected}'} : {', '.join(r.reasons)}")

    # 불변식: 시정은 등급을 바꾸지 않는다(하늘 상태·저층운이 같으면 결과도 같다).
    for st in (0, 1, 2):
        base = judge(st, 0.0, 20_000.0).verdict
        for vis in (0.0, 50.0, 999.0, 1_000.0, 9_999.0, None):
            got = judge(st, 0.0, vis)
            assert got.possible, f"시정 {vis} 가 불가를 만들었다"
            assert got.verdict == base, f"시정 {vis} 가 등급을 {base}→{got.verdict} 로 바꿨다"

    print(f"\n{len(cases) - failed}/{len(cases)} 통과")
    sys.exit(1 if failed else 0)
