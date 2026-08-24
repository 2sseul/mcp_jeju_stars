"""태양 고도 기반 밤/박명 구간 계산 모듈.

skyfield.almanac.dark_twilight_day 의 구간 값(0~4)을 가공 없이 그대로 노출한다.
이 모듈이 답하는 것은 **천문학적 사실**(지금 태양이 얼마나 내려갔는가)이지,
"별을 볼 수 있는가"라는 정책 판단이 아니다.

구간 값 정의:
    0 = 천문박명 이후 완전한 밤
    1 = 천문박명 (astronomical twilight)
    2 = 항해박명 (nautical twilight)
    3 = 시민박명 (civil twilight)
    4 = 낮

관측 가능 여부 판정은 judge() 소관이다. 예를 들어 항해박명(상태 2)에도
직녀성·견우성 같은 밝은 별은 보인다 — 그런 정책은 이 모듈이 아니라 judge()가
원시 상태값(0~4)을 받아 결정한다. 그래서 여기서는 상태를 깎지 않고 그대로 준다.

날씨·별자리 계산은 이 모듈의 소관이 아니다 — 달빛은 `moon.py`.
성표 파일을 여는 곳은 `ephem.py` 한 곳이다(태양과 달이 같은 파일을 읽는다).
모든 datetime 입출력은 tz-aware(Asia/Seoul) 이다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from skyfield import almanac
from skyfield.api import wgs84

from .ephem import EPH as _eph
from .ephem import TS as _ts
from .ephem import require_aware as _require_aware
from .ephem import span as _span
from .ephem import to_kst as _to_kst

# --- 상수 및 1회 초기화 -------------------------------------------------------

#: 천체력이 실제로 덮는 날짜 범위. DE421 은 무한하지 않아(대략 1900~2053) 범위 밖
#: 시각을 계산하면 skyfield 가 EphemerisRangeError 를 던진다. 하드코딩하지 않고
#: 로드된 파일의 세그먼트에서 읽으므로(`ephem.span`) 천체력을 교체해도 값이 따라온다.
EPHEM_START, EPHEM_END = _span()


def supports(when: datetime) -> bool:
    """when 이 천체력 지원 범위 안인가. 밖이면 박명 계산이 불가능하다."""
    return EPHEM_START <= _require_aware(when) <= EPHEM_END

# 완전한 밤(천문박명 이후)을 의미하는 dark_twilight_day 구간 값.
# 이것은 태양 고도라는 천문학적 사실일 뿐, "관측 가능"이라는 정책이 아니다.
_NIGHT = 0

# '박명 포함 밤'의 상한 상태값. 상태 0~2(완전한 밤·천문박명·항해박명 = 태양 < −6°)를
# 하나의 밤으로 본다. 상태 3(시민박명)·4(낮)는 제외. 밤 단위 집계(tonight)의 시간
# 창으로 쓰며, 이 역시 태양 고도라는 사실일 뿐 관측 가능 판정이 아니다.
_NIGHTISH_MAX = 2


# --- 내부 헬퍼 ----------------------------------------------------------------
# 시각 변환·검증은 `ephem.py` 것을 쓴다 — 태양과 달이 같은 규칙을 써야 두 축의
# 시각이 어긋나지 않는다.

def _twilight_fn(lat: float, lon: float):
    """주어진 좌표에 대한 dark_twilight_day 시간 함수를 만든다."""
    observer = wgs84.latlon(lat, lon)
    return almanac.dark_twilight_day(_eph, observer)


def _segments(fn, start: datetime, end: datetime) -> list[tuple[datetime, int]]:
    """[start, end) 구간의 (구간 시작 시각, 구간 상태) 목록을 만든다.

    각 원소 i 는 [segs[i][0], segs[i+1][0]) 동안 상태가 segs[i][1] 임을 뜻한다.
    첫 원소는 start 시점의 상태로 시작한다.
    """
    t0 = _ts.from_datetime(start)
    t1 = _ts.from_datetime(end)
    times, states = almanac.find_discrete(t0, t1, fn)

    segs: list[tuple[datetime, int]] = [(start, int(fn(t0)))]
    for t, state in zip(times, states):
        segs.append((_to_kst(t), int(state)))
    return segs


# --- 공개 API -----------------------------------------------------------------

def twilight_state(lat: float, lon: float, when: datetime) -> int:
    """when 시점의 박명 구간 값(0=완전한 밤 ~ 4=낮)을 반환한다."""
    when = _require_aware(when)
    fn = _twilight_fn(lat, lon)
    return int(fn(_ts.from_datetime(when)))


def next_dark_start(lat: float, lon: float, when: datetime) -> datetime | None:
    """when 이후 처음으로 상태가 0(완전한 밤)이 되는 시각을 반환한다.

    24시간 안에 그러한 전환이 없으면 None. 이미 밤이더라도 '되는' 시각을
    찾으므로, 현재 밤의 시작이 아니라 다음 밤의 시작을 반환한다.
    """
    when = _require_aware(when)
    fn = _twilight_fn(lat, lon)

    t0 = _ts.from_datetime(when)
    t1 = _ts.from_datetime(when + timedelta(hours=24))
    times, states = almanac.find_discrete(t0, t1, fn)

    for t, state in zip(times, states):
        if int(state) == _NIGHT:
            return _to_kst(t)
    return None


def dark_window(
    lat: float, lon: float, when: datetime
) -> tuple[datetime, datetime] | None:
    """when 이 속한(또는 이후 도래하는) 완전한 밤 구간 (시작, 종료)을 반환한다.

    이 구간은 상태 0(천문박명 이후 완전한 밤)이라는 **천문학적 사실**이다.
    '별을 볼 수 있는 구간'이 아니다 — 항해박명(상태 2)에도 밝은 별은 보이며,
    관측 가능 여부는 judge() 소관이다. 자정을 넘겨 다음 날로 이어지는 경우도
    그대로 (시작, 종료)로 반환한다.

    when 이 이미 밤이면 시작 시각은 과거의 실제 진입 시각을 자르지 않고 그대로
    준다(정보 보존). 잔여 시간이 필요하면 호출자가 end - when 으로 구한다.
    when 이 밤이 아니면(박명·낮) 지난밤이 아니라 이후 처음 도래하는 밤을
    반환한다. 백야 등으로 검색 창(48시간) 내 완전한 밤이 없으면 None.
    """
    when = _require_aware(when)
    fn = _twilight_fn(lat, lon)

    # 현재 밤에 이미 들어와 있을 수 있으므로 과거로 24h, 미래로 48h 훑는다.
    segs = _segments(fn, when - timedelta(hours=24), when + timedelta(hours=48))

    for i, (seg_start, state) in enumerate(segs):
        if state != _NIGHT:
            continue
        # 상태 0 구간의 종료는 다음 전환 시각이다.
        if i + 1 >= len(segs):
            continue  # 종료 경계를 못 찾으면(구간이 창을 벗어남) 건너뛴다.
        seg_end = segs[i + 1][0]

        # when 이 속한 밤이거나, when 이후 도래하는 첫 밤이면 채택한다.
        if seg_end > when:
            return (seg_start, seg_end)
    return None


def night_window(
    lat: float, lon: float, when: datetime
) -> tuple[datetime, datetime] | None:
    """when 이 속한(또는 이후 도래하는) '박명 포함 밤' 구간 (시작, 종료)을 반환한다.

    태양이 −6° 아래인 구간(완전한 밤+천문박명+항해박명, 상태 0/1/2)을 **하나로 병합**한
    넓은 밤이다. 시민박명(−6~0°)·낮은 제외한다. '오늘 밤 볼 수 있나'를 시간별로 집계할 때
    시간 창으로 쓴다 — dark_window(상태 0만)보다 넓어, 여름처럼 완전한 밤이 짧은 철에도
    이른 저녁 박명의 밝은 별 관측 시간을 포함한다.

    dark_window 와 마찬가지로 이것은 **천문학적 사실**(태양 고도)이지 관측 가능 판정이
    아니다. when 이 이미 밤이면 과거 진입 시각을 자르지 않고 그대로 준다. when 이 밤이
    아니면 이후 처음 도래하는 밤을 반환한다. 검색 창(48h) 내 없으면 None.
    """
    when = _require_aware(when)
    fn = _twilight_fn(lat, lon)

    # 현재 밤에 이미 들어와 있을 수 있으므로 과거로 24h, 미래로 48h 훑는다.
    segs = _segments(fn, when - timedelta(hours=24), when + timedelta(hours=48))

    # 상태 ≤ 2 인 연속 구간을 극대 런(run)으로 병합한다. 각 seg i 는
    # [segs[i][0], segs[i+1][0]) 동안 그 상태이므로, 이웃한 nightish seg 들을 이어붙인다.
    i, n = 0, len(segs)
    while i < n:
        if segs[i][1] > _NIGHTISH_MAX:
            i += 1
            continue
        j = i
        while j + 1 < n and segs[j + 1][1] <= _NIGHTISH_MAX:
            j += 1
        # 런의 종료는 런 다음(=상태 > 2)의 시작 시각. 그 경계가 창을 벗어나면 건너뛴다.
        if j + 1 < n:
            run = (segs[i][0], segs[j + 1][0])
            if run[1] > when:  # when 이 속한 밤이거나 이후 첫 밤
                return run
        i = j + 1
    return None

