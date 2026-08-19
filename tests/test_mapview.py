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
DRIVE = [(33.5070, 126.4930), (33.4500, 126.4200), (33.3651, 126.3611)]


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


def test_경로가_없으면_선을_긋지_않는다():
    # Given: 출발지도 도보 경로도 없이 점 하나만 있을 때 (출발지를 안 준 평가)
    document = mapview.render("한 지점", [SPOT])
    data = _payload(document)
    # When: 데이터를 보면
    # Then: 선 자료가 비어 있다 — 없는 길을 그으면 있는 것처럼 보인다
    assert data["drive"] == []
    assert data["walks"] == []


def test_범례는_실제로_그린_것만_싣는다():
    # Given: 도보 경로만 있고 주행 경로는 없을 때
    document = mapview.render("도보만", [SPOT, PARK], walk_paths=[WALK])
    # When: 범례를 보면
    # Then: "걸어 가는 길"은 있고 "차로 가는 길"은 없다.
    #       없는 것을 범례에만 두면 "왜 안 보이지"가 된다
    assert "걸어 가는 길" in document
    assert "차로 가는 길" not in document


def test_점이_둘_미만인_경로는_선이_되지_않는다():
    # Given: 점이 하나뿐인 경로가 주어졌을 때
    data = _payload(mapview.render("한 점", [SPOT], walk_paths=[[(33.36, 126.35)]]))
    # When: 데이터를 보면
    # Then: 자료로는 실리되 그리기는 길이 검사에서 걸러진다(자바스크립트 쪽 w.length>1).
    #       여기서는 자료가 그대로 넘어가는 것만 확인한다
    assert data["walks"] == [[[33.36, 126.35]]]


# --- 두 축을 눈으로 갈라 놓는다 ----------------------------------------------------


def test_주행선과_도보선은_다른_색이다():
    # Given: 주행과 도보가 모두 있는 지도에서
    data = _payload(
        mapview.render("둘 다", [SPOT, PARK], drive_path=DRIVE, walk_paths=[WALK])
    )
    # When: 두 선의 색을 보면
    # Then: 다르다. 주행 20분 + 도보 20분인 곳을 한 색으로 그으면 "40분 거리"로 뭉개진다
    assert data["driveColor"] != data["walkColor"]
    assert len(data["drive"]) == 3
    assert len(data["walks"][0]) == 3


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


# --- 파일과 주소 ------------------------------------------------------------------


def test_같은_내용은_같은_주소가_된다():
    # Given: 같은 지도를 두 번 만들면
    a = maps.write("같은 것", [SPOT], walk_paths=[WALK])
    b = maps.write("같은 것", [SPOT], walk_paths=[WALK])
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
