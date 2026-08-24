"""달빛 축 — 달이 하늘 배경을 얼마나 밝히는가 (순수 함수 + 성표 조회).

광공해(`darkness.py`)가 **장소의 고정 속성**이라면 달빛은 **그 밤의 시간 속성**이다.
같은 자리라도 달이 떠 있으면 하늘 배경이 밝아져 은하수가 사라진다. `darkness.py` 가
날짜·시각과 무관한 값만 다루므로(그 모듈 독스트링), 시각에 따라 변하는 이 축은 여기
따로 둔다.

왜 필요한가 — 보름달 밤의 오답
--------------------------------------------------------------------------
달빛을 안 보면 `judge` 는 완전한 밤(태양 -18° 아래)을 그대로 '최적'으로 내고
"은하수·성운까지 볼 수 있어요"라고 답한다. **보름달이 중천에 뜬 밤에는 제주 어디를
가도 은하수가 보이지 않으므로 이대로면 틀린 답이다**(`docs/decisions.md` §2.14).

Krisciunas & Schaefer (1991) — PASP 103, 1033
--------------------------------------------------------------------------
달빛이 대기에 산란돼 하늘 배경에 더해지는 밝기를 예측하는 표준 모형이다. 네 조각을
곱한다.

    I*(a) = 10^(-0.4*(3.84 + 0.026*|a| + 4e-9*a^4))     달의 대기 밖 조도. a=위상각(도)
    f(r)  = 10^5.36*(1.06 + cos^2 r) + 10^(6.15 - r/40) 산란 함수. r=달까지 각거리(도)
                                                        (앞항 Rayleigh · 뒷항 Mie)
    X(Z)  = (1 - 0.96*sin^2 Z)^(-0.5)                   산란광 대기량. Z=천정거리(도)
    B_moon = f(r)*I*(a)*10^(-0.4*k*X(Zm))*(1 - 10^(-0.4*k*X(Z)))   [nanoLambert]

**어느 방향의 하늘을 재는가 — 천정으로 고정한다(Z = 0).** 이유는 둘이다.
① 우리가 가진 광공해 격자(SB)가 **천정 하늘밝기**라, 같은 방향이어야 두 값을 더할 수
있다. ② 관측지를 고르는 시점에 사용자는 아직 그 자리에 없어 볼 방향이 정해지지 않았다
(방위 축을 버린 것과 같은 이유 — `decisions.md` §2.11).
Z=0 이면 r 은 자동으로 달의 천정거리가 된다.

단위 규약 — 두 규약이 0.43% 안에서 맞물린다
--------------------------------------------------------------------------
K&S 는 nanoLambert 로, 이 프로젝트는 mcd/m² 로 밝기를 잰다. 물리 환산은

    1 nL = 1e-9 L = 1e-9 * (1e4/pi) cd/m² = 3.1831e-6 cd/m² = 3.1831e-3 mcd/m²

이고, 이 환산으로 K&S 의 밝기→등급 식(V = (20.7233 - ln(B/34.08))/0.92104)에
V=22.00 을 넣으면 54.008 nL = **0.171913 mcd/m²** 가 나온다. 프로젝트가 쓰는
lightpollutionmap 영점의 자연 밤하늘 값(`darkness.NATURAL_MCD` = 0.171168)과 **0.43%**
차이다. 두 규약이 사실상 같은 눈금이므로, 여기서는 K&S 로 **더해지는 밝기만** 구하고
등급 변환은 프로젝트 규약(`darkness.sqm_of`)에 맡긴다 — 규약을 섞지 않는다.

이 축이 판정에 들어가는 방식
--------------------------------------------------------------------------
- **등급 상한**: 달빛을 더한 유효 밝기를 `darkness` 의 기존 점수·경계에 그대로 통과시켜
  상한을 얻는다(`darkness.assess_sky`). **새 임계값을 만들지 않는다** — 달이 없으면
  정적 점수와 정확히 같은 값이 나오므로, 달빛분만큼만 등급이 내려간다.
- **은하수 문구**: 유효 밝기로 다시 매긴 가시성이 판정 문구를 정정한다.
- **순위는 가르지 않는다**: 제주(약 80km) 안에서 달 고도차는 무시할 수 있어 모든 후보에
  균일하게 작용한다(`decisions.md` §2.14).
  그래서 `darkness_score`(정적)는 건드리지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from skyfield import almanac
from skyfield.api import wgs84

from .ephem import EPH as _eph
from .ephem import TS as _ts
from .ephem import require_aware as _require_aware
from .ephem import to_kst as _to_kst

_earth = _eph["earth"]
_moon = _eph["moon"]

# --- 상수 --------------------------------------------------------------------

#: V 대역 대기 소광계수(mag/airmass). K&S(1991) 가 모형 예시에 쓴 값이며 좋은 관측지의
#: 전형값이다. 문헌값 — 튜닝 대상이 아니다.
EXTINCTION_K: float = 0.172

#: nanoLambert → mcd/m². 1 L = (1e4/pi) cd/m² 에서 나온 물리 환산 상수(규약 아님).
NL_TO_MCD: float = 1e-9 * (1e4 / math.pi) * 1e3

#: 달이 이 고도(도) 아래면 하늘 배경에 더하는 밝기를 0 으로 본다. 지평 아래로 내려가면
#: 직달광이 대기 기둥을 벗어나 K&S 모형의 적용 범위 밖이다(모형은 Zm < 90도 가정).
HORIZON_DEG: float = 0.0

#: 달을 '떴다'고 볼 지평 기준(도). skyfield 기본값과 같은 -0.8333 은 대기 굴절 34분 과
#: 달 반지름 약 16분 을 합친 통상 정의다.
RISE_HORIZON_DEG: float = -0.8333


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Moon:
    """한 시각·한 지점에서 본 달.

    altitude_deg:     지평 위 고도(도). 음수면 떠 있지 않다.
    azimuth_deg:      방위각(도, 북=0 시계방향).
    phase_angle_deg:  위상각 a(도). 0=보름, 180=삭.
    illumination:     밝은 면 비율 0~1 (0.98 = 98% 찬 달).
    added_mcd:        달빛이 **천정 하늘**에 더하는 밝기(mcd/m²). 달이 지평 아래면 0.
    """

    altitude_deg: float
    azimuth_deg: float
    phase_angle_deg: float
    illumination: float
    added_mcd: float

    @property
    def up(self) -> bool:
        """달이 지평 위에 있는가."""
        return self.altitude_deg > HORIZON_DEG


# --- K&S 순수 함수 ------------------------------------------------------------

def airmass(zenith_deg: float) -> float:
    """산란광 대기량 X(Z) = (1 - 0.96*sin^2 Z)^(-0.5). K&S(1991)."""
    s = math.sin(math.radians(zenith_deg))
    return (1.0 - 0.96 * s * s) ** -0.5


def scattering(rho_deg: float) -> float:
    """산란 함수 f(r) [nL / footcandle]. Rayleigh + Mie. K&S(1991)."""
    c = math.cos(math.radians(rho_deg))
    return 10 ** 5.36 * (1.06 + c * c) + 10 ** (6.15 - rho_deg / 40.0)


def illuminance(phase_angle_deg: float) -> float:
    """대기 밖 달 조도 I*(a) [footcandle]. K&S(1991)."""
    a = abs(phase_angle_deg)
    return 10 ** (-0.4 * (3.84 + 0.026 * a + 4e-9 * a ** 4))


def zenith_brightness_mcd(phase_angle_deg: float, altitude_deg: float) -> float:
    """달이 **천정 하늘**에 더하는 밝기(mcd/m²). 달이 지평 아래면 0.

    관측 방향을 천정(Z=0)으로 고정했으므로 달까지 각거리 r 은 달의 천정거리와 같다
    (모듈 독스트링). 값이 0 이면 '달빛 없음'이고, 정적 광공해만 남는다.
    """
    if altitude_deg <= HORIZON_DEG:
        return 0.0
    zenith_moon = 90.0 - altitude_deg
    b_nl = (
        scattering(zenith_moon)
        * illuminance(phase_angle_deg)
        * 10 ** (-0.4 * EXTINCTION_K * airmass(zenith_moon))
        * (1 - 10 ** (-0.4 * EXTINCTION_K))  # X(0) = 1
    )
    return b_nl * NL_TO_MCD


def illumination_of(phase_angle_deg: float) -> float:
    """위상각 a(도) → 밝은 면 비율 0~1. (1 + cos a)/2."""
    return (1.0 + math.cos(math.radians(phase_angle_deg))) / 2.0


# --- 성표 조회 ----------------------------------------------------------------

def assess(lat: float, lon: float, when: datetime) -> Moon:
    """(lat, lon, when) 에서 본 달의 위치·위상과 천정 하늘에 더하는 밝기."""
    when = _require_aware(when)
    t = _ts.from_datetime(when)
    observer = _earth + wgs84.latlon(lat, lon)

    alt, az, _ = observer.at(t).observe(_moon).apparent().altaz()
    alpha = float(almanac.phase_angle(_eph, "moon", t).degrees)

    return Moon(
        altitude_deg=round(float(alt.degrees), 2),
        azimuth_deg=round(float(az.degrees), 1),
        phase_angle_deg=round(alpha, 1),
        illumination=round(illumination_of(alpha), 3),
        added_mcd=round(zenith_brightness_mcd(alpha, float(alt.degrees)), 4),
    )


def window_events(lat: float, lon: float, start: datetime, end: datetime) -> list[dict]:
    """[start, end) 안의 월출·월몰을 시간순으로. 없으면 빈 목록.

    밤 집계가 "달이 몇 시에 져서 그 뒤로 몇 시간이 남는가"를 답하려면 시각이 필요하다.
    지평 기준은 대기 굴절 + 달 반지름을 합친 통상값(`RISE_HORIZON_DEG`).
    """
    start = _require_aware(start)
    end = _require_aware(end)
    observer = _earth + wgs84.latlon(lat, lon)
    t0, t1 = _ts.from_datetime(start), _ts.from_datetime(end)

    events: list[dict] = []
    finders = (("월출", almanac.find_risings), ("월몰", almanac.find_settings))
    for kind, finder in finders:
        times, actual = finder(observer, _moon, t0, t1, RISE_HORIZON_DEG)
        for t, ok in zip(times, actual):
            if not ok:  # 지평을 실제로 넘지 않고 스치기만 한 경우
                continue
            at = _to_kst(t)
            if start <= at < end:
                events.append({"event": kind, "time": at.isoformat(timespec="minutes")})
    events.sort(key=lambda e: e["time"])
    return events


# --- 표현 헬퍼 (문구) ---------------------------------------------------------

def describe(m: Moon) -> str:
    """달 상태를 사람이 읽는 한 줄로."""
    pct = m.illumination * 100
    if not m.up:
        return f"달은 지평 아래예요 (밝은 면 {pct:.0f}%) — 달빛 방해가 없습니다"
    return (
        f"달이 {pct:.0f}% 차서 고도 {m.altitude_deg:.0f}도에 떠 있어요 "
        f"— 하늘 배경이 그만큼 밝아집니다"
    )


def milky_way_phrase(milky_way: str) -> str | None:
    """달빛 때문에 은하수가 가려졌을 때의 판정 문구. 'visible' 이면 None.

    `darkness.milky_way_phrase_from`(광공해가 원인)과 문장이 다른 이유는 **처방이
    다르기 때문**이다. 광공해는 "더 어두운 곳으로 가면 나아진다"가 성립하지만, 달은
    제주 전역에 균일하게 뜨므로 자리를 옮겨도 소용이 없다 — 대신 달이 진 뒤나 다른
    날짜가 답이다. 원인을 뭉뚱그리면 사용자가 헛걸음한다.
    """
    if milky_way == "degraded":
        return (
            "완전한 밤이지만 달빛이 하늘을 밝혀 은하수는 흐릿하게만 보이고 "
            "성운은 어려워요"
        )
    if milky_way == "lost":
        return (
            "완전한 밤이어도 달이 밝아 은하수는 보기 어렵고 밝은 별·행성 위주예요 "
            "— 달이 진 뒤나 그믐 무렵이 좋아요"
        )
    return None


def caveat(milky_way: str, moonless_hours: int = 0) -> str | None:
    """밤 전체 관점의 달빛 주의 문구. 달이 아무것도 깎지 않았으면 None.

    `milky_way_phrase`(순간 판정의 문구 대체용)와 달리 특정 시각을 가정하지 않는
    중립형이라 밤 단위 집계 응답에 한 줄로 덧붙이기에 적합하다.

    Args:
        milky_way: 밤 중 달이 가장 밝은 순간의 은하수 가시성.
        moonless_hours: 밤 창의 정시 중 달이 지평 아래인 수. **이것이 붙어야 문구가
            쓸모 있다** — "은하수가 안 보인다"로 끝나면 사용자가 할 수 있는 것이 없고,
            "달이 지고 나면 몇 시간 남는다"까지 와야 오늘 밤 계획이 선다.
    """
    if milky_way == "degraded":
        base = "오늘 밤은 달빛이 있어 맑은 시간이어도 은하수는 흐릿해요"
    elif milky_way == "lost":
        base = (
            "오늘 밤은 달이 밝아 맑은 시간이어도 은하수는 보기 어려워요 "
            "— 밝은 별·행성 위주로 보게 됩니다"
        )
    else:
        return None
    if moonless_hours > 0:
        return f"{base}. 다만 달이 지평 아래인 시간이 {moonless_hours}시간 있어요"
    return base
