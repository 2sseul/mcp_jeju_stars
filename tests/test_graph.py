"""engine.graph — 밤 집계 조립 규율.

외부 I/O(open_meteo)와 천체력(astro)을 대역으로 갈아끼워 네트워크 없이 검증한다.
여기서 보는 것은 "어느 정시를 집계에 넣는가" 라는 **엔진의 정책**이다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from server.engine import graph

KST = ZoneInfo("Asia/Seoul")

#: 밤 창이 정시에 딱 떨어지지 않는 실제 사례(2026-07-28 용눈이오름 근처).
NIGHT_START = datetime(2026, 7, 28, 20, 3, tzinfo=KST)
NIGHT_END = datetime(2026, 7, 29, 5, 15, tzinfo=KST)


@pytest.fixture
def stub_night(monkeypatch):
    """밤 창·기상 조회·박명 상태를 고정한다.

    요청된 구간의 매 정시를 맑음으로 돌려준다.
    """
    monkeypatch.setattr(
        graph.astro, "night_window", lambda lat, lon, when: (NIGHT_START, NIGHT_END)
    )
    # 창 안이면 완전한 밤(0), 밖이면 시민박명(3) — 경계 판별을 명확히 하기 위함.
    monkeypatch.setattr(
        graph.astro,
        "twilight_state",
        lambda lat, lon, t: 0 if NIGHT_START <= t < NIGHT_END else 3,
    )

    def fake_series(lat, lon, start, end):
        cur = start.replace(minute=0, second=0, microsecond=0)
        end = end.replace(minute=0, second=0, microsecond=0)
        rows = []
        while cur < end:
            rows.append({"time": cur, "cloud_cover": 5.0, "visibility": 20_000.0})
            cur += timedelta(hours=1)
        return rows

    monkeypatch.setattr(graph.open_meteo, "fetch_series", fake_series)


def test_밤_창_밖_정시는_집계에서_제외된다(stub_night):
    # Given: 밤 창이 20:03~05:15 이라 시작·끝이 정시에 안 떨어질 때
    # When: 밤 집계를 돌리면
    summary = graph.run_tonight(33.4762, 126.8229, NIGHT_START)["summary"]
    # Then: 창 밖인 20:00 은 빠지고 창 안인 05:00 은 들어와 정확히 9시간이다.
    #       (fetch_series 는 구간을 정시로 내림하므로 거르지 않으면 20:00 이 섞인다)
    assert summary["total_hours"] == 9
    assert summary["observable_hours"] == 9


def test_창_밖_정시가_PTB_STB에도_섞이지_않는다(stub_night):
    # Given: 창 밖 20:00 도 맑음(운량 5%)이라 거르지 않으면 PTB/STB 에 잡히는 상황
    # When: 집계하면
    summary = graph.run_tonight(33.4762, 126.8229, NIGHT_START)["summary"]
    # Then: PTB/STB 는 judge 등급과 무관하게 순수 운량으로 세므로, 창 밖 정시가
    #       섞이면 여기서 먼저 드러난다. 9시간이어야 한다
    assert summary["photometric_hours"] == 9
    assert summary["spectroscopic_hours"] == 9


def test_집계된_정시는_모두_밤_창_안에_있다(stub_night):
    # Given: 밤 집계 결과의 연속 창을 보면
    result = graph.run_tonight(33.4762, 126.8229, NIGHT_START)
    windows = result["summary"]["windows"]
    # When: 각 창의 시작·끝을 밤 창과 비교하면
    # Then: 밤 창을 벗어나지 않는다
    assert windows
    for w in windows:
        assert datetime.fromisoformat(w["start"]) >= NIGHT_START
        assert datetime.fromisoformat(w["end"]) <= NIGHT_END + timedelta(hours=1)


def test_밤_구간이_없으면_summary는_None이다(monkeypatch):
    # Given: 백야 등으로 밤 구간을 찾지 못했을 때
    monkeypatch.setattr(graph.astro, "night_window", lambda lat, lon, when: None)
    # When: 집계하면
    result = graph.run_tonight(33.4762, 126.8229, NIGHT_START)
    # Then: 예외가 아니라 window·summary 가 None 이고, 광공해는 그대로 실린다
    #       (어둡기는 정적 속성이라 밤 유무와 무관하다)
    assert result["window"] is None
    assert result["summary"] is None
    assert "darkness" in result


def test_기상_조회_실패는_스키마를_깨지_않는다(monkeypatch):
    # Given: 밤 구간은 찾았는데 외부 기상 조회가 실패할 때
    monkeypatch.setattr(
        graph.astro, "night_window", lambda lat, lon, when: (NIGHT_START, NIGHT_END)
    )

    def boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(graph.open_meteo, "fetch_series", boom)
    # When: 집계하면
    result = graph.run_tonight(33.4762, 126.8229, NIGHT_START)
    # Then: 예외가 새 나가지 않고 window 는 유지된 채 summary 만 None 이 된다
    assert result["window"] is not None
    assert result["summary"] is None
