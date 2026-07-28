"""nightlight — VIIRS 야간광 근거리 광원 (순수 함수 + 정적 격자 조회).

"절댓값을 판정에 쓰지 않는다"는 원칙의 근거(제로 96%·재샘플링 파생물)는
`server/core/nightlight.py` 모듈 독스트링과 `docs/decisions.md` §1.8.

네트워크는 쓰지 않는다. 격자(`jeju_viirs_grid.npz`)는 전처리된 정적 파일이다.
"""

from __future__ import annotations

import numpy as np

from server.core import nightlight
from server.core.nightlight import NOISE_FLOOR, assess, value_at

# --- 격자 사양 ----------------------------------------------------------------


def test_격자가_문서의_사양과_일치한다():
    # Given: 전처리된 VIIRS 격자에서
    # When: 형상과 픽셀 크기를 보면
    # Then: 311×260 · 15초각(0.004167°)이다 (star_research.md 보유 데이터 사양)
    assert nightlight._GRID.shape == (260, 311)
    assert nightlight._SCALE == 0.004166666666666667


def test_유효_픽셀의_제로_비율이_문서값과_일치한다():
    # Given: 격자의 유효 픽셀(nodata 제외)을 모으면
    grid = nightlight._GRID
    valid = grid[np.abs(grid - nightlight._NODATA) > 1e-3]
    # When: 값이 정확히 0 인 비율을 구하면
    zero_ratio = float((valid == 0).sum()) / valid.size
    # Then: 71.9% 다 — Black Marble 이 0.5 미만을 0 으로 두는 처리의 결과이며,
    #       이것이 "어두운 쪽 분해능은 SQM 이 담당한다"는 역할 분담의 근거다
    assert round(zero_ratio, 3) == 0.719


def test_재샘플링_파생물_근거인_임계_미만_픽셀이_존재한다():
    # Given: 유효 픽셀 중 0 < v < 0.5 구간을 세면
    grid = nightlight._GRID
    valid = grid[np.abs(grid - nightlight._NODATA) > 1e-3]
    sub = int(((valid > 0) & (valid < NOISE_FLOOR)).sum())
    # When: 임계가 살아 있는 원본이라면 이 구간은 비어야 하는데
    # Then: 3,864개가 존재한다 → 보유 파일은 재샘플링 파생물이고,
    #       그래서 픽셀 절댓값을 판정에 쓰지 않는다
    assert sub == 3864


# --- 조회 ---------------------------------------------------------------------


def test_격자_밖은_None을_돌려준다():
    # Given: 제주 격자를 한참 벗어난 좌표가 주어졌을 때
    # When: 조회하면
    # Then: 예외가 아니라 None 이다 ("데이터 없음"으로 서술하기 위함)
    assert assess(31.0, 128.0) is None
    assert value_at(31.0, 128.0) is None


def test_도심은_어두운_오름보다_근거리_광원이_훨씬_크다():
    # Given: 제주시청과 용눈이오름이 주어졌을 때
    city = assess(33.4996, 126.5312)
    oreum = assess(33.4762, 126.8229)
    # When: 반경 1km 최대 복사휘도를 비교하면
    # Then: 도심이 압도적으로 크다 — '밝다'는 신호는 유효하다는 것이 이 축의 전제
    assert city is not None and oreum is not None
    assert city.near_max > oreum.near_max * 10


def test_넓은_반경의_최대는_좁은_반경보다_작지_않다():
    # Given: 임의의 제주 지점에서
    result = assess(33.4331, 126.6906)
    # When: 1km 최대와 3km 최대를 비교하면
    # Then: 포함관계이므로 넓은 쪽이 항상 크거나 같다
    assert result is not None
    assert result.wide_max >= result.near_max


def test_어두운_지점의_0은_어둡다가_아니라_모른다로_서술된다():
    # Given: 근거리 광원이 노이즈 임계 미만인 지점(1100고지)에서
    result = assess(33.3583, 126.4675)
    assert result is not None
    # When: 사람이 읽는 문구를 만들면
    phrase = nightlight.describe(result)
    # Then: '어둡다'로 단정하지 않고 '잡히는 광원이 없다'로만 말한다
    #       (0 은 0.5 미만이라는 뜻일 뿐 밝기를 구별한 값이 아니다)
    assert "어둡" not in phrase
