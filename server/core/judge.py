"""별 관측 판정 (순수 함수, 정책).

태양 고도 상태와 기상값(총운량·시정)만으로 "지금 별이 얼마나 보이나"를 등급으로
판정한다. API 호출 없이 값만 받아 값만 반환하므로 단독 테스트가 가능하다.

판정은 두 축을 각각 평가한 뒤 가장 나쁜 축을 따른다.

    어둡기 축 (태양 고도)   →  등급 결정
    차폐 축 (총운량)        →  등급 결정
    시정                    →  판정에 관여하지 않음(참고 문구만)

두 축을 하나의 점수로 합치지 않는 것은 ESO 의 구조를 따른 것이다. ESO 는
clear sky 를 "운량 10% 미만 AND 투과율 변동 10% 미만" 으로 두 조건을 각각 건다.
가중합으로 단일 점수를 만들면 검증할 수 없는 계수가 생기므로 쓰지 않는다.
(Kerber et al. 2014 — A&A 2022, 10.1051/0004-6361/202142493 에서 재인용)

**광공해(어둡기 장소 속성)는 예외로 등급에 관여한다** — 단, 위 원칙을 지키려고
가중합에 끼워 넣지 않고 **상한(cap)** 으로만 받는다(`darkness_cap` 인자). 구름·박명이
정한 등급을 끌어내릴 수는 있어도 올리지는 못한다. 광공해 안쪽(SQM·VIIRS·가로등)의
가중합은 `darkness.py` 소관이고, 이 모듈은 그 결과 등급 하나만 받는다. 셋은 같은
물리량(인공 광원)을 다른 규모로 잰 값이라 합치는 것이 성립하지만, 구름·박명은 성격이
다른 축이라 여전히 합치지 않는다.


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


2. 차폐 축 — 총운량
--------------------------------------------------------------------------
구름은 하늘이 아무리 어두워도 별을 물리적으로 가리므로 어둡기 등급과 무관하게
등급을 끌어내린다. 층별(저/중/고) 구분 없이 총운량 한 값으로 판정한다 — 관측자가
실제로 마주하는 건 머리 위를 덮은 구름의 총량이기 때문이다.

알려진 한계 — 총운량은 지면 기준이라 고지대 관측자의 **발밑**에 깔린 운해까지 포함한다.
1100고지 같은 곳에서는 실제보다 나쁘게 평가될 수 있다(운해 위는 오히려 맑고, 아래 도시
광공해까지 가려 준다). 표고 기반 기압면 재구성으로 이를 보정한 적이 있으나, 총운량 단일
축으로 단순화하며 제거했다(common/star_research.md 운해 절).


3. 임계값 사다리 (차폐 축)
--------------------------------------------------------------------------
세 경계 모두 문헌값이다.

    <= 10%   ESO clear sky (Kerber et al. 2014)
    <= 30%   Xin et al. 2020 photometric time block (PTB) 상한
             — Ehgamberdiev et al. 2000 의 clear night 25% 가 이 구간에 든다
    <= 50%   Xin et al. 2020 spectroscopic time block (STB) 상한
    >  50%   관측 불가


4. 시정 — 판정에 관여하지 않는다
--------------------------------------------------------------------------
참고 정보로만 노출한다. 이유는 셋이다.

1) 물리량이 다르다. 예보 시정은 지표 20 m 층의 *수평* 시정인데, 별을 보는 건
   *수직* 방향이다. 관측 지침도 이 둘을 구분해, 하늘이 차폐돼 운고를 못 낼 때
   수평시정이 아니라 수직시정(VV)으로 대체한다.
2) 총운량과 중복이다. 안개는 지면에 닿은 층운이므로, 하늘을 가릴 만큼 두꺼우면
   그 사실이 이미 총운량에 반영된다. 반대로 두께 수십 m 의 얕은 복사안개는
   수평시정만 무너뜨리고 수직으로는 투과한다 — 시정이 독립적으로 더해주는 정보가 없다.
3) 예보 성능이 낮다. ECMWF 는 자사 시정 진단을 "an experimental product ...
   expectations regarding the quality of this product should remain low" 로
   명시하고, 저시정은 "orographic features that are not resolved by the model"
   에 좌우된다고 밝힌다(ECMWF Forecast User Guide, Visibility Parameter).
   한라산 1100고지(모델 격자 해발 1106 m)는 동일 시각 시정이 모델에 따라
   140 m ~ 24 km 로 갈린다.

안개 경계 1 km 는 WMO 의 안개 정의를 따른다. 이 값은 등급이 아니라 문구만 바꾼다.


5. 결측
--------------------------------------------------------------------------
등급을 정하는 건 차폐 축(총운량)이므로, 총운량이 없으면 '불가' 가 아니라
'알 수 없음' 을 낸다. 결측을 '불가'로 두지 않는 것은, 모르는 것과 나쁜 것을 같은
등급으로 두면 관측지 추천에서 데이터 없는 지점이 흐린 지점과 같은 순위로 떨어지기
때문이다.
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


#: 경계 비교용 허용오차. 예보값이 부동소수점이라 정확히 경계값인 입력(30.0 등)이
#: 표현 오차로 한 단계 아래 등급으로 떨어지는 것을 막는다.
_EPS: float = 1e-9


def _ladder(pct: float) -> str:
    """총운량(%)을 등급으로. 경계는 모두 문헌값이다(모듈 docstring 3절)."""
    if pct <= CLEAR_PCT + _EPS:
        return OPTIMAL
    if pct <= PHOTOMETRIC_PCT + _EPS:
        return GOOD
    if pct <= SPECTROSCOPIC_PCT + _EPS:
        return LIMITED
    return IMPOSSIBLE


#: 차폐 등급별 사람이 읽는 구름 문구. 등급과 문구가 어긋나지 않게 등급별로 나눈다
#: (31~50% 는 '밝은 별 한정' 인데 "구름 적음" 이라고 하면 모순). IMPOSSIBLE 은
#: judge 에서 따로 처리하므로 여기 없다.
_CLOUD_PHRASE = {
    OPTIMAL: "구름이 거의 없어요",
    GOOD: "구름이 조금 있어요",
    LIMITED: "구름이 다소 많아요",
}


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
    cloud_cover: float | None,
    visibility_m: float | None,
    darkness_cap: str | None = None,
) -> Judgement:
    """태양 고도 상태·총운량·시정으로 관측 등급을 판정한다.

    Args:
        state: astro.twilight_state 값(0=완전한 밤 ~ 4=낮).
        cloud_cover: 총운량 비율(%, 0~100). 없으면 None. 지면 기준이라 고지대에서는
                     관측자 발밑의 운해도 포함된다(모듈 docstring 2절의 한계).
        visibility_m: 시정(m). 없으면 None.
        darkness_cap: 광공해가 정한 등급 **상한**(darkness.cap_of 반환값). None 이면
                     제한 없음. 등급을 끌어내리기만 하고 올리지는 않는다.

    Returns:
        Judgement(verdict, possible, reasons).
    """
    sky_verdict, sky_msg = _SKY.get(
        state, (IMPOSSIBLE, f"하늘 상태를 알 수 없어요(상태 {state})")
    )

    # 애초에 별을 볼 시간대가 아니면(낮·시민박명) 날씨를 볼 것도 없다.
    if sky_verdict == IMPOSSIBLE:
        return Judgement(IMPOSSIBLE, False, [sky_msg])

    # 결측은 '불가' 가 아니라 '알 수 없음' 이다(모듈 docstring 5절).
    if cloud_cover is None:
        return Judgement(UNKNOWN, None, [sky_msg, "구름 정보를 가져오지 못했어요"])

    cloud_grade = _ladder(cloud_cover)

    # 어둡기 축과 차폐 축 중 나쁜 쪽을 따른다.
    verdict = _BY_RANK[max(_RANK[sky_verdict], _RANK[cloud_grade])]

    # 광공해 상한도 같은 방식으로 나쁜 쪽만 취한다 — 끌어내리기만 하고 올리지 않는다.
    # (구름이 '불가'인데 어두운 장소라고 '양호'로 올라가면 안 된다.)
    capped = verdict
    if darkness_cap in _RANK:
        capped = _BY_RANK[max(_RANK[verdict], _RANK[darkness_cap])]

    if capped == IMPOSSIBLE:
        return Judgement(
            IMPOSSIBLE,
            False,
            [f"구름이 하늘을 덮고 있어요 (총운량 {cloud_cover:.0f}%)"],
        )

    reasons = [sky_msg, f"{_CLOUD_PHRASE[cloud_grade]} (총운량 {cloud_cover:.0f}%)"]

    # 시정은 등급에 관여하지 않는다 — 참고 정보로만 덧붙인다(docstring 4절).
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

    # 광공해가 실제로 등급을 끌어내렸을 때만 그 사실을 밝힌다 — 하늘·구름은 좋은데
    # 등급이 낮은 이유가 장소에 있음을 알려야 '다른 곳으로'를 택할 수 있다.
    if capped != verdict:
        reasons.append(
            f"하늘과 날씨는 '{verdict}'이지만 이 지점은 광공해가 있어 "
            f"'{capped}'까지로 봅니다 — 더 어두운 곳으로 가면 나아져요"
        )

    return Judgement(capped, True, reasons)

