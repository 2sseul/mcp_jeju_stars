"""tonight — 밤 단위 집계 (순수 함수).

3시간 기준으로 가능/불가를 매기지 않는다는 것이 이 모듈의 핵심 규율이다
(`docs/decisions.md` §2.6). 테스트도 "시간 수를 그대로 주는가"만 본다.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from server.core.tonight import HourResult, summarize

KST = ZoneInfo("Asia/Seoul")


def H(
    hour: int, verdict: str, possible: bool | None, cloud: float | None
) -> HourResult:
    """테스트용 정시 판정 하나. 날짜는 고정(집계는 날짜에 의존하지 않는다)."""
    when = datetime(2026, 7, 27, hour, 0, tzinfo=KST)
    return HourResult(when, verdict, possible, cloud)


#: 밤 구간 예시 — 20시 흐림 → 21~22시 갬(최적) → 23시 흐림
#: → 00~01시 갬(양호) → 02시 결측
NIGHT = [
    H(20, "불가", False, 90.0),
    H(21, "최적", True, 5.0),
    H(22, "최적", True, 8.0),
    H(23, "불가", False, 70.0),
    H(0, "양호", True, 25.0),
    H(1, "양호", True, 20.0),
    H(2, "알 수 없음", None, None),
]


def test_관측_가능_시간을_세어_돌려준다():
    # Given: 관측 가능 4시간·불가 2시간·결측 1시간인 밤이 주어졌을 때
    # When: 집계하면
    s = summarize(NIGHT)
    # Then: 판정하지 않고 시간 수를 그대로 돌려준다
    assert s["observable_hours"] == 4
    assert s["unknown_hours"] == 1
    assert s["total_hours"] == 7


def test_등급별_분포는_관측_가능_정시만_센다():
    # Given: 최적 2시간·양호 2시간이 관측 가능한 밤에서
    # When: 집계하면
    s = summarize(NIGHT)
    # Then: '불가'·'알 수 없음'은 분포에 들어가지 않는다
    assert s["by_grade"] == {"최적": 2, "양호": 2}


def test_PTB와_STB는_순수_운량_기준으로_센다():
    # Given: 운량이 5·8·25·20 인 정시 4개와 70·90 인 정시, 결측 1개가 있을 때
    # When: 집계하면
    s = summarize(NIGHT)
    # Then: judge 등급이 아니라 운량만 보고 센다(결측은 어느 쪽에도 안 들어감)
    assert s["photometric_hours"] == 4    # ≤30%
    assert s["spectroscopic_hours"] == 4  # ≤50%


def test_PTB는_STB의_부분집합이다():
    # Given: 운량이 임계값 양쪽에 흩어진 밤에서
    mixed = summarize([
        H(20, "최적", True, 5.0),      # PTB · STB
        H(21, "밝은 별 한정", True, 45.0),  # STB 만
        H(22, "불가", False, 80.0),    # 둘 다 아님
        H(23, "알 수 없음", None, None),
    ])
    # When: PTB·STB 시간 수를 비교하면
    # Then: ≤30% 는 ≤50% 의 부분집합이므로 STB 가 항상 크거나 같다
    assert mixed["photometric_hours"] == 1
    assert mixed["spectroscopic_hours"] == 2
    assert mixed["spectroscopic_hours"] >= mixed["photometric_hours"]


def test_연속_관측_창은_불가_시각에서_끊긴다():
    # Given: 21~22시와 00~01시가 관측 가능하고 그 사이 23시가 불가인 밤에서
    # When: 집계하면
    s = summarize(NIGHT)
    # Then: 창이 둘로 나뉘고 각각 2시간이다
    assert len(s["windows"]) == 2
    assert s["windows"][0]["hours"] == 2
    assert s["windows"][1]["hours"] == 2


def test_전부_관측_가능하면_하나의_창으로_이어진다():
    # Given: 20~23시가 모두 관측 가능한 밤에서
    # When: 집계하면
    s = summarize([H(h, "양호", True, 10.0) for h in (20, 21, 22, 23)])
    # Then: 끊김 없이 창 하나 4시간이 된다
    assert len(s["windows"]) == 1
    assert s["windows"][0]["hours"] == 4


def test_입력_순서가_뒤섞여도_같은_결과를_낸다():
    # Given: 같은 밤을 시간 역순으로 넣었을 때
    # When: 집계하면
    forward = summarize(NIGHT)
    backward = summarize(list(reversed(NIGHT)))
    # Then: 내부에서 정렬하므로 결과가 같다
    assert forward == backward


def test_빈_입력은_0시간과_빈_창을_돌려준다():
    # Given: 집계할 정시가 하나도 없을 때 (백야 등)
    # When: 집계하면
    s = summarize([])
    # Then: 예외가 아니라 0 으로 채운 정상 결과가 나온다
    assert s["observable_hours"] == 0
    assert s["total_hours"] == 0
    assert s["windows"] == []
