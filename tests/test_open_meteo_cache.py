"""open_meteo — 요청 정규화(캐시가 실제로 맞게 하는 장치).

전부 순수 함수라 네트워크를 타지 않는다. 여기서 보는 것은 "값이 맞나"가 아니라
**같은 것을 묻는 질의가 같은 URL 로 나가나**다 — 그게 어긋나면 캐시가 조용히
안 맞고, 외부 호출만 늘어난다(조용히 새는 실패라 계약으로 못박는다).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from server.clients import open_meteo

KST = ZoneInfo("Asia/Seoul")


def _at(hour: int, day: int = 20) -> datetime:
    return datetime(2026, 8, day, hour, 0, tzinfo=KST)


# --- 좌표 정규화 ----------------------------------------------------------------


#: docstring 이 인용한 실측 사례 — 좌표를 칸으로 옮겼더니 고도가 달라져 운량이
#: 뒤집혔던 곳들이다. 여기가 다시 옮겨지면 "양호/불가"가 통째로 갈린다.
MOUNTAIN_SPOTS = [
    pytest.param(33.357770, 126.462456, id="1100고지 휴게소(1124m)"),
    pytest.param(33.427227, 126.604424, id="제주마방목지 관측지1(625m)"),
    pytest.param(33.425863, 126.603694, id="제주마방목지 관측지2(628m)"),
    pytest.param(33.276713, 126.639298, id="제주공천포전지훈련센터(62m)"),
]

#: 소수 넷째 자리는 위도로 약 11m. 이 안쪽이면 Open-Meteo 의 칸 선택
#: (`cell_selection=land`, 고도·육지 판정)이 바뀌지 않는다.
ELEVEN_M_DEG = 1e-4


@pytest.mark.parametrize(("lat", "lon"), MOUNTAIN_SPOTS)
def test_좌표를_칸으로_옮기지_않는다(lat, lon):
    # Given: 산 위 관측지처럼 고도가 칸 선택을 좌우하는 좌표가 주어졌을 때
    got_lat, got_lon = open_meteo.snap(lat, lon)
    # Then: 자릿수만 잘릴 뿐 11m 넘게 움직이지 않는다.
    #       한때 격자 칸(0.05°×0.0625°) 중심으로 옮겼는데, Open-Meteo 는 요청 지점의
    #       **고도**를 보고 칸을 고르므로 옮기면 다른 칸이 선택됐다 — 1100고지가
    #       고도 1124m→878m 로 읽혀 운량이 참값 77% 대신 19% 로 나왔다
    assert abs(got_lat - lat) <= ELEVEN_M_DEG
    assert abs(got_lon - lon) <= ELEVEN_M_DEG


@pytest.mark.parametrize(("lat", "lon"), MOUNTAIN_SPOTS)
def test_같은_지점을_다시_물으면_같은_키가_된다(lat, lon):
    # Given: 같은 지점을 미세하게 다른 부동소수점으로 두 번 물었을 때
    #        (지오코딩·계산 경로가 다르면 끝자리가 흔들린다)
    a = open_meteo.snap(lat, lon)
    b = open_meteo.snap(lat + 1e-9, lon - 1e-9)
    # Then: 같은 좌표로 잘려 URL 이 흔들리지 않는다 = 캐시가 맞는다
    assert a == b


def test_11m_보다_멀면_따로_묻는다():
    # Given: 마방목지의 두 관측지처럼 가깝지만 고도가 다른 지점들이
    a = open_meteo.snap(33.427227, 126.604424)
    b = open_meteo.snap(33.425863, 126.603694)
    # When: 정규화되면
    # Then: 여전히 다른 좌표다 — 합치면 한쪽 고도로 두 곳을 답하게 된다.
    #       캐시 항목이 늘어도 **맞는 값이 먼저다**
    assert a != b


def test_먼_두_지점은_합쳐지지_않는다():
    # Given: 제주 동·서 끝의 두 지점이
    east = open_meteo.snap(33.4589, 126.9408)
    west = open_meteo.snap(33.3663, 126.3576)
    # When: 정규화되면
    # Then: 여전히 다른 칸이다 — 합치기가 지나쳐 섬 반대편 예보를 쓰면 안 된다
    assert east != west


# --- 시간 창 정규화 --------------------------------------------------------------


def test_한_밤은_창_하나에_들어간다():
    # Given: 자정을 넘는 밤(20시~다음날 5시)의 각 정시가
    hours = [_at(h) for h in range(20, 24)] + [_at(h, day=21) for h in range(0, 6)]
    # When: 각각 어느 창에 속하는지 보면
    windows = {open_meteo._window_of(h) for h in hours}
    # Then: 전부 같은 창이다. 달력 하루로 잘랐다면 자정에서 갈려 호출이 두 배가 된다
    assert len(windows) == 1


def test_다른_밤은_다른_창이다():
    # Given: 이틀에 걸친 두 밤의 한복판이
    # When: 창을 보면
    # Then: 서로 다르다 — 어제 예보를 오늘 것으로 쓰면 안 된다
    assert open_meteo._window_of(_at(22, day=20)) != open_meteo._window_of(
        _at(22, day=21)
    )


def test_같은_밤의_여러_시각이_창을_공유한다():
    # Given: 같은 밤의 21·22·23시를
    # When: 정규화하면
    # Then: 창이 하나다 = "21시엔?" "22시엔?" 이 외부 호출을 나눠 쓴다.
    #       정시 창으로 물으면 시각마다 URL 이 달라져 매번 새 호출이 나갔다
    assert len({open_meteo._window_of(_at(h)) for h in (21, 22, 23)}) == 1


def test_창은_정오에_끊긴다():
    # Given: 기준 시각 앞뒤의 두 시각이
    before, after = _at(11), _at(12)
    # When: 창을 보면
    # Then: 정오에서 갈린다. 밤 서비스라 낮이 아니라 정오를 경계로 삼았다 —
    #       어느 밤도 이 경계를 넘지 않는다
    assert open_meteo._window_of(before) != open_meteo._window_of(after)
    assert open_meteo._window_of(after) == after


def test_구간을_덮는_창을_빠짐없이_고른다():
    # Given: 사흘에 걸친 긴 구간이
    start, end = _at(20, day=20), _at(20, day=23)
    # When: 덮는 창들을 구하면
    windows = open_meteo._windows_covering(start, end)
    # Then: 구간 전체가 덮인다 — 모자라면 뒷부분이 조용히 빈 채로 나간다
    assert windows[0] <= start
    assert windows[-1] + timedelta(days=1) >= end
    assert windows == sorted(windows)


def test_짧은_구간은_창_하나로_끝난다():
    # Given: 한 정시만 묻는 구간이 (evaluate_place 의 moment 경로)
    start = _at(22)
    # When: 덮는 창을 구하면
    # Then: 하나다 — 한 시각을 물었다고 이틀치를 받아 오지 않는다
    assert len(open_meteo._windows_covering(start, start + timedelta(hours=1))) == 1


def test_빈_구간은_외부_호출을_만들지_않는다():
    # Given: end 가 start 보다 앞서거나 같은 구간이
    start = _at(22)
    # When: 조회하면
    # Then: 빈 목록이다(창 계산에 들어가기 전에 끊는다)
    earlier = start - timedelta(hours=1)
    assert open_meteo.fetch_series(33.36, 126.35, start, start) == []
    assert open_meteo.fetch_series(33.36, 126.35, start, earlier) == []


# --- 캐시 자리 ------------------------------------------------------------------


def test_캐시_파일_자리는_path가_정한다():
    # Given: 캐시 파일 경로는
    from server import path

    # When: 세션이 쓰는 자리를 보면
    # Then: `path.py` 가 정한 저장소 루트 아래다. 작업 디렉터리 기준이면 어디서
    #       실행하느냐에 따라 캐시가 갈려 외부 호출이 중복된다
    #       (CLAUDE.md: 경로를 `path.py` 밖에서 계산하지 않는다)
    assert str(path.FORECAST_CACHE).startswith(str(path.ROOT))
