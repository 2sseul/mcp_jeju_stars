"""Open-Meteo 기상 조회 (특정 시각의 층별 운량·시정).

judge() 가 소비하는 값만 꺼내 반환한다:
    cloud_cover_low (%)  — 저층운 (차폐 축)
    cloud_cover_mid (%)  — 중층운 (차폐 축)
    cloud_cover_high (%) — 고층운 (투명도 축, 정보성)
    visibility (m)       — 시정 (참고 문구용)

when(tz-aware) 이 속한 정시(hour) 구간의 예보값을 쓴다. 다른 변수(기온·습도 등)는
이 서비스 판정에 쓰지 않으므로 요청조차 하지 않는다. API 호출은 캐시(1h)·재시도로
감싸며, 클라이언트는 모듈 로드 시 단 한 번만 초기화한다.


관측자 표고 보정 (운해 문제)
--------------------------------------------------------------------------
집계 변수 cloud_cover_low 는 지면부터의 저층운을 담으므로, 관측자 **발밑**에 깔린
구름(운해)까지 포함한다. 고지대에서 이는 치명적이다 — 1100고지(해발 1106 m)에서
운해가 600 m 에 깔리면 cloud_cover_low 는 100% 가 되지만, 관측자는 그 위에서 맑은
하늘을 본다(오히려 운해가 아래 도시 광공해를 가려 최상 조건이다).

그래서 표고가 높은 관측지는 기압면 운량(cloud_cover_XXXhPa)과 지오포텐셜
고도(geopotential_height_XXXhPa)를 받아, **관측자 표고보다 높은 기압면만** 골라
층별 운량을 재구성한다. 발밑 구름은 자동으로 빠진다. 새 임계값 없이 기존 밴드
정의(ISCCP 기압 경계)와 random overlap 방식을 그대로 쓴다.

표고 500 m 미만 관측지는 발밑에 뺄 구름이 거의 없어 집계 변수와 결과가 사실상
같으므로, 불필요한 요청을 줄이려 기존 집계 변수를 그대로 쓴다(하이브리드).
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import openmeteo_requests
import requests_cache
from retry_requests import retry

# --- 상수 및 1회 초기화 -------------------------------------------------------

KST = ZoneInfo("Asia/Seoul")

_URL = "https://api.open-meteo.com/v1/forecast"
_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

# 기압면 운량을 재구성할 때 조회할 기압면(hPa). 대류권 전체를 성기게 덮는다.
_PRESSURE_LEVELS = (1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300, 250, 200)

# 저/중/고 밴드의 기압 경계(ISCCP, Open-Meteo 집계 변수와 같은 정의).
# 새 튜닝 값이 아니라 저층운·중층운·고층운을 나누는 표준 경계다.
#   저층운: hPa >= 680      (물방울, 차폐)
#   중층운: 440 <= hPa < 680 (물방울, 차폐)
#   고층운: hPa < 440       (얼음, 정보성)
_LOW_MIN_HPA = 680
_HIGH_MAX_HPA = 440

# 이 표고(m) 이상이면 기압면 방식으로 발밑 구름을 걷어낸다. 물리 상수가 아니라
# "발밑에 뺄 구름이 유의미한가"를 가르는 운영 기준이다(경계 부근은 두 방식이 수렴).
HIGH_SPOT_ELEVATION_M: float = 500.0

# 캐시(1h)+재시도로 감싼 클라이언트 — 모듈 로드 시 1회만 만든다.
_cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
_retry_session = retry(_cache_session, retries=5, backoff_factor=0.2)
_client = openmeteo_requests.Client(session=_retry_session)

# 표고는 좌표당 불변이므로 프로세스 수명 동안 메모이즈한다.
_elev_cache: dict[tuple[float, float], float | None] = {}


# --- 내부 헬퍼 ----------------------------------------------------------------

def _require_aware(when: datetime) -> datetime:
    """tz-aware 인지 검증하고 Asia/Seoul 기준으로 정규화한다."""
    if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
        raise ValueError("when 은 tz-aware datetime 이어야 합니다.")
    return when.astimezone(KST)


def _first(values) -> float | None:
    """numpy 배열의 첫 값을 float 로. 비었거나 NaN 이면 None."""
    if values is None or len(values) == 0:
        return None
    v = float(values[0])
    return None if math.isnan(v) else v


def elevation(lat: float, lon: float, timeout: float = 12.0) -> float | None:
    """관측지 해발 표고(m)를 Open-Meteo Elevation API(90m DEM)로 조회한다.

    좌표당 한 번만 조회하고 메모이즈한다. 실패하면 None — 호출자는 표고 보정 없이
    집계 변수로 폴백한다.
    """
    key = (round(lat, 4), round(lon, 4))
    if key in _elev_cache:
        return _elev_cache[key]
    try:
        url = _ELEVATION_URL + "?" + urllib.parse.urlencode(
            {"latitude": key[0], "longitude": key[1]}
        )
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
        vals = data.get("elevation") or []
        result = float(vals[0]) if vals else None
    except Exception:  # noqa: BLE001 — 표고 조회 실패는 폴백으로 흡수한다
        result = None
    _elev_cache[key] = result
    return result


def _band_of(hpa: float) -> str:
    """기압면(hPa)을 저/중/고 밴드로 분류한다(ISCCP 경계)."""
    if hpa >= _LOW_MIN_HPA:
        return "low"
    if hpa >= _HIGH_MAX_HPA:
        return "mid"
    return "high"


def bands_above_observer(
    levels: list[tuple[float, float | None, float | None]], observer_m: float
) -> dict[str, float | None]:
    """관측자 위 기압면만 골라 저/중/고 밴드별 운량(%)을 재구성한다(순수 함수).

    Args:
        levels: (기압 hPa, 지오포텐셜 고도 m|None, 운량 %|None) 목록.
        observer_m: 관측지 해발 표고(m).

    Returns:
        {"low": .., "mid": .., "high": ..}. 각 밴드값은 그 밴드에서 관측자보다
        높은 층들의 운량 최댓값이다(연직 인접층 최대중첩 가정). 규칙:
          - 관측자 위에 그 밴드의 층이 하나도 없으면 0.0 (머리 위에 그 구름이 없음).
          - 층은 있으나 운량이 전부 결측이면 None (데이터 없음 → judge 가 처리).
    """
    out: dict[str, float | None] = {}
    for band in ("low", "mid", "high"):
        kept = [
            c
            for (hpa, geopot, c) in levels
            if _band_of(hpa) == band and geopot is not None and geopot > observer_m
        ]
        if not kept:
            out[band] = 0.0  # 관측자 위에 이 밴드의 층이 없음 → 가릴 구름 없음
            continue
        present = [c for c in kept if c is not None]
        # 기압면 값은 공간 보간으로 소수가 섞이므로 표기·계산 노이즈를 1자리로 줄인다.
        out[band] = round(max(present), 1) if present else None
    return out


# --- 공개 API -----------------------------------------------------------------

def fetch(lat: float, lon: float, when: datetime) -> dict:
    """when 이 속한 정시의 층별 운량(%)·시정(m)을 조회해 반환한다.

    관측지 표고가 HIGH_SPOT_ELEVATION_M 이상이면 기압면 운량에서 관측자 발밑 층을
    걷어내 저/중/고 운량을 재구성한다(운해 보정). 아니면 집계 변수를 그대로 쓴다.

    Args:
        lat, lon: 관측지 좌표.
        when: 조회할 시각(tz-aware). 분·초는 버리고 정시로 내림한다.

    Returns:
        {"time": datetime, "cloud_cover_low": float | None,
         "cloud_cover_mid": float | None, "cloud_cover_high": float | None,
         "visibility": float | None, "elevation": float | None,
         "cloud_method": "aggregated" | "above_observer"}
        값이 없으면(NaN·범위 밖) 해당 항목은 None 이며, 처리는 호출자(judge)에 맡긴다.
    """
    when = _require_aware(when)
    hour = when.replace(minute=0, second=0, microsecond=0)

    elev = elevation(lat, lon)
    use_levels = elev is not None and elev >= HIGH_SPOT_ELEVATION_M

    # 집계 변수(+시정)는 항상 받는다. 시정은 기압면에 없고, 표고 보정 실패 시 폴백이다.
    # 요청 변수 순서 = 아래 Variables(index) 순서. 바꾸면 같이 바꿀 것.
    hourly = ["cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "visibility"]
    if use_levels:
        hourly += [f"cloud_cover_{L}hPa" for L in _PRESSURE_LEVELS]
        hourly += [f"geopotential_height_{L}hPa" for L in _PRESSURE_LEVELS]

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": hourly,
        "timezone": "Asia/Seoul",
        "start_hour": hour.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": (hour + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
    }
    response = _client.weather_api(_URL, params=params)[0]
    h = response.Hourly()

    low = _first(h.Variables(0).ValuesAsNumpy())
    mid = _first(h.Variables(1).ValuesAsNumpy())
    high = _first(h.Variables(2).ValuesAsNumpy())
    vis = _first(h.Variables(3).ValuesAsNumpy())
    surface_low = low  # 보정 전 지상 저층운(발밑 운해 포함) — 안내 문구에 쓴다
    method = "aggregated"

    if use_levels:
        n = len(_PRESSURE_LEVELS)
        clouds = [_first(h.Variables(4 + i).ValuesAsNumpy()) for i in range(n)]
        geopots = [_first(h.Variables(4 + n + i).ValuesAsNumpy()) for i in range(n)]
        # 지오포텐셜 고도가 하나도 없으면(응답 이상) 집계 변수로 폴백한다.
        if any(g is not None for g in geopots):
            levels = list(zip(_PRESSURE_LEVELS, geopots, clouds))
            bands = bands_above_observer(levels, elev)
            low, mid, high = bands["low"], bands["mid"], bands["high"]
            method = "above_observer"

    return {
        "time": hour,
        "cloud_cover_low": low,
        "cloud_cover_mid": mid,
        "cloud_cover_high": high,
        "visibility": vis,
        "elevation": elev,
        "cloud_method": method,
        "cloud_cover_low_surface": surface_low,
    }


# --- 검증 (실제 API 호출) -----------------------------------------------------

if __name__ == "__main__":
    import sys

    # Windows 콘솔(cp949)에서 한글이 깨지지 않도록 UTF-8로 출력한다.
    # 근본 해결은 환경변수 PYTHONUTF8=1 쪽이다(리눅스/Docker 는 기본 UTF-8).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    def _show(name: str, lat: float, lon: float, when: datetime) -> None:
        data = fetch(lat, lon, when)
        cl, cm, ch = data["cloud_cover_low"], data["cloud_cover_mid"], data["cloud_cover_high"]
        vis = data["visibility"]
        print(f"\n관측지: {name} ({lat}, {lon})  표고 {data['elevation']} m")
        print(f"조회 시각: {data['time']:%Y-%m-%d %H:%M %Z}  방식: {data['cloud_method']}")
        print("-" * 48)
        print(f"저층운: {'데이터 없음' if cl is None else f'{cl:.0f}%'}")
        print(f"중층운: {'데이터 없음' if cm is None else f'{cm:.0f}%'}")
        print(f"고층운: {'데이터 없음' if ch is None else f'{ch:.0f}%'}")
        print(f"시정:   {'데이터 없음' if vis is None else f'{vis / 1000:.1f}km ({vis:.0f}m)'}")

    when = datetime.now(KST).replace(hour=23, minute=0, second=0, microsecond=0)
    _show("제주 도심(저지대)", 33.5097, 126.5219, when)
    _show("1100고지(고지대)", 33.3578, 126.4631, when)

    # --- 순수 함수 검증: 관측자 표고 위 층만 남기는가 --------------------------
    print("\n" + "=" * 48)
    print("bands_above_observer 검증:")
    # (hPa, 지오포텐셜 고도 m, 운량 %) — 1100고지 실측 고도에 가상 운량을 얹는다.
    sample = [
        (1000, 118.0, 90.0),   # 발밑 운해
        (950, 559.0, 90.0),    # 발밑 운해
        (900, 1040.0, 80.0),   # 발밑(1106 아래)
        (850, 1540.0, 10.0),   # 머리 위 저층운
        (800, 2059.0, 0.0),
        (700, 3197.0, 0.0),
        (600, 4472.0, 20.0),   # 머리 위 중층운
        (500, 5913.0, 0.0),
        (400, 7627.0, 40.0),   # 머리 위 고층운(권운)
        (300, 9728.0, 30.0),
    ]
    at_sea = bands_above_observer(sample, 0.0)
    at_peak = bands_above_observer(sample, 1106.0)
    print(f"  해수면(0m)  : {at_sea}")
    print(f"  1100고지(1106m): {at_peak}")
    # 발밑 운해(1000/950/900hPa 90·90·80%)는 1106m 관측자에게서 빠져야 한다.
    assert at_sea["low"] == 90.0, "해수면에선 발밑 운해가 저층운에 잡혀야 한다"
    assert at_peak["low"] == 10.0, "1100고지에선 발밑 운해가 빠지고 850hPa(10%)만 남아야 한다"
    assert at_peak["mid"] == 20.0 and at_peak["high"] == 40.0
    print("  → 관측자 발밑 층 제외 통과")
