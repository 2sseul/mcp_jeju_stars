"""광공해(어둡기) 판정 — 장소의 고정 속성 (순수 조회 + 순수 함수).

"여기가 얼마나 어두운 하늘인가"를 Sky Brightness 래스터에서 읽어 SQM·Falchi 등급으로
답한다. 광공해는 도시 확장·가로등 증설로만 바뀌는 **정적(T0) 속성**이라 날짜·시각과
무관하다 — 미래 어느 밤을 계획하든 같은 값이다(별도 갱신은 연 1회 래스터 교체뿐).

역할 분담(star_research.md):
    "여기가 좋은 곳인가"는 Sky Brightness(이 모듈)로,
    "어느 쪽을 볼까"는 VIIRS(방위 분석, 후속 P6)로 판단한다.

밝기 두 숫자 (개념 1번)
--------------------------------------------------------------------------
    SQM  : 하늘 배경이 얼마나 어두운가. **클수록 어둡다**(도시 18 … 최상급 22). 로그.
    등급 : 별 하나의 밝기. 작을수록 밝다. (여기선 안 씀)

변환식 (검증 완료 — star_research_validation.md [1][2])
--------------------------------------------------------------------------
래스터 값 = **인공 밝기**(자연광 제외, mcd/m²). 자연 밤하늘을 더해 총밝기를 만든 뒤 SQM 으로.

    총밝기 = 인공밝기 + 0.171168465        (mcd/m², 자연 밤하늘 22.00 mag/arcsec²)
    SQM    = log10(총밝기 / 1.08e8) / (-0.4)

상수 0.171168465 는 lightpollutionmap 의 영점 1.08e8 규약에서 역산한 값이다
(`1.08e8 × 10^(−0.4×22) = 0.171168465`, 10자리 일치). Falchi et al.(2016)의 174 μcd/m²
와 1.6% 다르나, 본 프로젝트는 sb_2025 레이어(LPM 규약)를 쓰므로 두 규약을 혼용하지 않는다.

등급 — Falchi et al.(2016)이 주 기준, Bortle 은 보조
--------------------------------------------------------------------------
Bortle(2001) 원문에는 SQM 경계가 없어(통용 표는 개인 사이트 출처), 판정의 주 기준은
peer-reviewed 등급인 Falchi 를 쓴다. Falchi 는 **인공 밝기 자체**를 6구간으로 정의하므로
(μcd/m² 절대 경계) 영점 규약과 무관하게 래스터 값에 바로 적용된다. Bortle 은
lightpollutionmap 의 SQM 매핑을 따른 **보조 표기**로만 병기한다.

은하수 가시성: 문서(별 예시 절)에 따르면 Falchi iv 는 "자연스러운 외관 상실"이나 은하수
자체는 **아직 보임**, v 부터 **은하수 소실**이다. 이 판정은 verdict 등급을 바꾸지 않고
'은하수까지 보인다'는 문구만 단계적으로 정정하는 데 쓴다(judge 는 장소를 모르는 순수 함수로 유지).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# --- 상수 --------------------------------------------------------------------

#: 자연 밤하늘 밝기(mcd/m²) — 영점 1.08e8 에서 22.00 mag/arcsec² 역산값.
NATURAL_MCD: float = 0.171168465
#: SQM 변환 영점(mcd/m²) — lightpollutionmap 규약.
ZERO_POINT: float = 1.08e8

#: Falchi et al.(2016) 인공 밝기 등급 경계(μcd/m², 상한). 초과하면 다음 등급.
#: (i) ≤1.7 (ii) ≤14 (iii) ≤87 (iv) ≤688 (v) ≤3000 (vi) >3000
_FALCHI_UCD = ((1.7, "i"), (14.0, "ii"), (87.0, "iii"), (688.0, "iv"), (3000.0, "v"))

_FALCHI_LABEL = {
    "i": "원시 하늘 (pristine)",
    "ii": "거의 청정 (지평선 쪽만 열화)",
    "iii": "약간 오염 (천정까지 열화)",
    "iv": "하늘의 자연스러운 외관 상실",
    "v": "은하수 소실 수준",
    "vi": "암순응 불가 수준",
}

#: Falchi 등급 → 은하수 가시성. iv 까지는 보이나(흐릿), v 부터 소실(문서 별 예시 절).
_MILKY_WAY = {
    "i": "visible", "ii": "visible", "iii": "visible",
    "iv": "degraded", "v": "lost", "vi": "lost",
}

#: SQM → Bortle 보조 매핑(lightpollutionmap 기준; Bortle 2001 원문엔 SQM 경계 없음).
_BORTLE_SQM = ((21.99, 1), (21.89, 2), (21.69, 3), (20.49, 4),
               (19.50, 5), (18.94, 6), (18.38, 7))

_GRID_PATH = Path(__file__).resolve().parent.parent / "darkness" / "jeju_sb_grid.npz"

# 격자·아핀·귀속을 모듈 로드 시 1회 로드한다(정적 데이터).
_npz = np.load(_GRID_PATH)
_GRID = _npz["grid"]
_ORIGIN_LON, _ORIGIN_LAT, _SCALE, _NODATA = (float(x) for x in _npz["affine"])
_NROWS, _NCOLS = _GRID.shape

#: attribution 최상위에 축어로 노출할 데이터 귀속(검증 [5] 권고).
SOURCE: str = str(_npz["source"])


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Darkness:
    """장소의 광공해(어둡기) 판정.

    artificial_mcd: 인공 밝기(mcd/m²) — 래스터 원값.
    sqm:            하늘 밝기 등급(클수록 어두움).
    ratio:          인공/자연 밝기 비율(참고).
    falchi_grade:   Falchi 등급 문자열(i~vi) — 주 기준.
    falchi_label:   등급의 사람이 읽는 설명.
    bortle:         Bortle 등급(1~8) — 보조 표기(LPM 매핑).
    milky_way:      은하수 가시성 'visible'|'degraded'|'lost'.
    """

    artificial_mcd: float
    sqm: float
    ratio: float
    falchi_grade: str
    falchi_label: str
    bortle: int
    milky_way: str


# --- 순수 함수 ----------------------------------------------------------------

def sqm_of(artificial_mcd: float) -> float:
    """인공 밝기(mcd/m²) → SQM(mag/arcsec²)."""
    return math.log10((artificial_mcd + NATURAL_MCD) / ZERO_POINT) / -0.4


def falchi_of(artificial_mcd: float) -> str:
    """인공 밝기(mcd/m²) → Falchi 등급(i~vi). 경계는 μcd/m² 절대값."""
    ucd = artificial_mcd * 1000.0
    for upper, grade in _FALCHI_UCD:
        if ucd <= upper:
            return grade
    return "vi"


def bortle_of(sqm: float) -> int:
    """SQM → Bortle 등급(1~8, 보조 표기)."""
    for lower, cls in _BORTLE_SQM:
        if sqm >= lower:
            return cls
    return 8


# --- 격자 조회 ----------------------------------------------------------------

def artificial_at(lat: float, lon: float) -> float | None:
    """(lat, lon) 이 속한 픽셀의 인공 밝기(mcd/m²). 격자 밖·결측이면 None.

    래스터는 좌상단 모서리가 원점인 area 픽셀이라, 픽셀 인덱스는 내림으로 구한다.
    """
    col = int(math.floor((lon - _ORIGIN_LON) / _SCALE))
    row = int(math.floor((_ORIGIN_LAT - lat) / _SCALE))
    if not (0 <= row < _NROWS and 0 <= col < _NCOLS):
        return None
    val = float(_GRID[row, col])
    if val == _NODATA or math.isnan(val) or val <= -900:
        return None
    return val


def assess(lat: float, lon: float) -> Darkness | None:
    """(lat, lon) 의 광공해(어둡기) 판정. 격자 밖·결측(해상 등)이면 None."""
    art = artificial_at(lat, lon)
    if art is None:
        return None
    sqm = sqm_of(art)
    grade = falchi_of(art)
    return Darkness(
        artificial_mcd=round(art, 4),
        sqm=round(sqm, 2),
        ratio=round(art / NATURAL_MCD, 2),
        falchi_grade=grade,
        falchi_label=_FALCHI_LABEL[grade],
        bortle=bortle_of(sqm),
        milky_way=_MILKY_WAY[grade],
    )


# --- 표현 헬퍼 (문구) ---------------------------------------------------------

def describe(d: Darkness) -> str:
    """어둡기 판정을 사람이 읽는 한 줄로."""
    return (
        f"이 지점 하늘 어둡기: SQM {d.sqm} · Falchi {d.falchi_grade}"
        f"({d.falchi_label}) · Bortle {d.bortle} 참고"
    )


def milky_way_phrase_from(milky_way: str, falchi_grade: str) -> str | None:
    """은하수 서술 정정본(완전한 밤=상태0 판정의 '은하수·성운까지' 문구 대체).

    'visible'(정정 불필요)이면 None. verdict 등급은 바꾸지 않는다 — '완전한 밤이면
    은하수까지'라는 이상적 서술을 이 장소의 광공해에 맞춰 낮추기만 한다. 반환 문구는
    원래 문구를 통째로 대체할 수 있게 '완전한 밤' 맥락을 포함한 완결형이다.
    """
    if milky_way == "degraded":
        return (
            "완전한 밤이지만 이 지점은 광공해가 있어(Falchi iv) 은하수는 "
            "흐릿하게만 보이고 성운은 어려워요"
        )
    if milky_way == "lost":
        return (
            f"완전한 밤이어도 이 지점은 광공해가 심해(Falchi {falchi_grade}) "
            "은하수는 보기 어렵고 밝은 별·행성 위주예요"
        )
    return None


def milky_way_phrase(d: Darkness) -> str | None:
    """Darkness 판정으로 은하수 서술 정정본을 만든다(milky_way_phrase_from 위임)."""
    return milky_way_phrase_from(d.milky_way, d.falchi_grade)


def milky_way_caveat(d: Darkness) -> str | None:
    """밤 전체 관점의 은하수 주의 문구('맑은 시간이어도' 광공해로 제약). visible 이면 None.

    milky_way_phrase_from(순간 판정의 '완전한 밤' 문구 대체용)과 달리, 특정 시각을
    가정하지 않는 중립형이라 밤 단위 집계 응답에 한 줄로 덧붙이기에 적합하다.
    """
    if d.milky_way == "degraded":
        return (
            "이 지점은 광공해가 있어(Falchi iv) 맑은 시간이어도 은하수는 흐릿하고 "
            "성운은 보기 어려워요"
        )
    if d.milky_way == "lost":
        return (
            f"이 지점은 광공해가 심해(Falchi {d.falchi_grade}) 맑은 시간이어도 "
            "은하수는 보기 어렵고 밝은 별·행성 위주예요"
        )
    return None


# --- 검증 (API 불필요, 격자 파일만 필요) --------------------------------------

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # 순수 함수 앵커: 검증 문서의 분포 양 끝을 재현하는가.
    assert round(sqm_of(0.0997), 2) == 21.50, sqm_of(0.0997)      # 중앙값 픽셀
    assert round(sqm_of(2.2084), 2) == 19.14, sqm_of(2.2084)      # 최대(제주시)
    # Falchi 경계: 87 μcd 이하 iii, 초과 iv.
    assert falchi_of(0.087) == "iii" and falchi_of(0.088) == "iv"
    assert falchi_of(0.0001) == "i" and falchi_of(5.0) == "vi"

    print(f"격자: {_NROWS}×{_NCOLS}  원점 ({_ORIGIN_LON}, {_ORIGIN_LAT})  scale {_SCALE:.6f}°")
    print(f"출처: {SOURCE}")
    print("-" * 60)

    spots = [
        ("용눈이오름(픽스처 SQM~21.2)", 33.4762, 126.8229),
        ("1100고지", 33.3583, 126.4658),
        ("제주시청(밝음)", 33.4996, 126.5312),
        ("새별오름", 33.3664, 126.3568),
    ]
    for name, lat, lon in spots:
        d = assess(lat, lon)
        if d is None:
            print(f"{name}: 격자 밖/결측")
            continue
        note = milky_way_phrase(d)
        print(f"{name}: SQM {d.sqm} · 비율 {d.ratio} · Falchi {d.falchi_grade}"
              f"({d.falchi_label}) · Bortle {d.bortle} · 은하수 {d.milky_way}")
        if note:
            print(f"    ↳ {note}")

    # 용눈이오름은 문서상 Falchi iv 근처(SQM 21.x). 픽셀 편차 허용해 범위로 검증.
    y = assess(33.4762, 126.8229)
    assert y is not None and 20.8 <= y.sqm <= 21.6, y
    assert y.falchi_grade in ("iii", "iv"), y.falchi_grade

    # 격자 밖(먼 바다)은 None.
    assert assess(31.0, 128.0) is None

    print("-" * 60)
    print("모든 검증 통과")
