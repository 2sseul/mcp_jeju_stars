"""Open-Meteo 기상 조회 (특정 시각의 저층운·시정).

judge() 가 소비하는 두 값만 꺼내 반환한다:
    cloud_cover_low (%) — 저층운
    visibility (m)      — 시정

when(tz-aware) 이 속한 정시(hour) 구간의 예보값을 쓴다. 다른 변수(기온·습도 등)는
이 서비스 판정에 쓰지 않으므로 요청조차 하지 않는다. API 호출은 캐시(1h)·재시도로
감싸며, 클라이언트는 모듈 로드 시 단 한 번만 초기화한다.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import openmeteo_requests
import requests_cache
from retry_requests import retry

# --- 상수 및 1회 초기화 -------------------------------------------------------

KST = ZoneInfo("Asia/Seoul")

_URL = "https://api.open-meteo.com/v1/forecast"

# 캐시(1h)+재시도로 감싼 클라이언트 — 모듈 로드 시 1회만 만든다.
_cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
_retry_session = retry(_cache_session, retries=5, backoff_factor=0.2)
_client = openmeteo_requests.Client(session=_retry_session)


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


# --- 공개 API -----------------------------------------------------------------

def fetch(lat: float, lon: float, when: datetime) -> dict:
    """when 이 속한 정시의 저층운(%)·시정(m)을 조회해 반환한다.

    Args:
        lat, lon: 관측지 좌표.
        when: 조회할 시각(tz-aware). 분·초는 버리고 정시로 내림한다.

    Returns:
        {"time": datetime, "cloud_cover_low": float | None, "visibility": float | None}
        time 은 실제로 조회한 정시(KST). 값이 없으면(NaN·범위 밖) 해당 항목은 None
        이며, 그 처리는 호출자(judge)에게 맡긴다.
    """
    when = _require_aware(when)
    hour = when.replace(minute=0, second=0, microsecond=0)

    # 요청 변수 순서 = 아래 Variables(index) 순서. 바꾸면 같이 바꿀 것.
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ["cloud_cover_low", "visibility"],
        "timezone": "Asia/Seoul",
        "start_hour": hour.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": (hour + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
    }
    response = _client.weather_api(_URL, params=params)[0]
    hourly = response.Hourly()

    return {
        "time": hour,
        "cloud_cover_low": _first(hourly.Variables(0).ValuesAsNumpy()),
        "visibility": _first(hourly.Variables(1).ValuesAsNumpy()),
    }


# --- 검증 (실제 API 호출) -----------------------------------------------------

if __name__ == "__main__":
    import sys

    # Windows 콘솔(cp949)에서 한글이 깨지지 않도록 UTF-8로 출력한다.
    # 근본 해결은 환경변수 PYTHONUTF8=1 쪽이다(리눅스/Docker 는 기본 UTF-8).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    JEJU_LAT, JEJU_LON = 33.5097, 126.5219
    # 오늘 밤 22시 무렵을 조회한다.
    when = datetime.now(KST).replace(hour=22, minute=0, second=0, microsecond=0)

    data = fetch(JEJU_LAT, JEJU_LON, when)
    cl, vis = data["cloud_cover_low"], data["visibility"]

    print(f"관측지: 제주 ({JEJU_LAT}, {JEJU_LON})")
    print(f"조회 시각: {data['time']:%Y-%m-%d %H:%M %Z}")
    print("-" * 40)
    print(f"저층운: {'데이터 없음' if cl is None else f'{cl:.0f}%'}")
    print(f"시정:   {'데이터 없음' if vis is None else f'{vis / 1000:.1f}km ({vis:.0f}m)'}")
