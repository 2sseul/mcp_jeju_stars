"""Open-Meteo 기상 조회 (총운량·시정).

judge() 가 소비하는 값만 꺼내 반환한다:
    cloud_cover (%)  — 총운량 (차폐 축)
    visibility (m)   — 시정 (참고 문구용)

구름은 **총운량 한 값으로만** 평가한다. 층별(저/중/고) 운량도, 관측자 표고 기반
운해 보정도 쓰지 않는다 — 관측자가 실제로 마주하는 건 머리 위를 덮은 구름의 총량이고,
층을 나눠 가중합하면 검증 불가능한 계수가 생기기 때문이다. (표고 기반 운해 보정은
이전 버전에 있었으나, 총운량 단일 축으로 단순화하며 제거했다.)

두 형태를 지원한다:
    fetch(when)                — 한 정시. "지금 별 보이나?"(judge 1회)에 쓴다.
    fetch_series(start, end)   — [start, end) 각 정시. "오늘 밤 볼 수 있나?"(시간별
                                 judge 를 모으는 밤 단위 집계)에 쓴다. 한 번의 호출로 받는다.

다른 변수(기온·습도 등)는 판정에 쓰지 않으므로 요청조차 하지 않는다. API 호출은
캐시(1h)·재시도로 감싸며, 클라이언트는 모듈 로드 시 단 한 번만 초기화한다.

캐시가 실제로 맞도록 요청을 정규화한다
--------------------------------------------------------------------------
`requests-cache` 는 **URL 이 같아야** 캐시가 맞는다. 그래서 부르는 쪽의 좌표·시각을
그대로 URL 에 실으면 캐시가 거의 안 맞는다. 두 축을 정규화한다:

1. **좌표를 모델 격자에 맞춘다**(`GRID_LAT_DEG`·`GRID_LON_DEG`). Open-Meteo 는 어차피
   격자 칸으로 스냅해서 답하므로(응답이 쓴 칸 좌표를 돌려준다) **결과가 바뀌지 않고**
   캐시 항목만 합쳐진다. 관측지 63곳이 격자 37칸으로 접힌다.
2. **시각을 하루 창으로 넓힌다**(`_window_of`). 정시 하나만 물으면 시각마다 URL 이
   달라져 "22시"와 "23시"가 각각 외부 호출이 된다. 한 창을 받아 두고 필요한 정시만
   잘라 쓰면, 같은 칸·같은 밤에 대한 모든 질의가 **호출 한 번**을 나눠 쓴다.
   창이 넓어져도 요금은 같다 — Open-Meteo 는 변수 10개 초과 또는 2주 초과일 때만
   호출을 가중하는데, 여기서 쓰는 것은 변수 2개·하루다.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import openmeteo_requests
import requests_cache
from retry_requests import retry

from server import path

# --- 상수 및 1회 초기화 -------------------------------------------------------

KST = ZoneInfo("Asia/Seoul")

_URL = "https://api.open-meteo.com/v1/forecast"

#: 예보 모델의 격자 간격(도). 응답이 실제로 쓴 칸 좌표를 돌려주므로 실측으로 확인했다
#: — 제주 안 6개 좌표를 물어 돌아온 칸이 위도 0.05° · 경도 0.0625° 간격이었다.
#: 요청을 이 칸에 맞춰도 **같은 칸이 나오므로 값이 바뀌지 않는다**.
GRID_LAT_DEG = 0.05
GRID_LON_DEG = 0.0625

#: 캐시 창을 가르는 기준 시각(KST). 밤은 자정을 넘으므로 달력 하루로 자르면 한 밤이
#: 두 창으로 갈려 호출이 두 배가 된다. 정오에 끊어 한 밤이 한 창에 들어오게 한다.
_ANCHOR_HOUR = 12

# 캐시(1h)+재시도로 감싼 클라이언트 — 모듈 로드 시 1회만 만든다.
# 캐시 파일 자리는 `path.py` 가 정한다(작업 디렉터리에 따라 캐시가 갈리지 않게).
# 디렉터리는 여기서 만든다 — 컨테이너가 볼륨을 안 잡아 줬어도 서버는 떠야 한다.
path.CACHE_DIR.mkdir(parents=True, exist_ok=True)
_cache_session = requests_cache.CachedSession(
    str(path.FORECAST_CACHE), expire_after=3600
)
_retry_session = retry(_cache_session, retries=5, backoff_factor=0.2)
_client = openmeteo_requests.Client(session=_retry_session)


# --- 내부 헬퍼 ----------------------------------------------------------------

def _require_aware(when: datetime) -> datetime:
    """tz-aware 인지 검증하고 Asia/Seoul 기준으로 정규화한다."""
    if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
        raise ValueError("when 은 tz-aware datetime 이어야 합니다.")
    return when.astimezone(KST)


def _clean(v) -> float | None:
    """numpy scalar 를 float 로. None·NaN 이면 None."""
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) else f


def snap(lat: float, lon: float) -> tuple[float, float]:
    """좌표를 예보 모델 격자 칸의 중심으로 맞춘다.

    Open-Meteo 는 어차피 격자로 스냅해서 답하므로 **값이 바뀌지 않는다**. 바뀌는 것은
    URL 이고, 그래서 같은 칸 안의 여러 관측지가 캐시 한 항목을 나눠 쓰게 된다.
    """
    return (
        round(lat / GRID_LAT_DEG) * GRID_LAT_DEG,
        round(lon / GRID_LON_DEG) * GRID_LON_DEG,
    )


def _window_of(when: datetime) -> datetime:
    """when 이 속한 캐시 창의 시작(정오 기준). 창은 [반환값, +24h) 이다."""
    day = when.replace(minute=0, second=0, microsecond=0)
    anchor = day.replace(hour=_ANCHOR_HOUR)
    if day.hour < _ANCHOR_HOUR:
        anchor -= timedelta(days=1)
    return anchor


def _windows_covering(start: datetime, end: datetime) -> list[datetime]:
    """[start, end) 를 덮는 캐시 창들의 시작 시각. 대개 하나, 길면 여럿."""
    out, cur = [], _window_of(start)
    while cur < end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _fetch_window(lat: float, lon: float, w_start: datetime) -> list[dict]:
    """캐시 창 하나(24시간)를 통째로 받는다. **외부 호출은 여기서만 일어난다.**

    좌표와 창이 정규화돼 있으므로 URL 이 안정적이고, 그래서 requests-cache 가 맞는다.
    """
    w_end = w_start + timedelta(days=1)
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ["cloud_cover", "visibility"],
        "timezone": "Asia/Seoul",
        "start_hour": w_start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": w_end.strftime("%Y-%m-%dT%H:%M"),
    }
    response = _client.weather_api(_URL, params=params)[0]
    h = response.Hourly()
    clouds = h.Variables(0).ValuesAsNumpy()
    viss = h.Variables(1).ValuesAsNumpy()

    # 응답은 start_hour 부터 Interval(초) 간격이다. 시각축을 창 시작에서 재구성해
    # UTC 오프셋 계산을 피한다(요청이 로컬 정시 기준이므로 그대로 대응된다).
    step = int(h.Interval()) or 3600
    out: list[dict] = []
    cur = w_start
    for i in range(len(clouds)):
        out.append({
            "time": cur,
            "cloud_cover": _clean(clouds[i]),
            "visibility": _clean(viss[i]),
        })
        cur = cur + timedelta(seconds=step)
    return out


# --- 공개 API -----------------------------------------------------------------

def fetch_series(lat: float, lon: float, start: datetime, end: datetime) -> list[dict]:
    """[start, end) 각 정시의 총운량(%)·시정(m). 캐시 창을 받아 필요한 만큼 자른다.

    부르는 쪽이 어떤 구간을 물어도 실제 요청은 **정규화된 창**으로 나가므로, 같은
    칸·같은 밤에 대한 질의들이 외부 호출 하나를 나눠 쓴다.

    Args:
        lat, lon: 관측지 좌표(격자 칸으로 맞춰 요청한다).
        start, end: 조회 구간(tz-aware). 분·초는 버리고 정시로 내림한다. end 는 배타적.

    Returns:
        [{"time": datetime(KST), "cloud_cover": float|None, "visibility": float|None}, ...]
        값이 없으면(NaN·범위 밖) 해당 항목은 None 이며, 처리는 호출자(judge)에 맡긴다.
    """
    start = _require_aware(start).replace(minute=0, second=0, microsecond=0)
    end = _require_aware(end).replace(minute=0, second=0, microsecond=0)
    if end <= start:
        return []

    glat, glon = snap(lat, lon)
    rows: list[dict] = []
    for w_start in _windows_covering(start, end):
        rows.extend(_fetch_window(glat, glon, w_start))

    # 창이 요청 구간보다 넓으므로 여기서 자른다. 창끼리 겹치지 않아 중복은 없다.
    return [r for r in rows if start <= r["time"] < end]


def fetch(lat: float, lon: float, when: datetime) -> dict:
    """when 이 속한 정시의 총운량(%)·시정(m)을 반환한다(단일 시각).

    Returns:
        {"time": datetime, "cloud_cover": float|None, "visibility": float|None}
    """
    when = _require_aware(when)
    hour = when.replace(minute=0, second=0, microsecond=0)
    series = fetch_series(lat, lon, hour, hour + timedelta(hours=1))
    if series:
        return series[0]
    return {"time": hour, "cloud_cover": None, "visibility": None}


# --- 검증 ---------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Windows 콘솔(cp949)에서 한글이 깨지지 않도록 UTF-8로 출력한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # 라이브 조회 데모(네트워크 필요). 값 정규화 단위 검증은 tests/test_schema.py 에 있다.
    JEJU_LAT, JEJU_LON = 33.5097, 126.5219
    now = datetime.now(KST)
    tonight = now.replace(hour=20, minute=0, second=0, microsecond=0)

    print(f"\n관측지: 제주 ({JEJU_LAT}, {JEJU_LON})")
    one = fetch(JEJU_LAT, JEJU_LON, tonight)
    c, v = one["cloud_cover"], one["visibility"]
    print(f"단일 시각 {one['time']:%Y-%m-%d %H:%M %Z}: "
          f"총운량 {'데이터 없음' if c is None else f'{c:.0f}%'}, "
          f"시정 {'데이터 없음' if v is None else f'{v / 1000:.1f}km'}")

    print("\n시계열(20:00~다음날 06:00):")
    series = fetch_series(JEJU_LAT, JEJU_LON, tonight, tonight + timedelta(hours=10))
    for row in series:
        c = row["cloud_cover"]
        print(f"  {row['time']:%m-%d %H:%M}  총운량 "
              f"{'--' if c is None else f'{c:>3.0f}%'}")
    assert all(r["time"].tzinfo is not None for r in series), "시각은 tz-aware 여야 한다"
    print(f"  → {len(series)}개 정시 수신")
