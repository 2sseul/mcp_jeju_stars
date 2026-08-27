"""천체력 로더 — DE421 을 한 번만 열어 astro·moon 이 함께 쓴다.

태양(박명)과 달(달빛)은 같은 성표 파일을 읽는다. 모듈마다 `Loader` 를 따로 만들면
17MB 짜리 `de421.bsp` 가 프로세스 안에 두 벌 올라가고, 지원 날짜 범위도 두 곳에서
따로 계산된다. **파일을 여는 곳은 여기 한 곳**이고, 축 모듈들은 이미 열린 것을 받아
쓴다.

경로는 `server/path.py` 를 거친다. 자동 다운로드에 기대지 않는다 — 파일이 없으면
바로 실패시킨다(온프레미스 배포에서 조용히 외부로 나가지 않게).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from skyfield.api import Loader

from server import path

KST = ZoneInfo("Asia/Seoul")

if not path.EPHEM.exists():
    raise FileNotFoundError(f"성표 없음: {path.EPHEM}")

_loader = Loader(str(path.EPHEM.parent))

#: skyfield 타임스케일. 시각 변환은 전부 이것을 쓴다.
TS = _loader.timescale()

#: JPL DE421 천체력. 세그먼트(earth·sun·moon …)를 여기서 꺼낸다.
EPH = _loader("de421.bsp")

#: 데이터 귀속 — 응답 attribution 에 축어로 싣는다.
SOURCE: str = "천체력: JPL DE421 via Skyfield"


def span() -> tuple[datetime, datetime]:
    """천체력이 실제로 덮는 [시작, 끝] 을 KST datetime 으로 돌려준다.

    DE421 은 무한하지 않아(대략 1900~2053) 범위 밖 시각을 계산하면 skyfield 가
    EphemerisRangeError 를 던진다. 하드코딩하지 않고 로드된 파일의 세그먼트에서
    직접 읽어, 천체력을 교체해도 값이 따라오게 한다.

    세그먼트마다 범위가 달라 **교집합**(가장 늦은 시작 ~ 가장 이른 끝)을 취한다.
    한 세그먼트라도 범위를 벗어나면 계산이 실패하기 때문이다.
    """
    lo = max(seg.spk_segment.start_jd for seg in EPH.segments)
    hi = min(seg.spk_segment.end_jd for seg in EPH.segments)
    return (
        TS.tdb_jd(lo).utc_datetime().astimezone(KST),
        TS.tdb_jd(hi).utc_datetime().astimezone(KST),
    )


def to_kst(t) -> datetime:
    """skyfield Time → Asia/Seoul tz-aware datetime."""
    return t.utc_datetime().astimezone(KST)


def require_aware(when: datetime) -> datetime:
    """tz-aware 인지 검증하고 Asia/Seoul 기준으로 정규화한다."""
    if when.tzinfo is None or when.tzinfo.utcoffset(when) is None:
        raise ValueError("when 은 tz-aware(Asia/Seoul) datetime 이어야 합니다.")
    return when.astimezone(KST)
