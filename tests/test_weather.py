"""core.weather — 기상 서술(순수 함수).

여기서 보는 것은 "값이 맞나"가 아니라 **말이 값과 어긋나지 않나**다. 판정에 관여하지
않는 축이라 등급으로 드러나지 않고, 그래서 문장이 조용히 틀려도 안 잡힌다.
문헌 경계(보퍼트 4·6, 0°C, 열대야 25°C)는 경계값 자체를 케이스로 넣는다.
"""

from __future__ import annotations

import pytest

from server.core import weather


def _row(**kw) -> dict:
    """기상 행. 주지 않은 키는 아예 없다(결측이 아니라 '안 물어본 값')."""
    return dict(kw)


# --- WMO 코드 해석 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "label"),
    [
        pytest.param(0, "맑음", id="청천"),
        pytest.param(3, "흐림", id="흐림"),
        pytest.param(45, "안개", id="안개"),
        pytest.param(63, "비", id="비"),
        pytest.param(73, "눈", id="눈"),
        pytest.param(95, "뇌우", id="뇌우"),
    ],
)
def test_WMO_코드는_한국어_하늘_상태로_바뀐다(code, label):
    # Given: Open-Meteo 가 돌려주는 WMO 4677 코드가 있을 때
    # When: 라벨로 옮기면
    # Then: 해석표(Open-Meteo 문서)와 같은 말이 나온다
    assert weather.sky_label(code) == label


def test_모르는_코드와_결측은_None이다():
    # Given: 해석표에 없는 코드(4)와 결측이
    # When: 라벨로 옮기면
    # Then: 지어내지 않고 None 을 돌려준다
    assert weather.sky_label(4) is None
    assert weather.sky_label(None) is None


@pytest.mark.parametrize(
    ("code", "precip"),
    [
        pytest.param(48, False, id="안개는_강수가_아니다"),
        pytest.param(51, True, id="이슬비가_강수_경계"),
        pytest.param(80, True, id="소나기"),
        pytest.param(None, False, id="결측"),
    ],
)
def test_강수_경계는_이슬비_51이다(code, precip):
    # Given: WMO 4677 은 51 부터 강수 계열이다
    # When/Then: 경계값 자체로 확인한다 — 48(안개)은 아니고 51(이슬비)부터다
    assert weather.is_precipitating(code) is precip


# --- 한 시각 서술 --------------------------------------------------------------


def test_기온_체감_습도는_한_줄로_묶인다():
    # Given: 기온·체감·습도가 다 있을 때
    row = _row(temperature_c=12.4, apparent_c=8.6, humidity_pct=71.0)
    # When: 서술하면
    lines = weather.describe(row)
    # Then: 세 값이 한 문장에 들어간다(줄을 셋으로 나누면 근거 목록이 기상으로 덮인다)
    assert lines[0] == "기온 12°C · 체감 9°C · 습도 71%예요"


def test_체감이_기온과_같으면_두_번_말하지_않는다():
    # Given: 바람이 없어 체감이 기온과 사실상 같을 때
    row = _row(temperature_c=20.0, apparent_c=20.2)
    # When: 서술하면
    lines = weather.describe(row)
    # Then: '체감' 을 따로 붙이지 않는다
    assert lines == ["기온 20°C예요"]


@pytest.mark.parametrize(
    "code",
    [
        pytest.param(0, id="맑음"),
        pytest.param(3, id="흐림"),
        pytest.param(45, id="안개"),
        pytest.param(63, id="비"),
    ],
)
def test_하늘_상태는_문장으로_말하지_않는다(code):
    # Given: 어떤 하늘 상태든 — 맑음이든 비든
    row = _row(weather_code=code, precipitation_probability_pct=80.0)
    # When: 서술하면
    lines = weather.describe(row)
    # Then: 문장이 하나도 없다. 차폐 축은 judge 가 말한다 — 여기서 또 말하면
    #       같은 사실을 두 모듈이 각자 말해 겹치거나 어긋난다(decisions.md §2.40)
    assert lines == []


@pytest.mark.parametrize(
    ("wind_ms", "expected"),
    [
        pytest.param(5.4, 0, id="보퍼트4_미만은_말하지_않는다"),
        pytest.param(5.5, 1, id="보퍼트4_경계"),
        pytest.param(10.7, 1, id="보퍼트6_직전"),
        pytest.param(10.8, 1, id="보퍼트6_경계"),
    ],
)
def test_바람은_보퍼트_4부터_말한다(wind_ms, expected):
    # Given: 풍속이 보퍼트 계급 경계에 있을 때
    row = _row(wind_ms=wind_ms)
    # When: 서술하면
    lines = weather.describe(row)
    # Then: 4 미만은 침묵한다 — 관측에 영향이 없는 바람까지 말하면 근거가 묽어진다
    assert len(lines) == expected


def test_보퍼트_6부터는_더_센_말을_쓴다():
    # Given: 된바람(보퍼트 6) 이상일 때
    # When: 서술하면
    weak = weather.describe(_row(wind_ms=6.0))[0]
    strong = weather.describe(_row(wind_ms=12.0))[0]
    # Then: 두 문장이 다르다(계급이 달라도 같은 말이면 계급을 나눈 뜻이 없다)
    assert "바람이 제법 불어요" in weak
    assert "바람이 강해요" in strong


def test_값이_하나도_없으면_아무_말도_하지_않는다():
    # Given: 조회에 실패해 기상값이 전부 없을 때
    # When: 서술하면
    # Then: 빈 목록이다 — 모르는 것을 아는 척하지 않는다
    assert weather.describe({}) == []


# --- 밤 단위 집계 --------------------------------------------------------------


def _night(temps, **kw) -> list[dict]:
    """정시별 기온 목록으로 밤 구간 행을 만든다."""
    return [_row(temperature_c=t, **kw) for t in temps]


def test_밤_기온은_최저_최고로_집계된다():
    # Given: 밤사이 기온이 오르내릴 때
    rows = _night([9.0, 7.2, 5.8, 6.4])
    # When: 집계하면
    got = weather.summarize_night(rows)
    # Then: 최저·최고가 그대로 나온다(평균으로 뭉개지 않는다 — 최저가 옷을 정한다)
    assert got["temp_min_c"] == 5.8
    assert got["temp_max_c"] == 9.0


def test_대표_기상코드는_최빈값이고_동률이면_나쁜_쪽이다():
    # Given: 맑음(0) 2시간, 비(61) 2시간으로 동률일 때
    rows = [_row(weather_code=c) for c in (0, 0, 61, 61)]
    # When: 집계하면
    got = weather.summarize_night(rows)
    # Then: 나쁜 쪽(비)을 대표로 쓴다 — 같은 밤을 두 번 물어도 답이 안 바뀌게
    assert got["weather_code"] == 61
    assert got["sky"] == "약한 비"


@pytest.mark.parametrize(
    ("codes", "kind"),
    [
        pytest.param([0, 51, 61, 80], "비", id="이슬비·비·소나기는_전부_비"),
        pytest.param([0, 95], "비", id="뇌우도_비"),
        pytest.param([0, 71, 77], "눈", id="눈·싸락눈"),
        pytest.param([85, 86], "눈", id="소낙눈"),
        pytest.param([61, 71], "비·눈", id="둘_다"),
        pytest.param([0, 3, 45], None, id="무강수면_None"),
    ],
)
def test_강수는_실제_종류로_부른다(codes, kind):
    # Given: 밤사이 나온 WMO 코드들이 주어졌을 때
    # When: 종류를 뽑으면
    # Then: 눈 계열(71·73·75·77·85·86)만 '눈'이다. 뭉뚱그려 "비나 눈"이라고 하면
    #       8월 제주에 눈 예보를 말하게 된다
    assert weather.precip_kind(codes) == kind


def test_여름_이슬비_밤에_눈을_말하지_않는다():
    # Given: 8월 새별오름의 실제 예보 — 이슬비(51)가 밤새 이어졌다
    rows = [_row(weather_code=51, temperature_c=23.0) for _ in range(10)]
    # When: 서술하면
    lines = weather.describe_night(weather.summarize_night(rows))
    # Then: '눈'이 한 글자도 없다
    assert not any("눈" in x for x in lines)
    assert any("10시간은 비 예보예요" in x for x in lines)


def test_강수_시간_수를_그대로_센다():
    # Given: 6시간 중 2시간이 비 예보일 때
    rows = [_row(weather_code=c) for c in (0, 0, 61, 63, 0, 0)]
    # When: 집계하면
    got = weather.summarize_night(rows)
    # Then: 가능/불가로 매기지 않고 시간 수를 그대로 준다(tonight.py 와 같은 원칙)
    assert got["precipitation_hours"] == 2


def test_쓸_값이_하나도_없으면_요약은_None이다():
    # Given: 기상 조회가 비었을 때(엔진 대역이 시각만 주는 경우 포함)
    rows = [_row(), _row()]
    # When: 집계하면
    # Then: 빈 dict 가 아니라 None 이다 — 호출자가 '정보 없음'으로 환원한다
    assert weather.summarize_night(rows) is None


@pytest.mark.parametrize(
    ("temp_min", "phrase"),
    [
        pytest.param(0.0, "영하로 내려가니", id="어는점_경계"),
        pytest.param(-1.5, "영하로 내려가니", id="영하"),
        pytest.param(25.0, "열대야라", id="열대야_경계"),
        pytest.param(24.9, None, id="열대야_직전은_말_안_함"),
    ],
)
def test_기온_문구는_문헌_경계에서만_나온다(temp_min, phrase):
    # Given: 밤 최저기온이 문헌 경계(어는점 0°C · 기상청 열대야 25°C)에 있을 때
    summary = weather.summarize_night(_night([temp_min, temp_min + 1.0]))
    # When: 서술하면
    lines = weather.describe_night(summary)
    # Then: 경계 안쪽에서만 문구가 붙는다(자체 눈금을 만들지 않는다)
    if phrase is None:
        assert not any("영하" in x or "열대야" in x for x in lines)
    else:
        assert any(phrase in x for x in lines)


def test_체감은_기온보다_낮을_때만_붙는다():
    # Given: 습한 여름밤이라 체감(26°C)이 최저기온(23°C)보다 높을 때
    rows = [_row(temperature_c=t, apparent_c=t + 3.0) for t in (23.1, 23.6)]
    summary = weather.summarize_night(rows)
    # When: 서술하면
    lines = weather.describe_night(summary)
    # Then: '최저 체감 26°C' 처럼 최저기온보다 큰 수를 '최저'로 붙이지 않는다.
    #       값 자체는 numbers 에 그대로 남는다(문장만 고르는 것이다)
    assert "체감" not in lines[0]
    assert summary["apparent_min_c"] == 26.1


def test_바람이_차가운_밤에는_체감을_붙인다():
    # Given: 바람이 불어 체감이 기온보다 낮을 때 — 방한 판단에 쓰는 값이다
    rows = [_row(temperature_c=t, apparent_c=t - 4.0) for t in (2.0, 4.0)]
    # When: 서술하면
    lines = weather.describe_night(weather.summarize_night(rows))
    # Then: 체감이 문장에 붙는다
    assert "체감 -2°C" in lines[0]


def test_밤_요약이_없으면_문장도_없다():
    # Given: 기상 요약을 못 만들었을 때
    # When: 서술하면
    # Then: 빈 목록이다(응답 모양은 호출자가 지킨다)
    assert weather.describe_night(None) == []
