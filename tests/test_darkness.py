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


# --- 종합 점수 (SQM + VIIRS + 가로등) -----------------------------------------


def test_성분은_모두_0에서_1_사이로_묶인다():
    # Given: 정규화 범위를 벗어나는 극단값이 주어졌을 때
    # When: 각 성분을 구하면
    # Then: 0~1 밖으로 나가지 않는다 (가중합이 등급 상한을 넘지 않게 하는 전제)
    assert darkness.sqm_part(25.0) == 0.0  # 자연 밤하늘보다 어두울 수는 없다
    assert darkness.sqm_part(10.0) == 1.0
    assert darkness.lamp_part(5.0) == 1.0  # 5m 앞 가로등 = 최악
    assert darkness.lamp_part(5000.0) == 0.0
    assert darkness.nightlight_part(0.0) == 0.0
    assert darkness.nightlight_part(1e6) == 1.0


def test_가로등이_없으면_광원_성분이_0이다():
    # Given: 반경 안에 가로등이 하나도 없어 최근접 거리가 None 일 때
    # When: 성분을 구하면
    # Then: 0 이다 — '없음'을 최악으로 오해하지 않는다
    assert darkness.lamp_part(None) == 0.0


def test_노이즈_임계_미만_야간광은_0으로_친다():
    # Given: Black Marble 이 0 으로 잘라 버리는 구간(0.5 미만)의 값이 주어졌을 때
    # When: VIIRS 성분을 구하면
    # Then: 0 이다 — 그 아래는 '어둡다'가 아니라 '모른다'이므로 점수를 주지 않는다
    assert darkness.nightlight_part(0.0) == darkness.nightlight_part(0.49) == 0.0


def test_점수가_낮을수록_어두운_곳이다():
    # Given: 제주에서 가장 어두운 급(1100고지)과 도심(제주시청)이 주어졌을 때
    dark = darkness.assess_site(33.3583, 126.4675)
    city = darkness.assess_site(33.4996, 126.5312)
    # When: 종합 점수를 비교하면
    # Then: 어두운 쪽이 확실히 낮다 (0=완전 암흑, 1=도심)
    assert dark.score is not None and city.score is not None
    assert dark.score < 0.2 < city.score


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        pytest.param(0.0, "최적", id="완전 암흑"),
        pytest.param(0.35, "최적", id="경계 0.35 — 관측지급 상한은 포함"),
        pytest.param(0.351, "양호", id="0.35 초과 → 한 단계 내림"),
        pytest.param(0.60, "양호", id="경계 0.60 — 포함"),
        pytest.param(0.601, "밝은 별 한정", id="0.60 초과 → 두 단계 내림"),
        pytest.param(1.0, "밝은 별 한정", id="도심"),
    ],
)
def test_등급_상한_경계가_운영값과_일치한다(score, expected):
    # Given: 종합 점수 경계값이 주어졌을 때 (0.35=관측지급, 0.60=Falchi v 중앙값)
    # When: 등급 상한을 구하면
    # Then: 경계값 자체는 좋은 쪽 등급에 포함되고, 초과하면 한 단계 내려간다
    assert darkness.cap_of(score) == expected


def test_SQM_격자_밖이면_점수를_내지_않는다():
    # Given: SQM(주 기준) 격자를 벗어난 먼 바다 좌표가 주어졌을 때
    site = darkness.assess_site(31.0, 128.0)
    # When: 종합 판정을 구하면
    # Then: 점수·상한이 None 이다 — 보조 축만으로 '광원이 없으니 최상급'이라고
    #       판정하면 거짓이 되기 때문이다
    assert site.darkness is None
    assert site.score is None and site.cap is None


def test_큐레이션_관측지가_시설_인접지보다_점수가_낮다():
    # Given: 별 보러 가는 오름(용눈이오름)과 시설이 붙은 관측지(저지오름)가 주어졌을 때
    #        둘 다 Falchi iv 라 SQM 만으로는 갈리지 않는다
    oreum = darkness.assess_site(33.4762, 126.8229)
    facility = darkness.assess_site(33.3312, 126.2541)
    # When: 종합 점수를 비교하면
    # Then: 국지 광원(가로등 362m vs 23m)이 순위를 가른다 — 세 신호를 쓰는 이유
    assert oreum.darkness.falchi_grade == facility.darkness.falchi_grade == "iv"
    assert oreum.score < facility.score


@pytest.mark.parametrize(
    ("name", "lat", "lon", "expected_score", "expected_cap"),
    [
        pytest.param(
            "1100고지 휴게소", 33.3583, 126.4675, 0.132, "최적", id="가로등 0개"
        ),
        pytest.param("용눈이오름", 33.4762, 126.8229, 0.198, "최적", id="동부 중산간"),
        pytest.param("저지오름", 33.3312, 126.2541, 0.481, "양호", id="23m 앞 가로등"),
        pytest.param("제주시청", 33.4996, 126.5312, 0.823, "밝은 별 한정", id="도심"),
    ],
)
def test_종합_점수_회귀_픽스처(name, lat, lon, expected_score, expected_cap):
    # Given: decisions.md §1.7 에 고정된 지점들이 주어졌을 때
    site = darkness.assess_site(lat, lon)
    # When: 어둡기 종합 점수와 등급 상한을 구하면
    # Then: 대장의 값이 그대로 재현된다 — 가중치·경계를 바꾸면 여기가 먼저 깨진다
    assert site.score == expected_score, f"{name} 점수가 픽스처와 다르다"
    assert site.cap == expected_cap


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
