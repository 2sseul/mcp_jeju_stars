"""tools — 가드레일과 판정 계약.

네트워크가 필요 없는 경로만 검증한다(범위 밖·형식 오류·scope 오류·미등록 장소는
외부 호출 전에 단락된다). 실제 판정 경로는 `uv run python -m server.app` 로 확인한다.

도구 **등록**(이 함수들이 MCP 로 노출되는지)은 `test_app.py` 소관이다.
"""

from __future__ import annotations

import pytest

from server import tools
from server.core import astro
from server.tools import evaluate_place, recommend_spots, spot_details

EXPECTED_KEYS = {
    "verdict", "reasons", "numbers", "attribution", "as_of", "resolved", "spots",
    "map_url",
}

# 제주 안의 실좌표(교래리 부근). 가드에 걸리지 않는 좌표가 필요할 때 쓴다.
IN_JEJU = (33.4762, 126.8229)

# scope·날짜 검사는 범위 검사보다 먼저 일어난다. 범위 밖 좌표를 쓰면 어느 갈래로
# 갔는지가 verdict 로 드러나고, 외부 호출도 타지 않는다.
OUT_OF_RANGE = (37.5665, 126.9780)


def test_geocode는_모듈이_아니라_호출_가능한_함수여야_한다():
    # Given: tools 가 지오코딩을 이름으로 가져다 쓸 때
    # When: 그 이름을 확인하면
    # Then: 모듈이 아니라 함수다.
    #       `from server.clients import geocode` 로 모듈을 바인딩하면 호출 시
    #       TypeError 가 나는데, `_locate` 의 `except Exception` 이 이를 삼켜
    #       **입력과 무관하게 항상 '주소 확인 실패'** 가 된다. 조용히 죽는 실패라
    #       계약으로 못박는다.
    assert callable(tools.geocode)
    assert not hasattr(tools.geocode, "__path__"), "모듈이 바인딩돼 있다"


# --- 가드레일 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        pytest.param(37.5665, 126.9780, id="서울"),
        pytest.param(33.0, 126.5, id="위도 하한 밖"),
        pytest.param(33.4, 127.5, id="경도 상한 밖"),
    ],
)
def test_제주_범위_밖은_프롬프트형_응답을_돌려준다(lat, lon):
    # Given: 제주 행정구역 밖의 좌표가 주어졌을 때
    # When: 평가하면
    result = evaluate_place(lat=lat, lon=lon)
    # Then: 예외가 아니라 '지원 범위 밖' 응답이며, 스키마 모양은 그대로다
    assert result["verdict"] == "지원 범위 밖"
    assert set(result) == EXPECTED_KEYS
    assert result["reasons"]


@pytest.mark.parametrize(
    ("date", "time"),
    [
        pytest.param("2026/07/24", None, id="날짜 구분자 오류"),
        pytest.param("내일", None, id="자연어 날짜"),
        pytest.param(None, "22시", id="시각 형식 오류"),
        pytest.param("2026-13-99", None, id="범위를 벗어난 날짜"),
    ],
)
def test_날짜_시각_형식_오류는_입력_오류로_환원된다(date, time):
    # Given: 파싱할 수 없는 date/time 이 주어졌을 때
    # When: 제주 안 좌표로 평가하면
    result = evaluate_place(lat=IN_JEJU[0], lon=IN_JEJU[1], date=date, time=time)
    # Then: 예외를 던지지 않고 형식을 안내하는 응답이 나온다
    assert result["verdict"] == "입력 오류"
    assert set(result) == EXPECTED_KEYS


@pytest.mark.parametrize("scope", ["tonight", "밤", "both", "moment;night"])
def test_알_수_없는_scope는_입력_오류로_환원된다(scope):
    # Given: moment/night 이 아닌 scope 가 주어졌을 때
    # When: 평가하면
    result = evaluate_place(lat=OUT_OF_RANGE[0], lon=OUT_OF_RANGE[1], scope=scope)
    # Then: 범위 가드에 닿기 전에 scope 오류로 단락된다
    assert result["verdict"] == "입력 오류"


@pytest.mark.parametrize("scope", ["  MOMENT ", "Night", "moment", "NIGHT"])
def test_scope는_대소문자와_공백을_정규화한다(scope):
    # Given: 대소문자·공백이 섞인 유효한 scope 가 주어졌을 때
    # When: 범위 밖 좌표로 평가하면
    result = evaluate_place(lat=OUT_OF_RANGE[0], lon=OUT_OF_RANGE[1], scope=scope)
    # Then: scope 오류가 아니라 범위 가드에 걸린다 = 정규화가 동작했다
    assert result["verdict"] == "지원 범위 밖"


@pytest.mark.parametrize("scope", ["", None])
def test_빈_scope는_moment로_기본값이_된다(scope):
    # Given: scope 를 비워서 넘겼을 때
    # When: 범위 밖 좌표로 평가하면
    result = evaluate_place(lat=OUT_OF_RANGE[0], lon=OUT_OF_RANGE[1], scope=scope)
    # Then: 입력 오류가 아니라 기본값 moment 로 흘러 범위 가드에 걸린다
    assert result["verdict"] == "지원 범위 밖"


def test_범위_가드는_night_경로에도_걸린다():
    # Given: 제주 밖 좌표에 밤 집계를 요청했을 때
    # When: 평가하면
    result = evaluate_place(lat=37.5665, lon=126.9780, scope="night")
    # Then: moment 와 같은 가드가 적용된다(두 경로의 일관성)
    assert result["verdict"] == "지원 범위 밖"


def test_장소를_아예_안_주면_입력_오류다():
    # Given: 이름도 좌표도 없이 불렀을 때
    # When: 평가하면
    result = evaluate_place()
    # Then: 지오코딩을 시도하지 않고 무엇을 달라는지 안내한다
    assert result["verdict"] == "입력 오류"
    assert set(result) == EXPECTED_KEYS
    assert any("좌표" in r for r in result["reasons"])


# --- 천체력 지원 범위 ------------------------------------------------------------


@pytest.mark.parametrize("scope", ["moment", "night"])
@pytest.mark.parametrize("date", ["2100-01-01", "1800-01-01"])
def test_천체력_범위_밖_날짜는_입력_오류로_환원된다(date, scope):
    # Given: DE421 이 덮지 않는 날짜가 주어졌을 때(대략 1900~2053 밖)
    # When: 제주 안 좌표로 평가하면
    result = evaluate_place(lat=IN_JEJU[0], lon=IN_JEJU[1], date=date, scope=scope)
    # Then: skyfield 의 EphemerisRangeError 가 도구 밖으로 새지 않고,
    #       고정 스키마의 '입력 오류' 응답이 된다. 형식 검사만으로는 못 걸러진다
    assert result["verdict"] == "입력 오류"
    assert set(result) == EXPECTED_KEYS
    assert any("천체력" in r for r in result["reasons"])


def test_지원_범위_경계는_거부하지_않는다():
    # Given: 천체력이 실제로 덮는 범위의 양 끝에서
    for when in (astro.EPHEM_START, astro.EPHEM_END):
        # When: 지원 여부를 물으면
        # Then: 경계 자체는 지원한다
        #       (범위를 파일에서 읽으므로 하드코딩과 어긋나지 않는다)
        assert astro.supports(when)


def test_지원_범위는_천체력_파일에서_읽는다():
    # Given: DE421 을 로드한 상태에서
    # When: 노출된 범위를 보면
    # Then: 상수가 아니라 파일의 세그먼트에서 유도된 값이라 교체 시 따라온다
    assert astro.EPHEM_START < astro.EPHEM_END
    assert astro.EPHEM_START.year <= 1900
    assert astro.EPHEM_END.year >= 2050


# --- 검증 순서 --------------------------------------------------------------------


def test_evaluate_place는_지오코딩보다_먼저_입력을_검증한다(monkeypatch):
    # Given: 지오코딩이 호출되면 즉시 실패하도록 해두고
    called = []

    def spy(*a, **kw):
        called.append(a)
        raise AssertionError("입력이 잘못됐는데 지오코딩을 호출했다")

    monkeypatch.setattr(tools, "geocode", spy)

    # When: 잘못된 scope·날짜로 지명 평가를 요청하면
    #       (등록된 관측지 이름이면 지오코딩을 안 타므로, 목록에 없는 이름을 쓴다)
    bad_scope = evaluate_place("제주시 어딘가", scope="tonight")
    bad_date = evaluate_place("제주시 어딘가", date="엉터리")

    # Then: 외부 호출 없이 '입력 오류' 로 단락된다.
    #       (뒤에 검증하면 지오코딩까지 실패했을 때 '주소 확인 실패' 로 잘못 분류된다)
    assert called == []
    assert bad_scope["verdict"] == "입력 오류"
    assert bad_date["verdict"] == "입력 오류"


def test_좌표_경로와_지명_경로의_입력_판정이_같다(monkeypatch):
    # Given: 지오코딩이 항상 실패하는 상황에서(네트워크 장애 등)
    monkeypatch.setattr(tools, "geocode", lambda *a, **kw: None)
    # When: 같은 잘못된 입력을 두 입력 형태에 주면
    for kwargs in ({"scope": "tonight"}, {"date": "엉터리"}, {"date": "2100-01-01"}):
        by_coord = evaluate_place(lat=IN_JEJU[0], lon=IN_JEJU[1], **kwargs)
        by_name = evaluate_place("제주시 어딘가", **kwargs)
        # Then: 지오코딩 성패와 무관하게 같은 판정이 나온다
        assert by_coord["verdict"] == by_name["verdict"] == "입력 오류", kwargs


def test_등록된_관측지_이름은_지오코딩을_타지_않는다(monkeypatch):
    # Given: 지오코딩이 불리면 터지도록 해두고
    def boom(*a, **kw):
        raise AssertionError("검증된 관측지인데 외부 지오코더를 불렀다")

    monkeypatch.setattr(tools, "geocode", boom)
    # When: 목록에 있는 이름으로 상세를 조회하면 (상세는 네트워크를 안 탄다)
    result = spot_details("새별오름")
    # Then: 우리 좌표로 답한다 — 외부 호출도, 좌표 오차도 없다
    assert result["spots"][0]["name"] == "새별오름"


# --- 출발지가 있으면 주행시간을 함께 답한다 ---------------------------------------
#
# 판정(하늘)은 네트워크를 타지만 주행시간은 로컬 그래프다. 그래서 날씨 조회만
# 막아 두고 주행 부분만 본다 — 이 파일의 "네트워크 없이" 규율을 지키면서.


@pytest.fixture
def _no_weather(monkeypatch):
    """graph.run 을 고정 응답으로 갈음한다. 하늘 판정이 아니라 경로를 보려는 것."""
    def fake_run(lat, lon, when):
        return {
            "verdict": "양호",
            "possible": True,
            "reasons": [],
            "numbers": {},
            "attribution": [],
        }

    monkeypatch.setattr(tools.graph, "run", fake_run)


def test_출발지를_주면_미등록_장소에도_주행시간이_붙는다(_no_weather):
    # Given: 검증 목록에 없는 좌표(제주 안)를, 출발지와 함께 물으면
    result = evaluate_place(
        lat=33.2447, lon=126.5606,           # 서귀포 시내 — 등록된 관측지가 아니다
        origin_lat=33.5070, origin_lon=126.4930,  # 제주공항
    )
    # When: 응답을 보면
    # Then: 하늘은 판정하고, 접근성 중 **주행시간만** 답한다.
    #       주행시간은 좌표만 있으면 계산되므로 등록 여부와 무관하다
    assert result["spots"] is None, "등록된 곳이 아니어야 이 시험이 성립한다"
    assert "drive" in result["numbers"]
    assert result["numbers"]["drive"]["minutes"] > 0
    joined = " ".join(result["reasons"])
    assert "차로 약" in joined
    # 그러면서도 나머지 접근성은 여전히 모른다고 말한다
    assert "확인되지 않았습니다" in joined


def test_출발지가_없으면_주행_필드가_아예_없다(_no_weather):
    # Given: 출발지 없이 물으면
    result = evaluate_place(lat=33.2447, lon=126.5606)
    # When: numbers 를 보면
    # Then: drive 키가 없다. 거리 축이 빠질 뿐 나머지는 그대로 나간다
    #       (예보 지평 밖에서 구름만 미상으로 남는 것과 같은 규율)
    assert "drive" not in result["numbers"]
    assert result["verdict"] == "양호"


AIRPORT = (33.5070, 126.4930)   # 제주국제공항. 좌표로 고정해 지오코딩을 타지 않는다.


def test_등록된_곳은_주행_목적지가_주차장이다(_no_weather):
    # Given: 관측 지점이 도로에서 먼 등반 관측지를 (정상과 주차장이 떨어져 있다)
    spot = next(s for s in tools.spots.all_spots() if s.needs_climb and s.parking)
    assert spot.drive_target() != spot.coord()
    # When: 출발지와 함께 물으면
    result = evaluate_place(
        query=spot.name, origin_lat=AIRPORT[0], origin_lon=AIRPORT[1]
    )
    # Then: 주행시간이 관측 지점이 아니라 **주차장까지**로 잰 값이다.
    #       정상까지 차로 가는 것처럼 답하면 도착 시간을 낙관하게 된다
    to_parking = tools.routing.drive_time(AIRPORT, spot.drive_target())
    to_summit = tools.routing.drive_time(AIRPORT, spot.coord())
    assert result["numbers"]["drive"] == to_parking.to_dict()
    assert to_parking.to_dict() != to_summit.to_dict(), "두 지점이 실제로 갈려야 한다"


def test_제주_밖_출발지는_주행시간을_지어내지_않는다(_no_weather):
    # Given: 출발지가 제주 밖일 때 (서울에서 물어보는 경우)
    result = evaluate_place(
        lat=33.2447, lon=126.5606, origin_lat=37.5665, origin_lon=126.9780
    )
    # When: 응답을 보면
    # Then: 목적지 판정은 그대로 하되 주행시간은 붙이지 않는다.
    #       배·비행기 구간을 차로 몇 분이라 답할 수는 없다
    assert result["verdict"] == "양호"
    assert "drive" not in result["numbers"]


# --- 지도 (경로·편의시설) --------------------------------------------------------


def test_출발지는_점으로만_찍고_선은_긋지_않는다():
    # Given: 출발지를 준 상세 조회에서
    result = spot_details("새별오름", origin_lat=AIRPORT[0], origin_lon=AIRPORT[1])
    document = tools.maps.read(result["map_url"].rsplit("/", 1)[-1]) or ""
    # When: 응답과 지도를 견주면
    # Then: 출발지 점은 찍히되 주행선은 없다. "내가 여기서 저만큼 떨어져 있구나"는
    #       점만으로 보이고, 섬을 가로지르는 선이 들어오면 지도가 줌아웃되어 도보
    #       경로·계단이 뭉개진다
    assert result["numbers"]["drive"]["minutes"] > 0
    assert '"kind": "origin"' in document
    assert '"drive":' not in document


def test_출발지가_없어도_지도는_그대로_나온다():
    # Given: 출발지 없이 상세를 조회하면
    result = spot_details("새별오름")
    document = tools.maps.read(result["map_url"].rsplit("/", 1)[-1]) or ""
    # When: 응답을 보면
    # Then: 주행 항목만 빠지고 지도(도보·주차·화장실)는 그대로다
    assert "drive" not in result["numbers"]
    assert '"walks":' in document


def test_등록된_곳은_사람이_확인한_주차_화장실을_쓴다():
    # Given: 주차·화장실이 확인된 관측지에서
    spot = next(
        s for s in tools.spots.all_spots()
        if s.parking and s.toilet and s.walk_segments
    )
    result = spot_details(spot.name)
    document = tools.maps.read(result["map_url"].rsplit("/", 1)[-1]) or ""
    # When: 지도를 보면
    # Then: 그 곳의 확인된 자리와 도보 경로가 실린다. 반경 검색이 아니라 검증분을
    #       쓰는 것은, 확인된 자리가 그 관측지에 실제로 쓰는 자리이기 때문이다
    assert spot.parking[0]["name"] in document
    assert '"points":' in document


def test_미등록_장소는_반경_안_편의시설만_표기한다(_no_weather):
    # Given: 검증 목록에 없는 자리(서귀포 시내)를 물으면
    result = evaluate_place(lat=33.2447, lon=126.5606)
    document = tools.maps.read(result["map_url"].rsplit("/", 1)[-1]) or ""
    # When: 응답과 지도를 보면
    # Then: 반경 안 편의시설은 표기하되 **도보 경로는 그리지 않는다**.
    #       어디에 세우고 어디로 걷는지는 사람이 확인한 곳에만 있는 정보다
    assert any(f"{tools.NEARBY_M:.0f}m 안에" in r for r in result["reasons"])
    assert '"walks": []' in document


def test_편의시설이_없으면_없다고_말한다(_no_weather):
    # Given: 반경 안에 아무것도 없는 자리에서 (한라산 중턱)
    result = evaluate_place(lat=33.3620, lon=126.5330)
    # When: 응답을 보면
    # Then: 조용히 빼지 않고 없다고 적는다 — "없음"과 "모름"은 계획이 달라진다
    assert any("없어요" in r and "m 안에" in r for r in result["reasons"])


# --- 도구 3: 관측지 상세 --------------------------------------------------------


def test_등록되지_않은_이름은_상세를_지어내지_않는다():
    # Given: 검증 목록에 없는 장소를 상세 조회하면
    result = spot_details("서울시청")
    # When: 응답을 보면
    # Then: 없다고 말하고 어디로 가야 하는지 안내한다. 스키마는 그대로다
    assert result["verdict"] == "등록된 관측지가 아니에요"
    assert set(result) == EXPECTED_KEYS
    assert result["spots"] == []
    assert any("evaluate_place" in r for r in result["reasons"])


def test_상세는_주차_도보_야간출입을_모두_답한다():
    # Given: 검증된 관측지를 조회하면
    result = spot_details("새별오름")
    row = result["spots"][0]
    # When: 응답을 보면
    # Then: 접근성 축이 빠짐없이 실린다 — 이 도구의 존재 이유다
    assert set(result) == EXPECTED_KEYS
    for key in ("parking_places", "toilet", "pets", "night_access", "cautions"):
        assert key in row, key
    # 그리고 사람이 읽는 줄에도 같은 축이 나온다
    joined = " ".join(result["reasons"])
    assert "주차" in joined
    assert "야간 출입" in joined


def test_상세는_하늘_상태를_답하지_않는다():
    # Given: 상세 조회는 접근성 도구다
    result = spot_details("새별오름")
    # When: numbers 를 보면
    # Then: 구름·박명 같은 판정 축이 없다 — 그건 evaluate_place 소관이다
    assert "cloud_cover" not in result["numbers"]
    assert "twilight_state" not in result["numbers"]


# --- 도구 1: 추천 (네트워크를 타기 전에 단락되는 경로만) ----------------------------


def test_알_수_없는_region은_입력_오류로_환원된다():
    # Given: 동/서/남/북/중산간 이 아닌 지역을 주면
    result = recommend_spots(region="북동")
    # When: 추천을 요청하면
    # Then: 후보를 고르기 전에 무엇을 줘야 하는지 안내한다
    assert result["verdict"] == "입력 오류"
    assert set(result) == EXPECTED_KEYS
    assert any("중산간" in r for r in result["reasons"])


def test_추천도_날짜_형식을_먼저_검증한다(monkeypatch):
    # Given: 어둡기·날씨 조회가 불리면 터지도록 해두고
    def boom(*a, **kw):
        raise AssertionError("입력이 잘못됐는데 판정까지 갔다")

    monkeypatch.setattr(tools.graph, "run", boom)
    # When: 잘못된 날짜로 추천을 요청하면
    result = recommend_spots(date="엉터리")
    # Then: 판정 전에 단락된다
    assert result["verdict"] == "입력 오류"


def test_충족_불가한_조건은_빈_목록과_이유를_돌려준다():
    # Given: 서로 모순되는 조건을 주면 (등산 없는 곳 + 도보 0분 + 반려동물 + 한 지역)
    result = recommend_spots(
        region="북", no_climb=True, max_walk_minutes=0.0, pets=True
    )
    # When: 추천을 요청하면
    # Then: 예외도 아무 곳이나 추천도 아닌, 빈 목록 + 어느 조건을 풀지 안내다
    assert set(result) == EXPECTED_KEYS
    assert result["spots"] == []
    assert result["numbers"]["candidates"] == 0
    assert any("조건" in r for r in result["reasons"])


def test_추천은_낮에_물어도_밤_기준으로_판정한다(_no_weather):
    # Given: 오후에 날짜·시각 없이 추천을 요청했을 때
    result = recommend_spots(region="동", limit=1)
    # When: 판정 기준 시각을 보면
    hour = int(result["as_of"][11:13])
    # Then: 지금이 아니라 밤이다. "어디로 갈까"는 낮에도 묻는 질문이라, 지금 시각으로
    #       판정하면 오후 네 시에 물었을 때 전부 '불가'가 나온다 — 그건 하늘이 아니라
    #       질문을 잘못 읽은 것이다
    assert hour == tools.DEFAULT_HOUR


def test_추천_문구에_요청한_조건이_들어간다(_no_weather):
    # Given: 여러 조건을 걸어 추천을 요청했을 때
    result = recommend_spots(
        region="동", no_climb=True, pets=True, date="2026-08-20", limit=2
    )
    verdict = result["verdict"]
    # When: 한 줄 결론을 보면
    # Then: 무엇으로 골랐는지가 결과와 함께 있다 — 조건을 안 적으면 왜 이 곳들인지
    #       알 수 없고, 조건을 잘못 읽었을 때도 드러나지 않는다
    assert "동쪽 지역" in verdict
    assert "등산 없는 곳" in verdict
    assert "반려동물" in verdict
    assert "추천드립니다" in verdict


def test_조건이_없으면_시각만_적는다(_no_weather):
    # Given: 조건 없이 추천을 요청했을 때
    verdict = recommend_spots(date="2026-08-20", limit=1)["verdict"]
    # When: 결론을 보면
    # Then: 없는 조건을 지어내지 않고 기준 시각만 말한다
    assert f"8월 20일 밤 {tools.DEFAULT_HOUR}시 기준" in verdict
    assert "지역" not in verdict


# --- 응답 계약 ------------------------------------------------------------------


def test_모든_오류_응답도_고정_스키마를_지킨다():
    # Given: 서로 다른 실패 경로들에서 (전부 외부 호출 전에 단락되는 경로)
    failures = [
        evaluate_place(lat=OUT_OF_RANGE[0], lon=OUT_OF_RANGE[1]),   # 범위 밖
        evaluate_place(lat=IN_JEJU[0], lon=IN_JEJU[1], date="엉터리"),  # 형식 오류
        evaluate_place(lat=OUT_OF_RANGE[0], lon=OUT_OF_RANGE[1], scope="tonight"),
        evaluate_place(),                                            # 장소 없음
        spot_details("없는곳"),                                       # 미등록
        recommend_spots(region="북동"),                              # region 오류
    ]
    # When: 각 응답의 키 집합을 보면
    # Then: 전부 같다 — 실패해도 응답 '모양'은 바뀌지 않는다
    for result in failures:
        assert set(result) == EXPECTED_KEYS
        assert isinstance(result["reasons"], list)
        assert isinstance(result["numbers"], dict)
        assert isinstance(result["attribution"], list)
        assert result["spots"] is None or isinstance(result["spots"], list)


# --- 미등록 지점의 근처 대안 -----------------------------------------------------

# 성산일출봉 — 등록되지 않았고(63곳 밖), 반경 안에 더 어두운 관측지도 더 밝은
# 관측지도 함께 있어 필터가 실제로 일하는지 보이는 자리다.
SEONGSAN = (33.4589, 126.9408)


def test_근처_대안은_여기보다_밝은_곳을_넣지_않는다():
    # Given: 성산일출봉의 어둡기 점수를 기준으로
    from server.core import darkness

    here = darkness.assess_site(*SEONGSAN)

    # When: 근처 대안을 고르면
    rows = tools._darker_nearby(*SEONGSAN, here.score)

    # Then: 하나하나가 **엄격히 더 어둡다**. 점수는 낮을수록 어두우므로 같거나 높은
    #       곳이 섞이면 "여기보다 어둡다"는 문장이 거짓이 되고, 밝은 곳으로 사람을
    #       보내게 된다. 주행 반경 안에는 여기보다 밝은 관측지도 있다(수마포해안).
    assert rows, "반경 안에 더 어두운 곳이 있는 좌표인데 빈 목록이 나왔다"
    for spot, _leg, _sqm in rows:
        assert darkness.assess_site(spot.lat, spot.lon).score < here.score


def test_근처_대안은_어두운_순_최대_두_곳이다():
    # Given: 반경 안에 후보가 둘보다 많은 좌표에서
    from server.core import darkness

    here = darkness.assess_site(*SEONGSAN)

    # When: 대안을 고르면
    rows = tools._darker_nearby(*SEONGSAN, here.score)

    # Then: 개수는 상한을 넘지 않고, 어두운 순이다. 가까운 순이 아닌 것은 이미
    #       주행 반경으로 잘라낸 뒤라 남은 축이 어둡기뿐이어서다.
    assert len(rows) <= tools._ALT_MAX
    scores = [darkness.assess_site(s.lat, s.lon).score for s, _, _ in rows]
    assert scores == sorted(scores)


def test_기준_어둡기가_없으면_대안을_말하지_않는다():
    # Given: 광공해 격자 밖이라 비교 기준이 없을 때
    # When: 대안을 고르면
    rows = tools._darker_nearby(*SEONGSAN, None)

    # Then: 아무 말도 하지 않는다. 기준 없이 고른 "근처의 어두운 곳"은 여기보다
    #       밝을 수 있고, 길찾기까지 헛돈다.
    assert rows == []


# --- 관측 0시간인 밤에서 '무엇이 막았나' (decisions.md §2.41) --------------------


def _summary(total: int, stb: int, unknown: int = 0) -> dict:
    """밤 집계의 일부만 채운 대역. `_blocked_by` 가 보는 세 값만 있으면 된다."""
    return {"total_hours": total, "unknown_hours": unknown, "spectroscopic_hours": stb}


@pytest.mark.parametrize(
    ("total", "stb", "rain", "kind", "expected"),
    [
        # 구름은 밤새 괜찮았는데(STB=10) 비가 막은 밤 — 2026-08-27 실제 예보
        pytest.param(10, 10, 10, "비", "비 예보로", id="비만"),
        # 흐림 10시간에 비는 1시간뿐 — 2026-08-30 실제 예보.
        # 여기서 "비 예보로"라고만 하면 원인이 뒤바뀐다
        pytest.param(10, 0, 1, "비", "구름과 비 예보로", id="구름이_주고_비도_섞임"),
        pytest.param(10, 1, 10, "비", "구름과 비 예보로", id="둘_다_많음"),
        pytest.param(10, 0, 0, None, "구름으로", id="구름만"),
        # 종류를 그대로 부른다 — 8월에 "비·눈"이라고 뭉뚱그리지 않는다
        pytest.param(10, 10, 10, "눈", "눈 예보로", id="겨울_눈"),
        pytest.param(10, 10, 10, "비·눈", "비·눈 예보로", id="비도_눈도_오는_밤"),
    ],
)
def test_밤이_막힌_원인을_사실대로_고른다(total, stb, rain, kind, expected):
    # Given: 관측 가능 0시간인 밤의 집계와 강수 시간 수·종류가 주어졌을 때
    # When: 결론 문장의 원인을 고르면
    got = tools._blocked_by(
        _summary(total, stb),
        {"precipitation_hours": rain, "precipitation_kind": kind},
    )
    # Then: 있는 것만 말한다 — 비율로 '주범'을 가르지 않는다(근거 임계값이 없다)
    assert got == expected


def test_기상값이_없으면_구름으로_돌린다():
    # Given: 기상 집계를 못 만든 밤(조회 실패 등)
    # When: 원인을 고르면
    got = tools._blocked_by(_summary(10, 0), None)
    # Then: 강수를 아는 척하지 않고 구름으로만 말한다
    assert got == "구름으로"
