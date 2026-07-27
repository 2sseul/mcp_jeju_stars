"""별 관측 판정 (순수 함수, 정책).

태양 고도 상태와 기상값(층별 운량·시정)만으로 "지금 별이 얼마나 보이나"를 등급으로
판정한다. API 호출 없이 값만 받아 값만 반환하므로 단독 테스트가 가능하다.

판정은 세 축을 각각 평가한 뒤 가장 나쁜 축을 따른다.

    어둡기 축 (태양 고도)      →  등급 결정
    차폐 축 (저층운 + 중층운)  →  등급 결정
    투명도 축 (고층운)         →  등급 상한만
    시정                       →  판정에 관여하지 않음(참고 문구만)

세 축을 하나의 점수로 합치지 않는 것은 ESO 의 구조를 따른 것이다. ESO 는
clear sky 를 "운량 10% 미만 AND 투과율 변동 10% 미만" 으로 두 조건을 각각 걸고,
투과율 변동 초과분은 thin cirrus 로 따로 분류한다. 가중합으로 단일 점수를 만들면
검증할 수 없는 계수가 생기므로 쓰지 않는다.
(Kerber et al. 2014 — A&A 2022, 10.1051/0004-6361/202142493 에서 재인용)


1. 어둡기 축
--------------------------------------------------------------------------
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


2. 차폐 축 — 저층운 + 중층운
--------------------------------------------------------------------------
저층운·중층운은 물방울 구름이라 불투명하다. 하늘이 아무리 어두워도 별을 물리적으로
가리므로 어둡기 등급과 무관하게 등급을 끌어내린다.

두 층을 단순히 더하지 않는다. 같은 하늘 조각을 두 층이 동시에 덮을 수 있어 단순
합은 과대평가가 된다. 대기 복사 계산에서 층 구름을 결합할 때 쓰는 표준 가정 중
random overlap 을 쓴다. random 가정의 결과는 maximum 과 minimum 가정 사이에
위치한다. (Geleyn & Hollingsworth 1979; 개관은 Zhang & Jing 2016)

    차폐율 = 1 - (1 - low) x (1 - mid)


3. 투명도 축 — 고층운
--------------------------------------------------------------------------
권운은 얼음 결정이라 반투과다. 별을 가리는 게 아니라 어둡게 만든다. 따라서 차폐
축이 통과한 경우 고층운이 끌어내릴 수 있는 하한은 '밝은 별 한정' 까지이며, 고층운
단독으로는 '불가' 가 되지 않는다. 이 하한은 임계값이 아니라 ESO 의 thin cirrus
분류에서 나온 것이므로 튜닝 대상이 아니다.


4. 임계값 사다리 (차폐 축·투명도 축 공통)
--------------------------------------------------------------------------
세 경계 모두 문헌값이며, 두 축에 동일하게 적용한다(ESO 의 AND 구조).

    <= 10%   ESO clear sky (Kerber et al. 2014)
    <= 30%   Xin et al. 2020 photometric time block (PTB) 상한
             — Ehgamberdiev et al. 2000 의 clear night 25% 가 이 구간에 든다
    <= 50%   Xin et al. 2020 spectroscopic time block (STB) 상한
    >  50%   관측 불가


5. 시정 — 판정에 관여하지 않는다
--------------------------------------------------------------------------
참고 정보로만 노출한다. 이유는 셋이다.

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

안개 경계 1 km 는 WMO 의 안개 정의를 따른다. 이 값은 등급이 아니라 문구만 바꾼다.


6. 결측
--------------------------------------------------------------------------
구름 정보가 없으면 '불가' 가 아니라 '알 수 없음' 이다. 모르는 것과 나쁜 것을
같은 등급으로 두면 관측지 추천에서 데이터 없는 지점이 흐린 지점과 같은 순위로
떨어진다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --- 임계값 (전부 문헌값, 튜닝 대상 아님) -------------------------------------

#: ESO clear sky. Kerber et al. 2014.
CLEAR_PCT: float = 10.0

#: Xin et al. 2020 PTB 상한. Ehgamberdiev et al. 2000 의 25% 가 이 구간에 포함된다.
PHOTOMETRIC_PCT: float = 30.0

#: Xin et al. 2020 STB 상한. 이 값을 넘으면 관측 불가.
SPECTROSCOPIC_PCT: float = 50.0

# --- 표기 경계 (등급에 영향 없음, 문구만 바꾼다) ------------------------------

#: 1 km 는 WMO 의 안개(fog) 정의 경계.
VISIBILITY_FOG_M: float = 1_000.0
VISIBILITY_HAZE_M: float = 10_000.0

# --- 판정 등급 ----------------------------------------------------------------

OPTIMAL = "최적"
GOOD = "양호"
LIMITED = "밝은 별 한정"
IMPOSSIBLE = "불가"
UNKNOWN = "알 수 없음"

#: 나쁠수록 큰 값. 축들의 판정을 합칠 때 max() 로 나쁜 쪽을 취한다.
#: UNKNOWN 은 이 순서에 들어가지 않는다 — 등급이 아니라 별개 상태다.
_RANK = {OPTIMAL: 0, GOOD: 1, LIMITED: 2, IMPOSSIBLE: 3}
_BY_RANK = {v: k for k, v in _RANK.items()}

#: 태양 고도 상태 → (등급, 사람이 읽는 하늘 설명). 근거: 모듈 docstring 1절.
_SKY = {
    0: (OPTIMAL, "완전한 밤이라 은하수·성운까지 볼 수 있어요"),
    1: (GOOD, "하늘이 충분히 어두워 대부분의 별이 보여요"),
    2: (LIMITED, "아직 완전히 어둡진 않지만 밝은 별과 별자리는 보이기 시작해요"),
    3: (IMPOSSIBLE, "해가 진 지 얼마 안 돼 하늘이 밝아요 — 가장 밝은 별·행성만 겨우 보입니다"),
    4: (IMPOSSIBLE, "아직 낮이에요 — 해가 떠 있습니다"),
}


# --- 보조 ---------------------------------------------------------------------

def _km(m: float) -> str:
    """시정을 사람이 읽는 문자열로. 반올림이 경계를 넘어 실제보다 좋아 보이지
    않도록 절사한다(9,999 m 를 '10.0km' 로 쓰지 않는다)."""
    if m < 1_000:
        return f"{m:.0f}m"
    return f"{math.floor(m / 100) / 10:.1f}km"


#: 경계 비교용 허용오차. blocking_pct() 의 곱셈에서 부동소수점 오차가 생겨
#: 정확히 경계값인 입력이 한 단계 아래로 떨어지는 것을 막는다.
#: (예: low=30, mid=0 → 30.000000000000004)
_EPS: float = 1e-9


def _ladder(pct: float) -> str:
    """운량(%)을 등급으로. 경계는 모두 문헌값이다(모듈 docstring 4절)."""
    if pct <= CLEAR_PCT + _EPS:
        return OPTIMAL
    if pct <= PHOTOMETRIC_PCT + _EPS:
        return GOOD
    if pct <= SPECTROSCOPIC_PCT + _EPS:
        return LIMITED
    return IMPOSSIBLE


def blocking_pct(low: float, mid: float) -> float:
    """저층운·중층운을 random overlap 가정으로 결합한 차폐율(%).

    두 층은 독립이 아니므로 단순 합이 아니라 여집합의 곱으로 계산한다.
    (Geleyn & Hollingsworth 1979)
    """
    return (1.0 - (1.0 - low / 100.0) * (1.0 - mid / 100.0)) * 100.0


def cloud_verdict(low: float, mid: float, high: float) -> tuple[str, list[str]]:
    """층별 운량으로 구름 등급과 근거 문구를 반환한다.

    Args:
        low:  저층운 비율(%, 0~100). Open-Meteo cloud_cover_low.
        mid:  중층운 비율(%, 0~100). Open-Meteo cloud_cover_mid.
        high: 고층운 비율(%, 0~100). Open-Meteo cloud_cover_high.

    Returns:
        (등급, 근거 문구 목록).
    """
    blocked = blocking_pct(low, mid)
    block_grade = _ladder(blocked)

    # 차폐만으로 이미 불가면 고층운을 볼 것도 없다.
    if block_grade == IMPOSSIBLE:
        return IMPOSSIBLE, [f"낮은 구름이 하늘을 덮고 있어요 (차폐 {blocked:.0f}%)"]

    # 투명도 축. 같은 사다리를 그대로 적용한다(ESO 의 AND 구조).
    haze_grade = _ladder(high)

    # 권운은 반투과이므로 단독으로 불가를 만들지 못한다 — 하한은 '밝은 별 한정'.
    worst = max(_RANK[block_grade], min(_RANK[haze_grade], _RANK[LIMITED]))

    reasons = [f"낮은 구름 적음 (차폐 {blocked:.0f}%)"]
    if _RANK[haze_grade] > _RANK[block_grade]:
        reasons.append(
            f"높은 구름이 하늘을 옅게 덮고 있어요 (고층운 {high:.0f}%) "
            "— 별이 가려지진 않지만 어두운 별은 잘 안 보여요"
        )
    elif high > CLEAR_PCT:
        reasons.append(f"높은 구름 약간 있음 (고층운 {high:.0f}%)")

    return _BY_RANK[worst], reasons


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Judgement:
    """판정 결과.

    verdict:  등급(최적/양호/밝은 별 한정/불가/알 수 없음).
    possible: 밝은 별이라도 볼 수 있는가. 판단 불가면 None.
    reasons:  사람이 읽는 근거 문자열 목록.
    """

    verdict: str
    possible: bool | None
    reasons: list[str] = field(default_factory=list)


# --- 판정 ---------------------------------------------------------------------

def judge(
    state: int,
    cloud_low: float | None,
    cloud_mid: float | None,
    cloud_high: float | None,
    visibility_m: float | None,
) -> Judgement:
    """태양 고도 상태·층별 운량·시정으로 관측 등급을 판정한다.

    Args:
        state: astro.twilight_state 값(0=완전한 밤 ~ 4=낮).
        cloud_low:  저층운 비율(%, 0~100). 없으면 None.
        cloud_mid:  중층운 비율(%, 0~100). 없으면 None.
        cloud_high: 고층운 비율(%, 0~100). 없으면 None.
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

    # 결측은 '불가' 가 아니라 '알 수 없음' 이다(모듈 docstring 6절).
    if cloud_low is None or cloud_mid is None or cloud_high is None:
        return Judgement(UNKNOWN, None, [sky_msg, "구름 정보를 가져오지 못했어요"])

    cloud_grade, cloud_reasons = cloud_verdict(cloud_low, cloud_mid, cloud_high)

    # 어둡기 축과 구름 축 중 나쁜 쪽을 따른다.
    verdict = _BY_RANK[max(_RANK[sky_verdict], _RANK[cloud_grade])]

    if verdict == IMPOSSIBLE:
        return Judgement(IMPOSSIBLE, False, cloud_reasons)

    reasons = [sky_msg, *cloud_reasons]

    # 시정은 등급에 관여하지 않는다 — 참고 정보로만 덧붙인다(docstring 5절).
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

    return Judgement(verdict, True, reasons)


# --- 검증 (API 불필요) --------------------------------------------------------

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cases = [
        # (이름, 상태, low, mid, high, 시정, 기대 등급)
        # 어둡기 축 — 구름이 없을 때 태양 고도가 그대로 등급이 된다.
        ("완전한밤+맑음", 0, 5.0, 0.0, 0.0, 20_000.0, OPTIMAL),
        ("천문박명+맑음", 1, 5.0, 0.0, 0.0, 20_000.0, GOOD),
        ("항해박명+맑음", 2, 5.0, 0.0, 0.0, 20_000.0, LIMITED),
        ("시민박명(너무밝음)", 3, 0.0, 0.0, 0.0, 30_000.0, IMPOSSIBLE),
        ("낮", 4, 0.0, 0.0, 0.0, 30_000.0, IMPOSSIBLE),
        # 차폐 축 — 나쁜 쪽이 등급을 결정한다.
        ("완전한밤+저층운많음", 0, 80.0, 0.0, 0.0, 20_000.0, IMPOSSIBLE),
        ("완전한밤+차폐45%", 0, 45.0, 0.0, 0.0, 20_000.0, LIMITED),
        ("완전한밤+차폐28%", 0, 15.0, 15.0, 0.0, 20_000.0, GOOD),
        ("완전한밤+차폐36%", 0, 20.0, 20.0, 0.0, 20_000.0, LIMITED),
        ("천문박명+차폐45%", 1, 45.0, 0.0, 0.0, 20_000.0, LIMITED),
        # random overlap — 단순 합(64%)이면 불가지만 실제 차폐는 51%다.
        ("저층30+중층30", 0, 30.0, 30.0, 0.0, 20_000.0, IMPOSSIBLE),
        ("저층28+중층28", 0, 28.0, 28.0, 0.0, 20_000.0, LIMITED),
        # 투명도 축 — 고층운은 단독으로 불가를 만들지 못한다.
        ("완전한밤+권운가득", 0, 0.0, 0.0, 100.0, 20_000.0, LIMITED),
        ("완전한밤+권운보통", 0, 0.0, 0.0, 40.0, 20_000.0, LIMITED),
        ("완전한밤+권운약간", 0, 0.0, 0.0, 20.0, 20_000.0, GOOD),
        ("완전한밤+권운없음", 0, 0.0, 0.0, 5.0, 20_000.0, OPTIMAL),
        # 결측 — 불가가 아니라 알 수 없음.
        ("완전한밤+구름데이터없음", 0, None, 0.0, 0.0, 20_000.0, UNKNOWN),
        ("완전한밤+중층데이터없음", 0, 0.0, None, 0.0, 20_000.0, UNKNOWN),
        # 시정 = 참고 정보. 어떤 값이든 등급을 바꾸지 않는다.
        ("완전한밤+안개", 0, 10.0, 0.0, 0.0, 400.0, OPTIMAL),
        ("천문박명+안개", 1, 10.0, 0.0, 0.0, 400.0, GOOD),
        ("항해박명+안개", 2, 10.0, 0.0, 0.0, 400.0, LIMITED),
        ("완전한밤+연무", 0, 10.0, 0.0, 0.0, 5_000.0, OPTIMAL),
        ("완전한밤+시정없음", 0, 10.0, 0.0, 0.0, None, OPTIMAL),
        # 표기 경계 — 문구만 바뀌고 등급은 동일해야 한다.
        ("시정 999m(안개 문구)", 0, 10.0, 0.0, 0.0, 999.0, OPTIMAL),
        ("시정 1000m(연무 문구)", 0, 10.0, 0.0, 0.0, 1_000.0, OPTIMAL),
        ("시정 9999m(연무 문구)", 0, 10.0, 0.0, 0.0, 9_999.0, OPTIMAL),
        ("시정 10000m(맑음 문구)", 0, 10.0, 0.0, 0.0, 10_000.0, OPTIMAL),
        # 사다리 경계 — 절벽이 아니라 단계적으로 내려간다.
        ("차폐 10%", 0, 10.0, 0.0, 0.0, 20_000.0, OPTIMAL),
        ("차폐 11%", 0, 11.0, 0.0, 0.0, 20_000.0, GOOD),
        ("차폐 30%", 0, 30.0, 0.0, 0.0, 20_000.0, GOOD),
        ("차폐 31%", 0, 31.0, 0.0, 0.0, 20_000.0, LIMITED),
        ("차폐 50%", 0, 50.0, 0.0, 0.0, 20_000.0, LIMITED),
        ("차폐 51%", 0, 51.0, 0.0, 0.0, 20_000.0, IMPOSSIBLE),
        # 실제 사례: 1100고지 2026-07-27 01:00 (저층운 다수모델 0%, 시정 140m)
        ("1100고지 07-27 01시", 0, 0.0, 0.0, 0.0, 140.0, OPTIMAL),
    ]

    failed = 0
    for name, st, lo, mi, hi, vis, expected in cases:
        r = judge(st, lo, mi, hi, vis)
        ok = r.verdict == expected
        failed += not ok
        mark = {True: "가능", False: "불가", None: "미상"}[r.possible]
        print(f"{'PASS' if ok else 'FAIL'} [{name}] -> {r.verdict}({mark})"
              f"{'' if ok else f', 기대={expected}'} : {', '.join(r.reasons)}")

    # 불변식 1: 시정은 등급을 바꾸지 않는다.
    for st in (0, 1, 2):
        base = judge(st, 0.0, 0.0, 0.0, 20_000.0).verdict
        for vis in (0.0, 50.0, 999.0, 1_000.0, 9_999.0, None):
            got = judge(st, 0.0, 0.0, 0.0, vis)
            assert got.possible, f"시정 {vis} 가 불가를 만들었다"
            assert got.verdict == base, f"시정 {vis} 가 등급을 {base}→{got.verdict} 로 바꿨다"

    # 불변식 2: 고층운은 단독으로 불가를 만들지 못한다.
    for hi in range(0, 101, 10):
        got = judge(0, 0.0, 0.0, float(hi), 20_000.0)
        assert got.verdict != IMPOSSIBLE, f"고층운 {hi}% 가 단독으로 불가를 만들었다"

    # 불변식 3: random overlap 은 단순 합보다 크지 않다.
    for lo in range(0, 101, 10):
        for mi in range(0, 101, 10):
            assert blocking_pct(lo, mi) <= lo + mi + 1e-9

    # 불변식 4: 어느 층이든 늘어나면 등급은 나빠지기만 한다(단조성).
    for st in (0, 1, 2):
        for layer in range(3):
            prev = -1
            for pct in range(0, 101, 5):
                args = [0.0, 0.0, 0.0]
                args[layer] = float(pct)
                v = judge(st, *args, 20_000.0).verdict
                cur = _RANK[v]
                assert cur >= prev, f"상태{st} 층{layer} {pct}% 에서 등급이 좋아졌다"
                prev = cur

    # 불변식 5: 어둡기 축보다 좋아질 수 없다.
    for st in (0, 1, 2):
        ceiling = _RANK[_SKY[st][0]]
        for lo in range(0, 101, 10):
            v = judge(st, float(lo), 0.0, 0.0, 20_000.0).verdict
            assert _RANK[v] >= ceiling, f"상태{st} 저층운{lo}% 가 어둡기 상한을 넘었다"

    print(f"\n{len(cases) - failed}/{len(cases)} 통과")
    sys.exit(1 if failed else 0)