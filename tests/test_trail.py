"""탐방로 등급 — 국립공원공단 원문 표를 코드가 그대로 옮겼는지.

임계값이 전부 남의 것이라(`decisions.md` §2.17), 여기서 지키는 것은 **우리가 정한
규칙**이 아니라 **원문과 어긋나지 않았는가**다. 경계값을 하나씩 짚는 이유가 그것이다.
"""

from __future__ import annotations

from server.core import trail


def test_경사도_배점이_지형마다_다르다():
    # Given: 같은 10% 경사여도
    # When: 둘레길·능선부와 계곡·사면부로 나눠 보면
    # Then: 배점표가 다르다 — 원문이 표를 둘로 나눠 놓았다
    assert trail.slope_point(10.0, trail.RIDGE) == 2
    assert trail.slope_point(10.0, trail.SLOPE_SIDE) == 2
    assert trail.slope_point(8.0, trail.SLOPE_SIDE) == 1
    # 둘레길·능선부에는 1점이 없다 — 원문에서 그 칸이 비어 있다
    assert trail.slope_point(0.0, trail.RIDGE) == 2


def test_경사도_경계값():
    # 계곡·사면부: 8이하1 · 8초과~12이하2 · 12초과~25이하3 · 25초과~32이하4 · 32초과5
    side = trail.SLOPE_SIDE
    assert [trail.slope_point(v, side) for v in (8.0, 8.1, 12.0, 12.1)] == [1, 2, 2, 3]
    assert [trail.slope_point(v, side)
            for v in (25.0, 25.1, 32.0, 32.1)] == [3, 4, 4, 5]
    # 둘레길·능선부: 0~10이하2 · 10초과~15이하3 · 15초과~20이하4 · 20초과5
    ridge = trail.RIDGE
    assert [trail.slope_point(v, ridge) for v in (10.0, 10.1, 15.0, 20.0, 20.1)] \
        == [2, 3, 3, 4, 5]


def test_내리막도_같은_배점이다():
    # Given: 관측 자리가 주차장보다 낮아 고도차가 음수일 때
    # When: 배점하면
    # Then: 부호를 떼고 본다 — 내려가는 20%도 20% 다
    assert trail.slope_point(-20.0, trail.SLOPE_SIDE) == 3
    assert trail.slope_point(-20.0, trail.RIDGE) == 4


def test_거리_경계값():
    side, ridge = trail.SLOPE_SIDE, trail.RIDGE
    assert [trail.distance_point(v, side) for v in (500, 501, 1000, 3000, 5000, 5001)] \
        == [1, 2, 2, 3, 4, 5]
    assert [trail.distance_point(v, ridge) for v in (2000, 2001, 8000, 8001)] \
        == [1, 2, 4, 5]


def test_등급_경계값():
    # 원문: 1~1.10미만 매우쉬움 · 1.11~1.60미만 쉬움 · 1.60~2.60미만 보통 ·
    #       2.61~3.1미만 어려움 · 3.1이상 매우어려움
    assert trail.grade_of(1.0) == "매우쉬움"
    assert trail.grade_of(1.11) == "쉬움"
    assert trail.grade_of(1.59) == "쉬움"
    assert trail.grade_of(1.60) == "보통"
    assert trail.grade_of(2.60) == "보통"
    assert trail.grade_of(2.61) == "어려움"
    assert trail.grade_of(3.09) == "어려움"
    assert trail.grade_of(3.10) == "매우어려움"


def test_소요시간을_뺀_가중치로_낸다():
    # Given: 원문 가중치 다섯 중 소요시간(0.154)은 배점표가 없어 뺐을 때
    # When: 남은 넷으로 재면
    # Then: 합이 0.844 이고, 그것으로 나누므로 점수가 1~5 를 유지한다 —
    #   그래야 원문의 등급 경계를 그대로 쓸 수 있다
    assert trail.OMITTED == {"소요시간": 0.154}
    assert round(sum(trail.WEIGHT.values()), 3) == 0.844
    worst = trail.assess(
        slope_percent=99, distance_m=99_000, terrain=trail.SLOPE_SIDE,
        surface=trail.SURFACE[-1], rock=trail.ROCK[-1],
    )
    assert worst.score == 5.0 and worst.grade == "매우어려움"


def test_한_항목이라도_비면_등급을_내지_않는다():
    # Given: 암릉을 아직 안 봤을 때
    # When: 등급을 물으면
    # Then: None — 빈 값에 기본점을 주면 실제보다 쉽게 나오고,
    #   그것을 밤에 초행으로 걷는 사람이 읽는다
    assert trail.assess(
        slope_percent=5, distance_m=1000, terrain=trail.SLOPE_SIDE,
        surface="포장", rock="",
    ) is None
    assert trail.assess(
        slope_percent=5, distance_m=1000, terrain="", surface="포장", rock="없음",
    ) is None


def test_용눈이오름_회귀():
    # Given: 실측 — 1,175m · 고도차 +80m(GLO-90) · 사면부 · 암릉 없음
    # When: 노면을 포장(데크·매트)으로 보면
    # Then: 쉬움. 20분짜리 완만한 오름에 맞는 답이다
    got = trail.assess(
        slope_percent=80 / 1175 * 100, distance_m=1175,
        terrain=trail.SLOPE_SIDE, surface="포장", rock="없음",
    )
    assert got.points == {"slope": 1, "distance": 3, "rock": 1, "surface": 1}
    assert got.score == 1.464
    assert got.grade == "쉬움"
    # 매우쉬움·쉬움은 점수 말고 부가 조건이 붙는데 우리는 그것을 못 본다
    assert "노면폭" in got.unverified
    assert got.partial is True
