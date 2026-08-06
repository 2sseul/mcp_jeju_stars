"""edit_spots — 화면이 보낸 도보 경로를 파일에 넣을 값으로 바꾸는 부분.

이 도구는 `data/jeju_spots.json` 에 **직접 쓴다**. 그래서 검증이 마지막 관문이다 —
반쯤 이상한 값이 들어간 파일이 제일 나쁘고, 그건 다음에 열었을 때가 아니라 판정이
그 관측지를 조용히 빼먹을 때 드러난다.

경로만 본다. 나머지 형식(text·bool·point…)은 이 파일보다 오래됐고 쓰이는 곳도
많아 이미 데이터로 검증돼 있다.

끝에 화면 코드 구문 검사가 하나 붙어 있다. 값 검증은 아니지만 같은 파일의 결함이고,
그쪽은 틀려도 예외가 나지 않고 **검은 화면**으로만 드러나서 여기서 잡는 편이 빠르다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from scripts.edit_spots import Column, Spots, build_page, coerce
from server import path
from server.core import elevation

_ROUTES = Column("walk_routes", "도보 경로", "routes")

#: 제주 안의 두 점. 좌표 범위 검증(`_coord`)에 걸리지 않는 최소한의 선.
_A = [33.4750, 126.8266]
_B = [33.4777, 126.8215]


def _route(**kw) -> dict:
    return {"points": [_A, _B], **kw}


#: 저장할 때 표고 격자에서 **잰** 값들(`_measure`). 사람이 적은 값을 보는 시험에서는
#: 걷어내고 본다 — 여기서 지키는 것은 화면이 보낸 값을 어떻게 받아들이는가이지,
#: DEM 이 무엇을 답했는가가 아니다 — 그쪽은 `core/elevation.py` 몫이다.
_MEASURED = ("climb_m", "slope_deg", "over_m")


def _tagged(value):
    """잰 값을 뺀 나머지 — 사람이 적은 것만."""
    if isinstance(value, dict):
        return {k: _tagged(v) for k, v in value.items() if k not in _MEASURED}
    if isinstance(value, list):
        return [_tagged(v) for v in value]
    return value


# --- 경로 하나 ----------------------------------------------------------------


def test_안_그렸으면_키를_지운다():
    # Given: 아직 경로를 그리지 않은 관측지일 때
    # When: 빈 값을 저장하면
    # Then: 키가 생기지 않는다 — 이 파일에서 '없는 키'가 곧 미확인이다
    assert coerce(_ROUTES, []) is None
    assert coerce(_ROUTES, None) is None


def test_점이_하나면_저장을_막는다():
    # Given: 그리기를 켜고 첫 점만 놓인 상태일 때
    # When: 저장하면
    # Then: 막는다 — 지도에는 그려지는데 갈 수는 없는 선이 파일에 남으면 안 된다
    with pytest.raises(ValueError, match="점이 둘은"):
        coerce(_ROUTES, [{"points": [_A]}])


def test_제주_밖_좌표를_막는다():
    # Given: 화면이 어떤 이유로든 범위 밖 좌표를 보냈을 때
    # When: 저장하면
    # Then: 막는다 — 이 관측지가 어둡기 격자 밖으로 나가 판정이 조용히 사라진다
    with pytest.raises(ValueError, match="제주 밖"):
        coerce(_ROUTES, [{"points": [_A, [35.1, 129.0]]}])


def test_도보_시간은_길마다_따로_붙는다():
    # Given: 빠른 급경사길과 느린 완만한 길처럼 길마다 시간이 다를 때
    # When: 분을 함께 보내면
    # Then: 그 길에 정수로 붙는다 — 관측지 대표값(walk_minutes)과는 다른 값이다
    assert coerce(_ROUTES, [_route(minutes="20")])[0]["minutes"] == 20
    # 안 적었으면 키를 만들지 않는다
    assert "minutes" not in coerce(_ROUTES, [_route(minutes="")])[0]
    with pytest.raises(ValueError, match="1분보다"):
        coerce(_ROUTES, [_route(minutes=0)])


# --- 여러 갈래 ----------------------------------------------------------------


def test_하나뿐이면_이름을_묻지_않는다():
    # Given: 오르는 길이 하나뿐일 때
    # When: 이름 없이 저장하면
    # Then: 그대로 저장된다 — 부를 일이 없는 이름은 묻지 않는다
    assert _tagged(coerce(_ROUTES, [_route()])) == [{"points": [_A, _B]}]


def test_길이_둘_이상이면_이름이_있어야_한다():
    # Given: 다랑쉬오름처럼 급경사길과 완만한 길이 갈릴 때
    # When: 이름 없이 저장하면
    # Then: 막는다 — 이름 없이는 둘을 고를 수가 없다
    with pytest.raises(ValueError, match="이름이 있어야"):
        coerce(_ROUTES, [_route(name="오른쪽 급경사길"), _route()])


def test_같은_이름_둘을_막는다():
    with pytest.raises(ValueError, match="겹칩니다"):
        coerce(_ROUTES, [_route(name="같은 길"), _route(name="같은 길")])


# --- 구간 --------------------------------------------------------------------


def test_구간은_자르는_자리로만_남는다():
    # Given: 계단 구간과 능선길로 나눠 노면을 적었을 때
    # When: 저장하면
    # Then: 시작 점 번호와 적은 것만 남는다 — 끝은 다음 구간이 정하므로 적지 않는다
    routes = coerce(_ROUTES, [_route(segments=[
        {"from": 0, "surface": "포장", "rock": "목재계단",
         "note": "경사 30~35도 데크계단"},
        {"from": 1, "surface": "거의 흙", "note": "완만한 능선 흙길"},
    ])])
    assert _tagged(routes[0])["segments"] == [
        {"from": 0, "surface": "포장", "rock": "목재계단",
         "note": "경사 30~35도 데크계단"},
        {"from": 1, "surface": "거의 흙", "note": "완만한 능선 흙길"},
    ]


def test_아무것도_안_적은_구간은_버린다():
    # Given: 자르기만 하고 노면도 설명도 안 적었을 때
    # When: 저장하면
    # Then: 구간을 남기지 않는다 — 아무것도 말하지 않는 구분이다
    assert "segments" not in coerce(_ROUTES, [_route(segments=[
        {"from": 0}, {"from": 1},
    ])])[0]


def test_첫_구간은_경로_첫_점에서_시작한다():
    # Given: 첫 구간이 중간부터 시작하는 값이 왔을 때
    # When: 저장하면
    # Then: 막는다 — 그러면 첫 점부터 그 자리까지가 어느 구간도 아닌 채로 남는다
    with pytest.raises(ValueError, match="첫 점에서 시작"):
        coerce(_ROUTES, [_route(segments=[{"from": 1, "surface": "포장"}])])


def test_없는_점에서_시작하는_구간을_막는다():
    with pytest.raises(ValueError, match="없는 점"):
        coerce(_ROUTES, [_route(segments=[
            {"from": 0, "surface": "포장"}, {"from": 9, "surface": "포장"},
        ])])


def test_구간은_찍은_순서대로여야_한다():
    with pytest.raises(ValueError, match="순서대로"):
        coerce(_ROUTES, [{"points": [_A, _B, _A], "segments": [
            {"from": 0, "surface": "포장"}, {"from": 2, "surface": "거의 흙"},
            {"from": 1, "surface": "거의 돌"},
        ]}])


def test_난이도는_더_받지_않는다():
    # Given: 예전에 있던 난이도 3단(쉬움·보통·어려움)을 그대로 보냈을 때
    # When: 저장하면
    # Then: 조용히 버린다 — 걷는 길의 '보통'은 적는 사람마다 다른 말이라 뺐다
    #   (`decisions.md` §2.16). 자른 자리만 남으므로 구간 자체가 사라진다.
    assert "segments" not in coerce(
        _ROUTES, [_route(segments=[{"from": 0, "level": "어려움"}])]
    )[0]


def test_노면만_적어도_구간이_남는다():
    # Given: 암릉도 설명도 아직 못 적고 노면만 봤을 때
    # When: 저장하면
    # Then: 구간이 남는다 — 노면 하나로도 그 구간은 무언가를 말하고 있다
    routes = coerce(_ROUTES, [_route(segments=[{"from": 0, "surface": "포장"}])])
    assert _tagged(routes[0])["segments"] == [{"from": 0, "surface": "포장"}]


def test_모르는_노면을_막는다():
    # Given: 국립공원공단 5단 밖의 낱말이 왔을 때
    # When: 저장하면
    # Then: 막는다 — 야자매트는 원문 축에 없다. 데크·포장이면 `포장` 이다
    with pytest.raises(ValueError, match="모르는 노면"):
        coerce(_ROUTES, [_route(segments=[{"from": 0, "surface": "야자매트"}])])


def test_모르는_암릉을_막는다():
    with pytest.raises(ValueError, match="모르는 암릉"):
        coerce(_ROUTES, [_route(segments=[{"from": 0, "rock": "바위 조금"}])])


def test_지형은_배점표를_고르는_값이라_아무_말이나_못_적는다():
    # Given: 둘레길·능선부 / 계곡·사면부 밖의 낱말이 왔을 때
    # When: 저장하면
    # Then: 막는다 — 이 값이 경사도·거리 배점표를 고른다(`core.trail`)
    got = coerce(_ROUTES, [_route(terrain="계곡·사면부")])
    assert got[0]["terrain"] == "계곡·사면부"
    with pytest.raises(ValueError, match="모르는 지형"):
        coerce(_ROUTES, [_route(terrain="오름")])


# --- 만들어진 페이지 ----------------------------------------------------------


def test_페이지_자바스크립트가_구문에_맞는다():
    # Given: 화면 코드는 파이썬 **일반 문자열**(`_HTML`) 안에 통째로 들어 있고,
    #   `\n` 같은 escape 를 한 자로 적으면 파이썬이 먼저 바꿔서 JS 문자열이 그
    #   자리에서 끊긴다. 그러면 화면은 아무 말 없이 **검은 화면**만 뜬다.
    # When: 페이지를 만들어 구문 검사를 돌리면
    # Then: 통과해야 한다. 이건 열어 봐야만 드러나는 결함이라 여기서 막는다.
    node = shutil.which("node")
    if not node:
        pytest.skip("node 가 없어 구문 검사를 건너뜁니다")

    html = build_page("test-key", Spots(path.SPOTS))
    blocks = re.findall(
        r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S
    )
    assert blocks, "화면 코드가 담긴 script 블록을 찾지 못했습니다"

    for i, code in enumerate(blocks, 1):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", encoding="utf-8", delete=False
        ) as file:
            file.write(code)
        result = subprocess.run(
            [node, "--check", file.name], capture_output=True, text=True
        )
        Path(file.name).unlink()
        assert result.returncode == 0, f"{i}번째 script 구문 오류:\n{result.stderr}"


def test_경사는_사람이_적는_값이_아니다():
    # Given: 화면이 경사를 지어내 보냈을 때
    # When: 저장하면
    # Then: 무시하고 **표고 격자에서 다시 잰다**(`core/elevation.py`).
    #   이 값은 좌표만으로 정해지므로 사람이 적을 자리가 아니다.
    got = coerce(_ROUTES, [_route(slope_deg=99, climb_m=999, over_m=1)])[0]
    assert got["slope_deg"] != 99
    assert got["over_m"] == round(elevation.length_m([_A, _B]), 1)


def test_격자_두_칸보다_짧으면_경사를_안_낸다():
    # Given: 격자 두 칸(약 62m)보다 짧은 선일 때
    # When: 저장하면
    # Then: 키를 만들지 않는다 — 0° 로 두면 '평평하다'로 읽히는데, 실제로는
    #   양 끝점이 같은 칸이라 **못 잰** 것이다
    near = [_A, [_A[0] + 0.0001, _A[1]]]          # 약 11m
    assert elevation.length_m(near) < elevation.MIN_M
    got = coerce(_ROUTES, [{"points": near}])[0]
    assert "slope_deg" not in got and "climb_m" not in got
