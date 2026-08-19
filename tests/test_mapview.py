"""mapview·maps — 지도가 무엇을 그리고 무엇을 안 그리나.

렌더링은 순수 함수라 네트워크가 없다. 파일 쓰기(`server/maps.py`)는 `outputs/` 아래로
떨어지므로 저장소를 더럽히지 않는다.

여기서 보는 것은 "예쁘게 나오나"가 아니라 **없는 것을 그리지 않나**다 — 지도는 있는
것처럼 보이게 만드는 힘이 세서, 확인되지 않은 선을 그으면 글로 붙인 단서보다 강하게
읽힌다.
"""

from __future__ import annotations

import json
import re

from server import maps
from server.core import mapview
from server.core.mapview import Marker

SPOT = Marker(33.3663, 126.3576, "spot", "새별오름", "오름")
PARK = Marker(33.3651, 126.3611, "parking", "새별오름 주차장", "무료")
WALK = [(33.3651, 126.3611), (33.3658, 126.3595), (33.3663, 126.3576)]
#: (점렬, 갈래, 설명) — 지도는 갈래로 색을 가르고, 눌렀을 때 설명을 띄운다.
WALK_DIRT = [(WALK, "흙길", "120m · 노면 거의 흙")]
WALK_MIXED = [(WALK, "흙길", "120m"), (WALK[:2], "계단", "60m · 목재계단")]


def _payload(document: str) -> dict:
    """HTML 에 심어 둔 데이터 뭉치를 도로 꺼낸다."""
    return json.loads(re.search(r"^const D = (\{.*\});$", document, re.M).group(1))


# --- 그릴 것이 없으면 그리지 않는다 ------------------------------------------------


def test_마커가_없으면_지도를_만들지_않는다():
    # Given: 찍을 점이 하나도 없을 때
    # When: 렌더링하면
    # Then: 빈 문자열이다. 빈 지도를 내보내면 "지도가 있다"는 잘못된 신호가 된다
    assert mapview.render("제목", []) == ""
    assert maps.write("제목", []) is None


def test_도보_경로가_없으면_선을_긋지_않는다():
    # Given: 점 하나만 있고 도보 경로가 없을 때 (미등록 장소)
    data = _payload(mapview.render("한 지점", [SPOT]))
    # When: 데이터를 보면
    # Then: 선 자료가 비어 있다 — 없는 길을 그으면 있는 것처럼 보인다
    assert data["walks"] == []


def test_주행_경로는_지도에_아예_없다():
    # Given: 어떤 지도든
    document = mapview.render("도착 이후", [SPOT, PARK], walk_segments=WALK_DIRT)
    data = _payload(document)
    # When: 자료와 문서를 보면
    # Then: 주행선을 담는 자리 자체가 없다. 제주를 가로지르는 선이 들어오면 지도가
    #       섬 전체로 줌아웃되어 정작 봐야 할 도보 경로·계단이 점으로 뭉개진다 —
    #       주행시간은 도구 응답의 숫자와 문장이 답한다
    assert "drive" not in data
    assert "출발지" not in document


def test_범례는_실제로_그린_갈래만_싣는다():
    # Given: 흙길과 계단이 섞인 도보 경로만 있을 때(주행 경로는 없다)
    document = mapview.render("도보만", [SPOT, PARK], walk_segments=WALK_MIXED)
    # When: 범례를 보면
    # Then: 그린 갈래는 있고, 안 그린 갈래와 주행선은 없다.
    #       없는 것을 범례에만 두면 "왜 안 보이지"가 된다
    assert "흙길" in document
    assert "계단" in document
    assert "포장길" not in document
    assert "차로 가는 길" not in document


def test_점이_둘_미만인_구간은_아예_빠진다():
    # Given: 점이 하나뿐인 구간이 주어졌을 때
    data = _payload(
        mapview.render("한 점", [SPOT], walk_segments=[([(33.36, 126.35)], "흙길", "")])
    )
    # When: 데이터를 보면
    # Then: 선이 될 수 없으므로 담지 않는다 — 담아 두면 범례에만 갈래가 뜬다
    assert data["walks"] == []


# --- 두 축을 눈으로 갈라 놓는다 ----------------------------------------------------


def test_도보_갈래마다_색이_다르다():
    # Given: 흙길과 계단이 섞인 경로에서
    data = _payload(mapview.render("갈래", [SPOT], walk_segments=WALK_MIXED))
    colors = {w["kind"]: w["color"] for w in data["walks"]}
    # When: 색을 견주면
    # Then: 다르다. 한 색으로 그으면 "20분 걷는다"까지만 보이고 **어디서 계단이
    #       시작되는지**가 안 보인다 — 밤에 초행으로 오르는 사람에게 그게 준비를 가른다
    assert colors["흙길"] != colors["계단"]


def test_구간을_누르면_길이가_뜬다():
    # Given: 설명이 붙은 구간에서
    data = _payload(mapview.render("설명", [SPOT], walk_segments=WALK_MIXED))
    # When: 구간 자료를 보면
    notes = {w["kind"]: w["note"] for w in data["walks"]}
    # Then: 갈래만이 아니라 길이가 함께 실린다 — "계단"만 떠서는 각오할 양을 모른다.
    #       10m 계단과 260m 계단은 다른 이야기다
    assert "60m" in notes["계단"]
    assert "120m" in notes["흙길"]


def test_모르는_갈래는_쉬운_색으로_칠하지_않는다():
    # Given: 구간 정보가 없어 갈래를 못 정한 경로에서
    data = _payload(mapview.render("모름", [SPOT], walk_segments=[(WALK, "모름", "")]))
    paved = mapview.render("포장길", [SPOT], walk_segments=[(WALK, "포장길", "")])
    known = _payload(paved)
    # When: 색을 보면
    # Then: 가장 쉬운 갈래(포장)와 다른 색이다 — 모르는 길을 쉬운 색으로 칠하면
    #       확인되지 않은 것이 확인된 것처럼 읽힌다
    assert data["walks"][0]["color"] != known["walks"][0]["color"]


def test_마커는_색뿐_아니라_글자로도_갈린다():
    # Given: 갈래가 다른 마커들에서
    data = _payload(mapview.render("갈래", [SPOT, PARK]))
    glyphs = {m["glyph"] for m in data["markers"]}
    # When: 표시를 보면
    # Then: 갈래마다 다른 글자가 있다 — 색만으로 나누면 색맹·흑백 출력에서
    #       구분이 사라진다
    assert len(glyphs) == 2


def test_모르는_갈래도_그리기는_한다():
    # Given: 정의되지 않은 갈래의 마커가 주어졌을 때
    data = _payload(mapview.render("모르는 것", [Marker(33.4, 126.5, "???", "무엇")]))
    # When: 결과를 보면
    # Then: 예외 없이 기본 모양으로 찍힌다 — 축이 늘 때 지도가 먼저 깨지지 않게
    assert data["markers"][0]["name"] == "무엇"


def test_제목과_설명은_HTML로_새지_않는다():
    # Given: 꺾쇠가 든 이름이 주어졌을 때 (지오코딩 결과가 그대로 들어올 수 있다)
    document = mapview.render("<script>x</script>", [SPOT], caption="<b>굵게</b>")
    # When: 문서를 보면
    # Then: 태그로 살아나지 않는다
    assert "<script>x</script>" not in document
    assert "&lt;script&gt;" in document


# --- 배경 (위성이 기본) -----------------------------------------------------------


def test_배경은_위성사진이_기본이다():
    # Given: 관측지 지도를 그리면
    document = mapview.render("배경", [SPOT])
    # When: 어느 배경이 지도에 붙는지 보면
    # Then: 위성이 붙고 일반 지도는 토글로만 있다. 주차 자리가 포장인지 흙바닥인지,
    #       탐방로가 어디로 났는지는 선 지도로는 안 보인다
    assert "SAT.addTo(map)" in document
    assert "PLAIN.addTo(map)" not in document
    assert "'일반 지도': PLAIN" in document


def test_위성_최대_실사진_줌을_넘겨_당기지_않는다():
    # Given: 실사진이 있는 줌은 공급자마다 다르다(Esri 는 제주 z18, VWorld 는 z19)
    document = mapview.render("줌", [SPOT])
    data = _payload(document)
    # When: 위성 레이어 설정을 보면
    # Then: 실사진 줌이 최대 줌보다 작다 — 같거나 크면 없는 줌을 그대로 요청해
    #       화면이 회색으로 빈다. 늘려 보여주는 쪽이 비어 보이는 것보다 낫다
    assert data["sat"]["maxNative"] < data["sat"]["maxZoom"]
    assert "maxNativeZoom: D.sat.maxNative" in document


def test_위성_공급자를_밖에서_갈아끼울_수_있다():
    # Given: 키가 필요한 공급자가 있어 `core` 가 환경을 읽을 수 없다
    custom = mapview.Tiles(
        url="https://example.test/{z}/{y}/{x}.jpeg",
        attribution="시험용",
        max_native_zoom=19,
    )
    # When: 밖에서 배경을 넘기면
    data = _payload(mapview.render("갈아끼우기", [SPOT], satellite=custom))
    # Then: 그것이 쓰인다 — 공급자 선택은 `server/maps.py` 가 한다
    assert data["sat"]["url"] == custom.url
    assert data["sat"]["maxNative"] == 19


def test_두_배경_모두_출처를_밝힌다():
    # Given: 타일은 남의 것이다
    document = mapview.render("출처", [SPOT])
    # When: 문서를 보면
    # Then: 위성·일반 각각의 귀속이 들어 있다(attribution 은 축약·생략하지 않는다)
    assert "Esri" in document
    assert "OpenStreetMap" in document


# --- 파일과 주소 ------------------------------------------------------------------


def test_같은_내용은_같은_주소가_된다():
    # Given: 같은 지도를 두 번 만들면
    a = maps.write("같은 것", [SPOT], walk_segments=WALK_DIRT)
    b = maps.write("같은 것", [SPOT], walk_segments=WALK_DIRT)
    # When: 주소를 견주면
    # Then: 같다. 이름이 내용 해시라 요청마다 파일이 쌓이지 않고 세션 상태도 안 생긴다
    assert a == b is not None


def test_다른_내용은_다른_주소가_된다():
    # Given: 내용이 다른 두 지도가
    a = maps.write("가", [SPOT])
    b = maps.write("나", [SPOT, PARK])
    # When: 주소를 견주면
    # Then: 다르다 — 같으면 먼저 만든 지도가 나중 것을 덮어 잘못된 지도를 보여준다
    assert a != b


def test_해시_이름이_아니면_읽지_않는다():
    # Given: 경로 탈출을 노린 이름들이 주어졌을 때
    for bad in ("../../server/app.py", "..%2Fapp.py", "index.html", "", "a.html"):
        # When: 읽으려 하면
        # Then: 전부 None. 이 디렉터리 밖은 어떤 요청으로도 읽히지 않는다
        assert maps.read(bad) is None, bad


def test_만든_지도는_이름으로_다시_읽힌다():
    # Given: 방금 만든 지도의 주소에서
    url = maps.write("읽기", [SPOT])
    name = url.rsplit("/", 1)[-1]
    # When: 이름으로 읽으면
    # Then: 같은 문서가 나온다(서빙 라우트가 이 경로를 쓴다)
    assert (maps.read(name) or "").startswith("<!doctype html>")


def test_주소는_바인딩이_아니라_공개_주소를_쓴다(monkeypatch):
    # Given: 컨테이너처럼 겉 주소가 따로 정해진 환경에서
    monkeypatch.setenv("MAP_BASE_URL", "https://star.example/")
    # When: 지도를 만들면
    url = maps.write("겉 주소", [SPOT])
    # Then: 그 주소로 나간다. 0.0.0.0 을 브라우저에 줄 수는 없으므로
    #       바인딩 주소를 그대로 쓰면 컨테이너에서 지도가 열리지 않는다
    assert url.startswith("https://star.example/maps/")
