"""astro — 박명 구간 (DE421 천체력, 네트워크 불필요).

밤/박명 경계에서 "어느 밤을 고르는가"가 조용히 틀리기 쉬운 지점이라, 특정 날짜의
정확한 시각에 의존하지 않고 **기준 밤 창에 상대적인 시각**으로 불변식을 검증한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from server.core.astro import (
    dark_window,
    next_dark_start,
    night_window,
    twilight_state,
)
from server.core.ephem import KST

JEJU_LAT, JEJU_LON = 33.5097, 126.5219

#: 여름 낮 — 이 시각을 기준으로 "오늘 밤"을 기준 창으로 삼는다.
REF = datetime(2026, 7, 24, 12, 0, tzinfo=KST)

#: find_discrete 의 근찾기는 검색 창에 따라 µs 단위로 흔들리므로 1초 허용오차를 둔다.
TOL = timedelta(seconds=1)


@pytest.fixture(scope="module")
def base_window() -> tuple[datetime, datetime]:
    """기준이 되는 완전한 밤 창."""
    window = dark_window(JEJU_LAT, JEJU_LON, REF)
    assert window is not None, "여름 제주에는 완전한 밤이 존재해야 한다"
    return window


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL


# --- 밤 선택 규칙 -------------------------------------------------------------


def test_깊은_밤_한가운데는_자기_밤을_돌려준다(base_window):
    # Given: 완전한 밤의 한가운데 시각이 주어졌을 때
    start, end = base_window
    middle = start + (end - start) / 2
    # When: 그 시각의 밤 창을 구하면
    got = dark_window(JEJU_LAT, JEJU_LON, middle)
    # Then: 지금 속해 있는 밤을 그대로 준다(시작은 이미 지난 시각)
    assert _same(got, base_window)


def test_저녁_박명은_오늘_밤을_미리_준다(base_window):
    # Given: 아직 완전한 밤이 되기 전(밤 시작 1시간 전) 시각에서
    start, _ = base_window
    evening = start - timedelta(minutes=60)
    # When: 밤 창을 구하면
    got = dark_window(JEJU_LAT, JEJU_LON, evening)
    # Then: 곧 시작될 오늘 밤을 준다
    assert _same(got, base_window)


def test_새벽_박명은_지난밤이_아니라_다음_밤을_준다(base_window):
    # Given: 밤이 이미 끝난 직후(새벽 박명) 시각에서
    _, end = base_window
    morning = end + timedelta(minutes=27)
    # When: 밤 창을 구하면
    got = dark_window(JEJU_LAT, JEJU_LON, morning)
    # Then: 방금 끝난 밤이 아니라 앞으로 올 밤을 준다
    assert got is not None
    assert got[0] >= end - TOL


# --- night_window (박명 포함 밤) ----------------------------------------------


def test_박명_포함_밤은_완전한_밤을_감싼다(base_window):
    # Given: 같은 기준 시각의 완전한 밤 창이 있을 때
    dark_start, dark_end = base_window
    # When: 박명 포함 밤 창(태양 고도 -6도 미만)을 구하면
    window = night_window(JEJU_LAT, JEJU_LON, REF)
    # Then: 완전한 밤을 완전히 포함하는 더 넓은 구간이다
    assert window is not None, "여름 제주에는 박명 포함 밤이 존재해야 한다"
    night_start, night_end = window
    assert night_start <= dark_start + TOL
    assert night_end >= dark_end - TOL


def test_박명_포함_밤_안은_태양이_영하_6도_아래다():
    # Given: 박명 포함 밤 창이 주어졌을 때
    window = night_window(JEJU_LAT, JEJU_LON, REF)
    assert window is not None
    start, end = window
    # When: 창 한가운데의 박명 상태를 보면
    state = twilight_state(JEJU_LAT, JEJU_LON, start + (end - start) / 2)
    # Then: 상태 0/1/2 (완전한 밤·천문박명·항해박명) 안에 있다
    assert state <= 2


# --- 기본 계약 ----------------------------------------------------------------


def test_박명_상태는_0에서_4_사이다():
    # Given: 하루를 두 시간 간격으로 훑으면서
    for hour in range(0, 24, 2):
        when = REF.replace(hour=hour)
        # When: 박명 상태를 구하면
        state = twilight_state(JEJU_LAT, JEJU_LON, when)
        # Then: 항상 0(완전한 밤)~4(낮) 범위 안이다
        assert 0 <= state <= 4


def test_창의_시작은_끝보다_이르다(base_window):
    # Given: 완전한 밤 창과 박명 포함 밤 창에 대해
    night = night_window(JEJU_LAT, JEJU_LON, REF)
    assert night is not None
    # When: 각 창의 시작·끝을 비교하면
    # Then: 언제나 시작 < 끝이다
    assert base_window[0] < base_window[1]
    assert night[0] < night[1]


def test_다음_완전한_밤_시작은_tz_aware다():
    # Given: 여름 낮 기준 시각에서
    # When: 다음 완전한 밤의 시작을 구하면
    start = next_dark_start(JEJU_LAT, JEJU_LON, REF)
    # Then: 값이 있고, 시간대 정보를 가진 datetime 이다
    assert start is not None
    assert start.tzinfo is not None


def test_naive_datetime은_거부한다():
    # Given: 시간대 정보가 없는 datetime 이 주어졌을 때
    naive = datetime(2026, 7, 24, 22, 0)
    # When: 박명 상태를 구하려 하면
    # Then: 조용히 UTC 로 가정하지 않고 예외를 낸다
    with pytest.raises((ValueError, TypeError, AssertionError)):
        twilight_state(JEJU_LAT, JEJU_LON, naive)
