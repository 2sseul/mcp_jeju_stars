"""밤 단위 집계 (순수 함수).

judge() 는 **한 시점**을 판정한다("지금 별 보이나?"). 이 모듈은 그 위에 한 층을 얹어
**밤 전체**를 집계한다("오늘 밤 볼 수 있나?"). 밤 구간의 각 정시를 judge 로 판정한 결과
목록을 받아, 관측 가능한 시간 수·등급별 분포·연속 관측 창을 돌려준다.

핵심 원칙 — **판정하지 않고 시간 수를 그대로 준다.**
--------------------------------------------------------------------------
Xin et al. 2020 은 하룻밤을 사후 평가하는 통계 기준으로, 운량 ≤30% 지속 구간을
photometric time block(PTB), ≤50% 지속 구간을 spectroscopic time block(STB)으로
정의하고 그 합이 3시간을 넘으면 '관측 가능한 밤'으로 본다. 그러나 그 3시간은 천문대가
밤새 관측 프로그램을 돌리는 것을 전제한 기준이다. 맨눈 관측(관광)은 1~2시간이면
충분하므로, 3시간 미만을 '불가'로 잘라내면 실제로 별을 볼 수 있는 밤을 상당수 걸러낸다.

그래서 이 모듈은 3시간 기준으로 가능/불가를 **매기지 않는다**. 관측 가능한 시간 수와
분포를 그대로 반환하고, "충분한가"의 판단은 호출자(LLM·사용자)에게 맡긴다 — 근거 수치를
함께 돌려주어 호출자가 판정을 재구성하게 하는, 이 프로젝트의 일관된 방식이다.

임계값 30/50 은 judge 의 차폐 사다리와 공유한다(같은 문헌값). PTB/STB 시간 수는 순수
운량 기준(judge 의 어둡기 축과 무관)이고, by_grade 는 judge 판정(어둡기 축 포함) 기준이라
서로 다른 정보다 — 둘 다 노출한다.

원 정의의 '10분 중단 허용'은 시간별 예보 데이터로는 판정할 수 없어 적용하지 않는다.
각 정시가 임계값을 넘느냐로만 센다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

# --- 임계값 (judge 와 공유하는 문헌값) ----------------------------------------

#: photometric time block 상한 — 운량 ≤ 이 값인 정시(Xin et al. 2020).
PHOTOMETRIC_PCT: float = 30.0
#: spectroscopic time block 상한 — 운량 ≤ 이 값인 정시(Xin et al. 2020). PTB ⊂ STB.
SPECTROSCOPIC_PCT: float = 50.0


# --- 입력 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class HourResult:
    """밤 구간 한 정시의 판정 결과. judge 결과를 시각·운량과 함께 담은 것.

    time:        해당 정시(tz-aware). 이 정시는 [time, time+1h) 를 대표한다.
    verdict:     judge 등급(최적/양호/밝은 별 한정/불가/알 수 없음).
    possible:    밝은 별이라도 볼 수 있는가(judge.possible). 판단 불가면 None.
    cloud_cover: 총운량 %(PTB/STB 집계용). 없으면 None.
    """

    time: datetime
    verdict: str
    possible: bool | None
    cloud_cover: float | None


# --- 집계 (순수 함수) ---------------------------------------------------------

def summarize(hours: list[HourResult]) -> dict:
    """시간별 판정 목록을 밤 단위 요약으로 집계한다(가능/불가 판정 안 함).

    Args:
        hours: 밤 구간 정시별 HourResult 목록(시간순이 아니어도 됨 — 내부에서 정렬).

    Returns:
        {
          "observable_hours": int,        # possible=True 인 정시 수
          "unknown_hours": int,           # possible=None(데이터 없음) 정시 수
          "total_hours": int,             # 집계 대상 전체 정시 수
          "by_grade": {등급: 시간수, ...}, # 관측 가능 정시의 judge 등급 분포
          "photometric_hours": int,       # 운량 ≤30% 정시 수(PTB, 순수 운량 기준)
          "spectroscopic_hours": int,     # 운량 ≤50% 정시 수(STB, PTB 포함)
          "windows": [                    # 관측 가능 정시의 연속 창(possible=True)
            {"start": iso, "end": iso, "hours": int}, ...
          ],
        }
    """
    ordered = sorted(hours, key=lambda h: h.time)

    observable = [h for h in ordered if h.possible]
    unknown = [h for h in ordered if h.possible is None]

    by_grade = Counter(h.verdict for h in observable)

    photometric = sum(
        1 for h in ordered if h.cloud_cover is not None and h.cloud_cover <= PHOTOMETRIC_PCT
    )
    spectroscopic = sum(
        1 for h in ordered if h.cloud_cover is not None and h.cloud_cover <= SPECTROSCOPIC_PCT
    )

    return {
        "observable_hours": len(observable),
        "unknown_hours": len(unknown),
        "total_hours": len(ordered),
        "by_grade": dict(by_grade),
        "photometric_hours": photometric,
        "spectroscopic_hours": spectroscopic,
        "windows": _windows(observable),
    }


def _windows(observable: list[HourResult]) -> list[dict]:
    """관측 가능 정시들의 연속 창을 만든다. 각 정시는 [time, time+1h) 를 대표하므로
    창의 종료는 마지막 정시 + 1h 다. 정시 간격이 1h 를 넘으면 창을 끊는다."""
    windows: list[dict] = []
    run: list[HourResult] = []

    def flush() -> None:
        if run:
            windows.append({
                "start": run[0].time.isoformat(timespec="minutes"),
                "end": (run[-1].time + timedelta(hours=1)).isoformat(timespec="minutes"),
                "hours": len(run),
            })

    for h in observable:  # 이미 시간순
        if run and h.time - run[-1].time > timedelta(hours=1):
            flush()
            run = []
        run.append(h)
    flush()
    return windows

