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

날씨·달·별자리 계산은 이 모듈의 소관이 아니다.
모든 datetime 입출력은 tz-aware(Asia/Seoul) 이다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from skyfield import almanac
from skyfield.api import Loader, wgs84

# --- 상수 및 1회 초기화 -------------------------------------------------------

KST = ZoneInfo("Asia/Seoul")

# 완전한 밤(천문박명 이후)을 의미하는 dark_twilight_day 구간 값.
# 이것은 태양 고도라는 천문학적 사실일 뿐, "관측 가능"이라는 정책이 아니다.
_NIGHT = 0

# 천체력을 모듈 파일 기준 절대경로(data/ephem)에 고정한다.
# 실행 위치(cwd)와 무관하게 항상 같은 파일을 쓰므로 중복 다운로드가 없다.
_EPHEM_DIR = Path(__file__).resolve().parent.parent / "ephem"

# timescale 과 ephemeris 는 모듈 로드 시 단 한 번만 초기화한다.
_load = Loader(str(_EPHEM_DIR))
_ts = _load.timescale()
_eph = _load("de421.bsp")


# --- 내부 헬퍼 ----------------------------------------------------------------

def _require_aware(when: datetime) -> datetime:
    """tz-aware 인지 검증하고 Asia/Seoul 기준으로 정규화한다."""
    if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
        raise ValueError("when 은 tz-aware(Asia/Seoul) datetime 이어야 합니다.")
    return when.astimezone(KST)


def _twilight_fn(lat: float, lon: float):
    """주어진 좌표에 대한 dark_twilight_day 시간 함수를 만든다."""
    observer = wgs84.latlon(lat, lon)
    return almanac.dark_twilight_day(_eph, observer)


def _to_kst(t) -> datetime:
    """skyfield Time 을 Asia/Seoul tz-aware datetime 으로 변환한다."""
    return t.utc_datetime().astimezone(KST)


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


# --- 검증 ---------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Windows 콘솔(cp949)에서 한글/기호가 깨지지 않도록 UTF-8로 출력한다.
    # 근본 해결은 환경변수 PYTHONUTF8=1 (또는 python -X utf8) 쪽이며, 그러면
    # 이 블록은 불필요해진다. 리눅스/Docker 는 기본이 UTF-8 이라 관여하지 않는다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _STATE_NAMES = {
        0: "완전한 밤 (천문박명 이후)",
        1: "천문박명",
        2: "항해박명",
        3: "시민박명",
        4: "낮",
    }

    JEJU_LAT, JEJU_LON = 33.5097, 126.5219
    now = datetime.now(KST)

    print(f"관측지: 제주 ({JEJU_LAT}, {JEJU_LON})")
    print(f"기준 시각: {now:%Y-%m-%d %H:%M:%S %Z}")
    print("-" * 52)

    state = twilight_state(JEJU_LAT, JEJU_LON, now)
    print(f"현재 상태: {state} — {_STATE_NAMES[state]}")

    nxt = next_dark_start(JEJU_LAT, JEJU_LON, now)
    if nxt is None:
        print("다음 완전한 밤 시작: 24시간 내 없음")
    else:
        print(f"다음 완전한 밤 시작: {nxt:%Y-%m-%d %H:%M:%S}")

    window = dark_window(JEJU_LAT, JEJU_LON, now)
    if window is None:
        print("완전한 밤 구간: 없음")
    else:
        start, end = window
        length = end - start
        print(
            f"완전한 밤 구간: {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M}"
            f"  (약 {length.total_seconds() / 3600:.1f}시간)"
        )

    print("-" * 52)
    print("향후 24시간 박명 구간 전환:")
    fn = _twilight_fn(JEJU_LAT, JEJU_LON)
    t0 = _ts.from_datetime(now)
    t1 = _ts.from_datetime(now + timedelta(hours=24))
    times, states = almanac.find_discrete(t0, t1, fn)
    for t, s in zip(times, states):
        s = int(s)
        print(f"  {_to_kst(t):%m-%d %H:%M}  →  {s} {_STATE_NAMES[s]}")

    # --- 경계 검증: "when 이 속한 밤" vs "이후 도래하는 밤" -------------------
    # dark_window 이 밤/박명 경계에서 어느 밤을 고르는지가 조용히 틀리기 쉬운
    # 지점이다. 특정 날짜의 정확한 시각에 의존하지 않도록, 기준 밤 창을 먼저 구해
    # 그에 상대적인 시각(깊은 밤·저녁 박명·새벽 박명)으로 불변식을 검증한다.
    print("-" * 52)
    print("경계 검증 (밤 선택 규칙):")

    ref = datetime(2026, 7, 24, 12, 0, tzinfo=KST)  # 여름 낮 — 오늘 밤을 기준 창으로
    base = dark_window(JEJU_LAT, JEJU_LON, ref)
    assert base is not None, "여름 제주에는 완전한 밤이 존재해야 한다"
    b_start, b_end = base

    # find_discrete 의 근찾기는 검색 창에 따라 µs 단위로 흔들리므로, 같은 밤인지는
    # 정확 일치가 아니라 1초 허용오차로 본다.
    def _same_window(
        a: tuple[datetime, datetime] | None, b: tuple[datetime, datetime] | None
    ) -> bool:
        if a is None or b is None:
            return a is b
        return (
            abs((a[0] - b[0]).total_seconds()) < 1.0
            and abs((a[1] - b[1]).total_seconds()) < 1.0
        )

    def _probe(label: str, when: datetime, expect: tuple[datetime, datetime]) -> None:
        got = dark_window(JEJU_LAT, JEJU_LON, when)
        st = twilight_state(JEJU_LAT, JEJU_LON, when)
        shown = f"{got[0]:%m-%d %H:%M}~{got[1]:%H:%M}" if got else "None"
        mark = "OK " if _same_window(got, expect) else "X  "
        print(f"  {mark}{label:9} when={when:%m-%d %H:%M}(상태{st}) -> {shown}")
        assert _same_window(got, expect), f"{label}: 기대 {expect}, 실제 {got}"

    # 1) 깊은 밤 한가운데(예: 01:00) — 자기 밤을 그대로, 시작은 과거 진입 시각.
    mid = b_start + (b_end - b_start) / 2
    _probe("깊은 밤", mid, base)

    # 2) 저녁 박명(일몰 후, 아직 밤 아님, 예: 20:00) — 오늘 밤을 미리 준다.
    evening = b_start - timedelta(minutes=60)
    _probe("저녁 박명", evening, base)

    # 3) 새벽 박명(밤이 끝난 직후, 예: 04:30) — 지난밤이 아니라 '다음 밤'을 준다.
    morning = b_end + timedelta(minutes=27)
    nxt = dark_window(JEJU_LAT, JEJU_LON, morning)
    assert nxt is not None and nxt[0] >= b_end, f"새벽 박명은 다음 밤을 줘야 한다: {nxt}"
    _probe("새벽 박명", morning, nxt)

    print("  → 모든 경계 검증 통과")
