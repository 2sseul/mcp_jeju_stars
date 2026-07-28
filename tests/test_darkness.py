"""darkness — 광공해 SQM·Falchi (순수 함수 + 정적 격자 조회).

변환식·등급 경계 근거는 `docs/decisions.md` §1.4·§1.5.
회귀 픽스처(용눈이오름·제주시·격자 분포)는 §1.7.

네트워크는 쓰지 않는다. 격자(`jeju_sb_grid.npz`)는 저장소에 있는 정적 파일이다.
"""

from __future__ import annotations

import pytest

from server.core import darkness
from server.core.darkness import (
    NATURAL_MCD,
    ZERO_POINT,
    assess,
    bortle_of,
    falchi_of,
    milky_way_phrase,
    sqm_of,
)

# --- 변환식 -------------------------------------------------------------------


def test_자연광_상수는_영점에서_22등급을_역산한_값이다():
    # Given: lightpollutionmap 영점 규약 1.08e8 mcd/m² 에서
    # When: 자연 밤하늘 22.00 mag/arcsec² 를 역산하면
    derived = ZERO_POINT * 10 ** (-0.4 * 22.0)
    # Then: 코드가 쓰는 상수와 소수 9자리까지 일치한다 (영점·자연광은 한 쌍)
    assert derived == pytest.approx(NATURAL_MCD, abs=1e-9)


def test_인공광이_0이면_자연_밤하늘_22등급이_나온다():
    # Given: 인공 밝기가 전혀 없는 하늘에서
    # When: SQM 으로 변환하면
    # Then: 자연 밤하늘 값 22.00 이 그대로 나온다
    assert sqm_of(0.0) == pytest.approx(22.0, abs=1e-6)


@pytest.mark.parametrize(
    ("artificial_mcd", "expected_sqm"),
    [
        pytest.param(0.0997, 21.50, id="격자 중앙값 p50"),
        pytest.param(2.2084, 19.14, id="격자 최대(제주시)"),
    ],
)
def test_검증_문서의_SQM_분포_양_끝을_재현한다(artificial_mcd, expected_sqm):
    # Given: 원본 래스터에서 확인된 인공 밝기 값이 주어졌을 때
    # When: SQM 으로 변환하면
    # Then: 검증 문서의 분포 값이 소수 둘째자리까지 재현된다
    assert round(sqm_of(artificial_mcd), 2) == expected_sqm


def test_인공광이_밝아질수록_SQM은_작아진다():
    # Given: 인공 밝기를 단조 증가시키면서
    previous = float("inf")
    for artificial in (0.0, 0.01, 0.1, 1.0, 10.0):
        # When: SQM 을 구하면
        current = sqm_of(artificial)
        # Then: SQM 은 계속 작아진다 (SQM 은 클수록 어둡다)
        assert current < previous
        previous = current


# --- Falchi 등급 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("artificial_mcd", "expected_grade"),
    [
        pytest.param(0.0001, "i", id="원시 하늘"),
        pytest.param(0.0017, "i", id="경계 1.7 μcd"),
        pytest.param(0.014, "ii", id="경계 14 μcd"),
        pytest.param(0.087, "iii", id="경계 87 μcd"),
        pytest.param(0.088, "iv", id="87 초과 → iv"),
        pytest.param(0.688, "iv", id="경계 688 μcd"),
        pytest.param(3.0, "v", id="경계 3000 μcd"),
        pytest.param(5.0, "vi", id="3000 초과 → vi"),
    ],
)
def test_Falchi_등급_경계가_문헌값과_일치한다(artificial_mcd, expected_grade):
    # Given: Falchi et al.(2016)의 인공 밝기 경계값이 주어졌을 때
    #        (래스터 단위는 mcd/m², 문헌 경계는 μcd/m² — 1000배 차이)
    # When: 등급을 매기면
    # Then: 경계값 자체는 그 등급에 포함되고, 초과하면 다음 등급으로 넘어간다
    assert falchi_of(artificial_mcd) == expected_grade


def test_Bortle은_SQM이_어두울수록_작은_등급이_된다():
    # Given: 어두운 하늘과 밝은 하늘의 SQM 이 있을 때
    # When: 보조 표기인 Bortle 로 매핑하면
    # Then: 어두울수록 낮은 등급이다 (LPM 매핑 — Bortle 원문 근거 아님)
    assert bortle_of(22.0) < bortle_of(19.18)
    assert bortle_of(19.18) == 6


# --- 격자 조회 ----------------------------------------------------------------


def test_용눈이오름_픽스처를_재현한다():
    # Given: 용눈이오름 좌표가 주어졌을 때
    # When: 격자에서 어둡기를 조회하면
    result = assess(33.4762, 126.8229)
    # Then: 검증 문서의 SQM 21.2 대역·Falchi iv 근처가 나온다(픽셀 편차 허용)
    assert result is not None
    assert 20.8 <= result.sqm <= 21.6
    assert result.falchi_grade in ("iii", "iv")


def test_격자_밖은_None을_돌려준다():
    # Given: 제주 격자를 벗어난 먼 바다 좌표가 주어졌을 때
    # When: 조회하면
    # Then: 예외가 아니라 None 이다 ("데이터 없음"으로 서술하기 위함)
    assert assess(31.0, 128.0) is None


def test_격자_전체_SQM_분포가_원본과_일치한다():
    # Given: 전처리된 격자(`jeju_sb_grid.npz`)에서
    import numpy as np

    grid = darkness._GRID
    valid = grid[(grid != darkness._NODATA) & (grid > -900) & ~np.isnan(grid)]
    # When: 유효 픽셀의 SQM 분포를 구하면
    sqm = np.log10((valid + NATURAL_MCD) / ZERO_POINT) / (-0.4)
    # Then: 검증 문서의 min/p50/max 와 소수 둘째자리까지 일치한다
    assert round(float(sqm.min()), 2) == 19.14
    assert round(float(np.percentile(sqm, 50)), 2) == 21.50
    assert round(float(sqm.max()), 2) == 21.93


# --- 은하수 문구 --------------------------------------------------------------


def test_Falchi_iv부터_은하수_문구가_붙는다():
    # Given: 은하수가 흐릿해지는 Falchi iv 지점(용눈이오름)에서
    result = assess(33.4762, 126.8229)
    assert result is not None
    # When: 은하수 문구를 구하면
    phrase = milky_way_phrase(result)
    # Then: iii 이하면 문구가 없고, iv 이상이면 제약을 알리는 문구가 붙는다
    if result.falchi_grade == "iii":
        assert phrase is None
    else:
        assert phrase is not None and phrase.strip()
