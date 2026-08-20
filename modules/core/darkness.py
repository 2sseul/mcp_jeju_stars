"""광공해(어둡기) 축 — 장소의 고정 속성 (순수 조회 + 순수 함수).

"여기가 얼마나 어두운 곳인가"를 **세 신호**로 답한다. 광공해는 도시 확장·가로등
증설로만 바뀌는 **정적(T0) 속성**이라 날짜·시각과 무관하다 — 미래 어느 밤을 계획하든
같은 값이다(갱신은 연 1회 원본 교체뿐).

세 신호 — 같은 물리량을 다른 공간 규모로 잰다
--------------------------------------------------------------------------
    SQM   (이 모듈, Sky Brightness 30초각≈0.9km) — 광역 하늘밝기. 주 기준.
    VIIRS (`nightlight.py`, 15초각≈0.46km)      — 국지 지상광. "근처가 켜져 있나".
    가로등 (`lamps.py`, 점 좌표)                 — 발밑 광원. "눈에 직접 들어오나".

셋을 다 쓰는 이유는 실측으로 확인됐다. 제주 큐레이션 관측지 20곳은 **19곳이 Falchi iv**
로 SQM 만으로는 순위가 갈리지 않는다. 그런데 1100고지 휴게소는 1km 안 가로등이 0개이고
저지오름은 23m 앞에 4개다 — 같은 등급 안에서 실제 체감을 가르는 것이 이 차이다.
반대로 VIIRS·가로등만으로는 판정할 수 없다. 제주 최상급 대역(SQM 21.5~22.0) 픽셀의
96%가 VIIRS 0 이라 어두운 곳끼리 구별이 안 되기 때문이다(`nightlight.py` 참조).
**어두운 쪽의 분해능은 SQM, 밝은 쪽의 국지 분해능은 나머지 둘**이 담당한다.

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
자체는 **아직 보임**, v 부터 **은하수 소실**이다.

종합 점수와 등급 상한 (`score_of` · `assess_site`)
--------------------------------------------------------------------------
세 신호를 0~1 점수로 정규화해 가중합한다(0=완전 암흑, 1=도심). **가중치와 경계는
운영값이다** — 문헌에서 대지 못한다. 다만 다음 근거로 고정했고, 바꿀 때는 아래 검산을
다시 돌려야 한다(`docs/decisions.md` §1.8).

    가중치  SQM 0.60 · 가로등 0.25 · VIIRS 0.15
      - SQM 이 가장 큰 것은 유일하게 peer-reviewed 등급(Falchi)이 붙고 하늘 배경 자체를
        재는 축이기 때문이다.
      - VIIRS 가 가장 작은 것은 SQM 과 순위상관 0.874 로 중복분이 크기 때문이다.

    경계    0.35 (관측지급) · 0.60 (은하수 소실급)
      - 0.35 — 큐레이션 20곳 중 별 보러 가는 오름 15곳이 전부 이 아래, 시설·마을 인접
        5곳(우도·저지오름·별빛누리공원 등)이 이 위로 갈린다.
      - 0.60 — 제주 본섬 표본에서 Falchi v(은하수 소실) 구간의 중앙값 0.613 과 맞물린다.

이 점수는 **등급 상한(cap)**으로만 작용한다. 구름·박명이 정한 등급을 끌어내릴 수는
있어도 올리지는 못한다 — 아무리 어두운 곳이어도 구름이 덮으면 못 보기 때문이다
(가중합을 구름·박명까지 확장하지 않는 이유는 `judge.py` 모듈 독스트링).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from modules import path

from . import lamps as _lamps
from . import nightlight as _nightlight

_GRID_PATH = path.SB_GRID

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

# 격자·아핀·귀속을 모듈 로드 시 1회 로드한다(정적 데이터).
_npz = np.load(_GRID_PATH)
_GRID = _npz["grid"]
_ORIGIN_LON, _ORIGIN_LAT, _SCALE, _NODATA = (float(x) for x in _npz["affine"])
_NROWS, _NCOLS = _GRID.shape

#: attribution 최상위에 축어로 노출할 데이터 귀속(검증 [5] 권고).
SOURCE: str = str(_npz["source"])

#: Falchi 등급을 어두운 쪽부터 나열한 순서. 표·범례가 등급 순서를 스스로 정하지 않고
#: 이 튜플을 따르게 해, 경계표(`_FALCHI_UCD`)와 어긋날 여지를 없앤다.
FALCHI_GRADES: tuple[str, ...] = ("i", "ii", "iii", "iv", "v", "vi")


def falchi_label(grade: str) -> str:
    """Falchi 등급 → 사람이 읽는 설명. 등급표를 밖에서 베끼지 않게 하는 접근자."""
    return _FALCHI_LABEL[grade]


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


# --- 종합 점수 (SQM + VIIRS + 가로등) -----------------------------------------

#: 성분 가중치 — **운영값**(문헌 근거 없음).
#: 근거·검산은 모듈 독스트링과 `docs/decisions.md` §1.8.
W_SQM: float = 0.60
W_LAMP: float = 0.25
W_NIGHTLIGHT: float = 0.15

#: SQM 정규화 양끝. 22.00 은 자연 밤하늘(NATURAL_MCD 와 같은 규약), 18.00 은 도심 수준.
SQM_DARK: float = 22.0
SQM_BRIGHT: float = 18.0

#: 가로등 거리 정규화 양끝(m). 25m 이내면 사실상 광원 아래, 1km 밖은 영향 없음으로 본다.
LAMP_NEAR_M: float = 25.0
LAMP_FAR_M: float = 1_000.0

#: VIIRS 정규화 상한(nW·cm⁻²·sr⁻¹). 하한은 Black Marble 노이즈 임계(0.5)다.
#: 0.5 → 0, 50 → 1 이 되도록 상용로그 2 자릿수를 쓴다.
NIGHTLIGHT_MAX: float = 50.0

#: 등급 상한 경계 — **운영값**.
#: 근거는 모듈 독스트링(큐레이션 관측지 분리 · Falchi v 중앙값).
SCORE_GOOD_CAP: float = 0.35
SCORE_LIMITED_CAP: float = 0.60


def _clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def sqm_part(sqm: float) -> float:
    """SQM → 0~1 광공해 성분. SQM 은 이미 로그 눈금이라 선형 매핑한다."""
    return _clamp01((SQM_DARK - sqm) / (SQM_DARK - SQM_BRIGHT))


def lamp_part(nearest_m: float | None) -> float:
    """최근접 가로등 거리(m) → 0~1 성분. 거리는 로그로 줄어드는 체감에 맞춘다."""
    if nearest_m is None:
        return 0.0
    d = min(max(nearest_m, LAMP_NEAR_M), LAMP_FAR_M)
    return _clamp01(math.log10(LAMP_FAR_M / d) / math.log10(LAMP_FAR_M / LAMP_NEAR_M))


def nightlight_part(near_max: float) -> float:
    """VIIRS 근거리 최대 복사휘도 → 0~1 성분.

    노이즈 임계(0.5) 미만은 전부 0 이다 — 그 아래는 원본이 이미 0 으로 잘라 놓아
    "어둡다"가 아니라 "모른다"이기 때문이다(`nightlight.py` 참조).
    """
    floor = _nightlight.NOISE_FLOOR
    return _clamp01(
        math.log10(max(near_max, floor) / floor) / math.log10(NIGHTLIGHT_MAX / floor)
    )


def score_of(sqm: float, near_max: float, nearest_m: float | None) -> float:
    """세 성분의 가중합(0=완전 암흑, 1=도심). 가중치는 운영값이다."""
    return (
        W_SQM * sqm_part(sqm)
        + W_NIGHTLIGHT * nightlight_part(near_max)
        + W_LAMP * lamp_part(nearest_m)
    )


def cap_of(score: float) -> str:
    """종합 점수 → verdict 등급 **상한**. 등급을 올리지는 못한다.

    judge 의 등급 문자열을 그대로 돌려주므로, 호출부는 이 값과 기존 판정 중
    나쁜 쪽을 취하면 된다.
    """
    if score <= SCORE_GOOD_CAP:
        return "최적"
    if score <= SCORE_LIMITED_CAP:
        return "양호"
    return "밝은 별 한정"


# --- 종합 판정 ----------------------------------------------------------------

@dataclass(frozen=True)
class Site:
    """장소의 어둡기 종합 — 세 신호와 그 합산.

    darkness:   SQM·Falchi 판정(주 기준). 격자 밖이면 None.
    nightlight: VIIRS 근거리 야간광. 격자 밖이면 None.
    lamps:      가로등 근접도. 주변에 없으면 개수 0(항상 값이 있다).
    score:      0~1 종합 광공해 점수. darkness 가 없으면 None.
    cap:        verdict 등급 상한. darkness 가 없으면 None.
    """

    darkness: Darkness | None
    nightlight: _nightlight.NightLight | None
    lamps: _lamps.Lamps
    score: float | None
    cap: str | None


def assess_site(lat: float, lon: float) -> Site:
    """(lat, lon) 의 어둡기 종합 판정 — 세 신호를 모아 점수·상한까지.

    SQM 격자 밖(해상 등)이면 점수를 내지 않는다(score·cap 이 None) — 주 기준이
    빠진 채 보조 축만으로 등급 상한을 매기면 '광원이 안 잡히니 최상급'이라는 거짓
    판정이 나오기 때문이다. 나머지 신호는 그대로 실어 보낸다.
    """
    d = assess(lat, lon)
    n = _nightlight.assess(lat, lon)
    lamp = _lamps.assess(lat, lon)

    if d is None:
        return Site(darkness=None, nightlight=n, lamps=lamp, score=None, cap=None)

    score = score_of(d.sqm, n.near_max if n is not None else 0.0, lamp.nearest_m)
    return Site(
        darkness=d,
        nightlight=n,
        lamps=lamp,
        score=round(score, 3),
        cap=cap_of(score),
    )


def describe_site(site: Site) -> list[str]:
    """어둡기 종합을 사람이 읽는 줄들로. 신호마다 한 줄씩, 없는 신호는 건너뛴다."""
    lines: list[str] = []
    if site.darkness is not None:
        lines.append(describe(site.darkness))
    if site.nightlight is not None:
        lines.append(_nightlight.describe(site.nightlight))
    lines.append(_lamps.describe(site.lamps))
    return lines


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

