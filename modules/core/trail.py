"""탐방로 등급 — 국립공원공단 기준을 그대로 옮긴 순수 함수.

관측지 추천은 안전 문제다(`architecture.md` §0). 주차 지점에서 관측 자리까지 밤에
짐을 들고 걸어야 하는데, 그 길이 얼마나 힘든지를 **우리가 만든 눈금**으로 말하면
근거가 없다. 실제로 그 눈금을 만들어 본 기관이 있으므로 그것을 쓴다.

출처
--------------------------------------------------------------------------
국립공원공단 「탐방로 등급제 정보」(2018-10-01) — 공공데이터 개방자료.
항목마다 1~5점을 매기고 가중평균해 5등급으로 자른다.

    구간경사도  0.286      거리      0.196      암릉·암반  0.193
    노면상태    0.169      소요시간  0.154

**소요시간은 빠져 있다.** 원문에 가중치는 있는데 1~5점을 어떻게 자르는지가 없다.
없는 배점표를 지어내지 않는다(`CLAUDE.md`). 대신 나머지 넷의 가중치를 그 합(0.844)
으로 나눠 쓴다 — 점수가 1~5 범위를 유지하므로 원문의 등급 경계를 그대로 쓸 수 있다.
**이것은 원문과 다르다.** 그래서 `Grade.partial` 이 항상 True 로 나가고, 화면은
"소요시간 항목 제외"를 함께 적는다. 경위는 `decisions.md` §2.17.

무엇을 검증하지 않나
--------------------------------------------------------------------------
원문의 `매우쉬움`·`쉬움` 에는 점수 말고 **부가 조건**이 붙어 있다 — 계단 유무,
노면폭(2m·1.5m·1.0m), 장애인 편의시설. 우리에게 노면폭도 편의시설 자료도 없으므로
그 둘은 확인하지 않는다. 점수가 그 구간에 떨어져도 실제로는 한 단계 아래일 수 있다.
`Grade.unverified` 가 그것을 들고 나간다.

지형 구분이 필요하다
--------------------------------------------------------------------------
경사도와 거리는 **둘레길·능선부**냐 **계곡 및 사면부**냐로 배점표가 갈린다. 같은
1km 가 둘레길에서는 1점, 사면부에서는 3점이다. 제주 오름 등반로는 대개 사면부지만
그것을 코드가 짐작하지 않는다 — 사람이 고르지 않았으면 등급을 내지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 노면상태 1~5점. 원문의 낱말을 줄이지 않고 그대로 쓴다 — 줄이면 '흙'과 '돌'을
#: 가르는 50~80% 라는 기준이 사라진다.
SURFACE: tuple[str, ...] = (
    "포장",          # 1점 단단·매끈한 포장(목재데크, 콘크리트 등)
    "거의 흙",       # 2점 거의 대부분 흙으로 노면이 이루어진 길
    "비교적 흙",     # 3점 비교적 흙으로 노면이 이루어진 길(50~80%)
    "비교적 돌",     # 4점 비교적 돌로 노면이 이루어진 길(50~80%)
    "거의 돌",       # 5점 거의 대부분 돌로 노면이 이루어진 길
)

#: 암릉·암반 1~5점.
ROCK: tuple[str, ...] = (
    "없음",          # 1점 암릉 암반 없음
    "약간의 암반",   # 2점 약간의 암반이 있을 수 있음
    "목재계단",      # 3점 목재계단이 설치된 암릉, 암반
    "로프·사다리",   # 4점 로프, 사다리 등이 설치된 암릉, 암반
    "손 사용",       # 5점 손을 이용해서 오르내리는 암릉, 암반
)

#: 이 이상이면 걷는 것 말고 손발을 더 쓴다 — 목재계단·로프·사다리·손 사용.
#:
#: **소요시간에는 넣지 않는다.** 같은 기울기에서 계단이 흙길보다 느리다는 공표
#: 자료를 찾지 못했고, 부호조차 분명하지 않다 — 탐방로에 계단을 놓는 이유가 맨
#: 비탈보다 걷기 쉬워서다. 기울기 자체는 이미 소요시간에 들어가 있다
#: (`core/elevation.spans` 가 계단의 고도를 잡아낸다).
#:
#: 대신 **얼마나가 계단인가를 그대로 내보낸다**. 잰 사실이라 계수가 필요 없고,
#: 힘든 정도는 이 모듈의 등급이 노면 0.169 · 암릉 0.193 가중치로 이미 말한다.
STAIRS_FROM: int = 2  # ROCK 의 "목재계단" 자리


def is_stairs(rock: str) -> bool:
    """그 구간이 계단·로프 등 손발을 더 쓰는 자리인가."""
    return rock in ROCK and ROCK.index(rock) >= STAIRS_FROM


#: 지형. 경사도·거리 배점표가 이것으로 갈린다.
RIDGE = "둘레길·능선부"
SLOPE_SIDE = "계곡·사면부"
TERRAIN: tuple[str, ...] = (RIDGE, SLOPE_SIDE)

#: 항목별 가중치(원문). 소요시간 0.154 는 배점표가 없어 빼고 나머지를 재정규화한다.
WEIGHT = {"slope": 0.286, "distance": 0.196, "rock": 0.193, "surface": 0.169}
OMITTED = {"소요시간": 0.154}
_TOTAL = sum(WEIGHT.values())

#: 구간경사도 배점 — (상한 %, 점수). 상한을 넘으면 5점.
#: 둘레길·능선부에는 **1점이 없다**(원문에서 그 칸이 비어 있다). 0~10% 가 이미 2점이다.
SLOPE_PCT = {
    RIDGE: ((10.0, 2), (15.0, 3), (20.0, 4)),
    SLOPE_SIDE: ((8.0, 1), (12.0, 2), (25.0, 3), (32.0, 4)),
}

#: 거리 배점 — (상한 m, 점수). 상한을 넘으면 5점.
DISTANCE_M = {
    RIDGE: ((2_000.0, 1), (4_000.0, 2), (6_000.0, 3), (8_000.0, 4)),
    SLOPE_SIDE: ((500.0, 1), (1_000.0, 2), (3_000.0, 3), (5_000.0, 4)),
}

#: 등급 경계 — (미만, 등급). 원문 표의 경계를 그대로 옮긴다.
#: 원문은 `1~1.10미만 / 1.11이상~1.60미만 / 1.60이상~2.60미만 / 2.61이상~3.1미만 /
#: 3.1이상` 이라 1.10~1.11 과 2.60~2.61 에 **틈이 있다**. 틈에 떨어진 점수를 버릴 수는
#: 없으므로 아래 경계로 이어 붙인다 — 원문에 없는 자리를 메운 것이라 여기 적어 둔다.
GRADE = ((1.11, "매우쉬움"), (1.60, "쉬움"), (2.61, "보통"), (3.10, "어려움"))
HARDEST = "매우어려움"

#: 점수만으로는 확정할 수 없는 등급 — 원문이 계단·노면폭·편의시설 조건을 함께 걸어 둔다.
_CONDITIONAL = ("매우쉬움", "쉬움")


@dataclass(frozen=True)
class Grade:
    """탐방로 한 구간(또는 경로 하나)의 등급.

    score:      가중평균 점수(1~5).
    grade:      매우쉬움 · 쉬움 · 보통 · 어려움 · 매우어려움.
    points:     항목별 1~5점. 무엇 때문에 이 등급인지가 여기서 보인다.
    partial:    소요시간 항목을 빼고 낸 값인가. 지금은 **항상 True** 다.
    unverified: 점수 말고 원문이 함께 요구하는 조건 중 우리가 못 본 것들.
                비어 있지 않으면 실제 등급은 한 단계 아래일 수 있다.
    """

    score: float
    grade: str
    points: dict[str, int]
    partial: bool
    unverified: tuple[str, ...]


def _score(value: float, table: tuple[tuple[float, int], ...]) -> int:
    for limit, point in table:
        if value <= limit:
            return point
    return 5


def slope_point(percent: float, terrain: str) -> int:
    """구간경사도 1~5점. `percent` 는 (고도차 / 거리) * 100."""
    return _score(abs(percent), SLOPE_PCT[terrain])


def distance_point(metres: float, terrain: str) -> int:
    return _score(metres, DISTANCE_M[terrain])


def grade_of(score: float) -> str:
    for limit, name in GRADE:
        if score < limit:
            return name
    return HARDEST


def worst(segments) -> tuple[str, str]:
    """구간들에서 **가장 나쁜** 노면과 암릉. 못 고르면 빈 문자열.

    경로 하나에 구간이 여럿인데 등급은 하나다. 평균을 내면 다랑쉬오름처럼 흙길
    사이에 목재계단이 끼어 있는 길이 '흙길'로 뭉개진다 — 밤에 초행으로 걷는 사람이
    걸리는 곳은 제일 나쁜 자리이므로 그쪽을 쓴다.

    `SURFACE`·`ROCK` 은 나쁜 순으로 늘어놓은 목록이라 뒤에 있을수록 나쁘다
    (그 자리가 곧 배점이다). 그래서 '가장 나쁜 것'은 색인이 가장 큰 것이다.
    """
    bad_surface, bad_rock = "", ""
    for segment in segments or ():
        got = segment.get("surface")
        if got in SURFACE and SURFACE.index(got) > _rank(bad_surface, SURFACE):
            bad_surface = got
        got = segment.get("rock")
        if got in ROCK and ROCK.index(got) > _rank(bad_rock, ROCK):
            bad_rock = got
    return bad_surface, bad_rock


def _rank(value: str, table: tuple[str, ...]) -> int:
    """아직 못 고른 값은 -1 — 어떤 실제 값보다도 낮게 둬야 첫 값이 들어온다."""
    return table.index(value) if value in table else -1


def assess(
    *,
    slope_percent: float,
    distance_m: float,
    terrain: str,
    surface: str,
    rock: str,
) -> Grade | None:
    """네 항목으로 등급을 낸다. 하나라도 비면 `None` — 짐작으로 채우지 않는다.

    빈 값에 기본점을 주면(암릉을 안 봤으니 '없음' 1점으로) 등급이 실제보다 쉽게
    나오고, 그것을 밤에 초행으로 걷는 사람이 읽는다.
    """
    if terrain not in TERRAIN or surface not in SURFACE or rock not in ROCK:
        return None

    points = {
        "slope": slope_point(slope_percent, terrain),
        "distance": distance_point(distance_m, terrain),
        "rock": ROCK.index(rock) + 1,
        "surface": SURFACE.index(surface) + 1,
    }
    score = sum(WEIGHT[key] * point for key, point in points.items()) / _TOTAL
    score = round(score, 3)
    grade = grade_of(score)
    unverified = (
        ("계단 유무", "노면폭", "장애인 편의시설") if grade in _CONDITIONAL else ()
    )
    return Grade(
        score=score,
        grade=grade,
        points=points,
        partial=True,
        unverified=unverified,
    )


#: attribution 에 축어로 나갈 귀속.
SOURCE = "국립공원공단 「탐방로 등급제 정보」(2018-10-01)"
