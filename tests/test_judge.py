"""judge — 한 시각 등급 판정 (순수 함수).

임계값 근거는 `docs/decisions.md` §1.2. 경계값(10/30/50)은 반드시 케이스로 둔다.
"""

from __future__ import annotations

import pytest

from server.core.judge import (
    _RANK,
    _SKY,
    GOOD,
    IMPOSSIBLE,
    LIMITED,
    OPTIMAL,
    UNKNOWN,
    judge,
)

# (이름, 상태, 총운량, 시정, 기대 등급)
CASES = [
    # 어둡기 축 — 구름이 없을 때 태양 고도가 그대로 등급이 된다.
    ("완전한밤+맑음", 0, 5.0, 20_000.0, OPTIMAL),
    ("천문박명+맑음", 1, 5.0, 20_000.0, GOOD),
    ("항해박명+맑음", 2, 5.0, 20_000.0, LIMITED),
    ("시민박명(너무밝음)", 3, 0.0, 30_000.0, IMPOSSIBLE),
    ("낮", 4, 0.0, 30_000.0, IMPOSSIBLE),
    # 차폐 축 — 나쁜 쪽이 등급을 결정한다.
    ("완전한밤+운량80", 0, 80.0, 20_000.0, IMPOSSIBLE),
    ("완전한밤+운량45", 0, 45.0, 20_000.0, LIMITED),
    ("완전한밤+운량28", 0, 28.0, 20_000.0, GOOD),
    ("천문박명+운량45", 1, 45.0, 20_000.0, LIMITED),
    # 결측 — 총운량이 없으면 '불가'가 아니라 '알 수 없음'.
    ("완전한밤+운량데이터없음", 0, None, 20_000.0, UNKNOWN),
    ("천문박명+운량데이터없음", 1, None, 20_000.0, UNKNOWN),
    # 시정 = 참고 정보. 어떤 값이든 등급을 바꾸지 않는다.
    ("완전한밤+안개", 0, 10.0, 400.0, OPTIMAL),
    ("천문박명+안개", 1, 10.0, 400.0, GOOD),
    ("항해박명+안개", 2, 10.0, 400.0, LIMITED),
    ("완전한밤+연무", 0, 10.0, 5_000.0, OPTIMAL),
    ("완전한밤+시정없음", 0, 10.0, None, OPTIMAL),
    # 표기 경계 — 문구만 바뀌고 등급은 동일해야 한다.
    ("시정 999m(안개 문구)", 0, 10.0, 999.0, OPTIMAL),
    ("시정 1000m(연무 문구)", 0, 10.0, 1_000.0, OPTIMAL),
    ("시정 9999m(연무 문구)", 0, 10.0, 9_999.0, OPTIMAL),
    ("시정 10000m(맑음 문구)", 0, 10.0, 10_000.0, OPTIMAL),
    # 사다리 경계 — 절벽이 아니라 단계적으로 내려간다.
    ("운량 10%", 0, 10.0, 20_000.0, OPTIMAL),
    ("운량 11%", 0, 11.0, 20_000.0, GOOD),
    ("운량 30%", 0, 30.0, 20_000.0, GOOD),
    ("운량 31%", 0, 31.0, 20_000.0, LIMITED),
    ("운량 50%", 0, 50.0, 20_000.0, LIMITED),
    ("운량 51%", 0, 51.0, 20_000.0, IMPOSSIBLE),
    # 시정이 무너져도(안개 140m) 등급은 총운량만 따른다 — 시정은 문구 전용.
    ("총운량 0% + 안개 140m", 0, 0.0, 140.0, OPTIMAL),
]


@pytest.mark.parametrize(
    ("state", "cloud", "visibility", "expected"),
    [pytest.param(*c[1:], id=c[0]) for c in CASES],
)
def test_judge_등급이_기대와_일치한다(state, cloud, visibility, expected):
    # Given: 태양 고도 상태·총운량·시정이 주어졌을 때
    # When: 한 시각을 판정하면
    result = judge(state, cloud, visibility)
    # Then: 문헌 임계값이 정한 등급이 나온다
    assert result.verdict == expected


def test_시정은_등급을_바꾸지_않는다():
    # Given: 총운량이 고정된 각 어둡기 상태에 대해
    for state in (0, 1, 2):
        baseline = judge(state, 0.0, 20_000.0).verdict
        # When: 시정만 극단적으로 바꿔가며 판정하면
        for visibility in (0.0, 50.0, 999.0, 1_000.0, 9_999.0, None):
            result = judge(state, 0.0, visibility)
            # Then: 등급도 관측 가능 여부도 변하지 않는다
            assert result.possible, f"시정 {visibility} 가 불가를 만들었다"
            assert result.verdict == baseline, (
                f"시정 {visibility} 가 등급을 {baseline} → {result.verdict} 로 바꿨다"
            )


def test_총운량이_늘면_등급은_나빠지기만_한다():
    # Given: 각 어둡기 상태에서
    for state in (0, 1, 2):
        previous = -1
        # When: 총운량을 0%부터 100%까지 단조 증가시키면
        for pct in range(0, 101, 5):
            current = _RANK[judge(state, float(pct), 20_000.0).verdict]
            # Then: 등급 순위는 절대 좋아지지 않는다(단조성)
            assert current >= previous, (
                f"상태{state} 총운량 {pct}% 에서 등급이 좋아졌다"
            )
            previous = current


def test_등급은_어둡기_축_상한을_넘지_못한다():
    # Given: 각 어둡기 상태의 등급 상한이 정해져 있을 때
    for state in (0, 1, 2):
        ceiling = _RANK[_SKY[state][0]]
        # When: 총운량을 어떻게 주더라도
        for cloud in range(0, 101, 10):
            verdict = judge(state, float(cloud), 20_000.0).verdict
            # Then: 어둡기 축이 정한 상한보다 좋아질 수 없다
            assert _RANK[verdict] >= ceiling, (
                f"상태{state} 총운량{cloud}% 가 어둡기 상한을 넘었다"
            )


def test_결측은_불가가_아니라_알_수_없음이다():
    # Given: 하늘은 완전한 밤인데
    # When: 총운량 데이터가 없으면
    result = judge(0, None, 20_000.0)
    # Then: '불가'로 단정하지 않고 '알 수 없음'이며, 가능 여부도 미상이다
    #       (모르는 것과 나쁜 것을 같은 등급에 두면 관측지 추천 순위가 왜곡된다)
    assert result.verdict == UNKNOWN
    assert result.possible is None


# --- 광공해 상한 (darkness_cap) -----------------------------------------------


def test_광공해_상한이_없으면_기존_판정_그대로다():
    # Given: 완전한 밤 + 맑음이라 '최적'이 나오는 조건에서
    # When: 광공해 상한을 주지 않으면
    # Then: 기존 동작과 같다 (인자를 늘려도 기본 경로는 안 바뀐다)
    assert judge(0, 5.0, 20_000.0).verdict == judge(0, 5.0, 20_000.0, None).verdict


def test_광공해_상한은_등급을_끌어내린다():
    # Given: 하늘·날씨만 보면 '최적'인 조건에서
    # When: 광공해가 '양호'까지로 상한을 걸면
    result = judge(0, 5.0, 20_000.0, "양호")
    # Then: 등급이 그 상한으로 내려가고, 이유가 **장소**에 있음을 밝힌다.
    #       원인마다 처방이 다르다 — 둘레 불빛이면 자리를 옮기고, 달이면 때를 옮긴다
    assert result.verdict == "양호"
    assert any("둘레 불빛" in r for r in result.reasons)


def test_광공해_상한은_등급을_올리지_못한다():
    # Given: 항해박명이라 하늘만으로 이미 '밝은 별 한정'인 조건에서
    # When: 광공해가 아무리 좋아('최적') 상한이 느슨해도
    result = judge(2, 5.0, 20_000.0, "최적")
    # Then: 등급은 올라가지 않는다 — 상한은 내리기만 한다
    assert result.verdict == LIMITED


def test_구름_게이트는_광공해보다_우선한다():
    # Given: 제주에서 가장 어두운 곳이라 상한이 '최적'이어도
    # When: 구름이 하늘을 덮으면
    result = judge(0, 90.0, 20_000.0, "최적")
    # Then: '불가'다 — 구름은 물리적 필연이라 어둡기로 상쇄되지 않는다
    #       (그래서 어둡기를 구름·박명과 가중합하지 않고 상한으로만 받는다)
    assert result.verdict == IMPOSSIBLE
    assert result.possible is False


def test_알_수_없음은_광공해_상한에_영향받지_않는다():
    # Given: 총운량이 결측이라 '알 수 없음'인 조건에서
    # When: 광공해 상한을 걸어도
    result = judge(0, None, 20_000.0, "밝은 별 한정")
    # Then: 여전히 '알 수 없음'이다 — 등급이 아니라 별개 상태이기 때문
    assert result.verdict == UNKNOWN
