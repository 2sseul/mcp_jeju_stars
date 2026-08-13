"""edit_spots — 화면이 보낸 도보 경로를 파일에 넣을 값으로 바꾸는 부분.

이 도구는 `data/jeju_spots.json` 에 **직접 쓴다**. 그래서 검증이 마지막 관문이다 —
반쯤 이상한 값이 들어간 파일이 제일 나쁘고, 그건 다음에 열었을 때가 아니라 판정이
그 관측지를 조용히 빼먹을 때 드러난다.

경로와, 그와 같은 이유로 **여럿일 수 있는** 주차 자리·화장실을 본다. 나머지 형식
(text·bool·point…)은 이 파일보다 오래됐고 쓰이는 곳도 많아 이미 데이터로 검증돼 있다.
편의시설(`flags`)은 세 상태를 갖게 되면서 규약이 걸린 값이 되어 함께 본다.

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

from scripts.edit_spots import Column, Spots, apply, build_page, coerce
from server import path
from server.core import elevation

_ROUTES = Column("walk_routes", "도보 경로", "routes")
_PARKING = Column("parking", "주차 지점", "parking")
_TOILET = Column("toilet", "화장실 위치", "points")
_AMENITIES = Column("amenities", "편의시설", "flags")
_COORDS = Column("coords", "관측 좌표", "coords")
_ELEVATION = Column("elevation_m", "해발높이(m)", "measured")

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


def test_도보_시간은_받지_않는다():
    # Given: 옛 화면이 길마다 도보 시간을 적게 하던 시절의 값이 섞여 들어올 때
    # When: 저장하면
    # Then: 버린다 — 계단·오르막이 섞인 길의 분은 재도 눈대중이라 아예 두지 않는다.
    #       힘든 정도는 경사·거리·노면·암릉으로 내는 탐방로 등급이 말한다
    assert "minutes" not in coerce(_ROUTES, [_route(minutes="20")])[0]


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


# --- 주차 자리 ----------------------------------------------------------------


def test_안_봤으면_키를_지우고_봤는데_없으면_false_다():
    # Given: 아직 안 본 관측지와, 가 봤는데 댈 데가 없던 관측지일 때
    # When: 저장하면
    # Then: 앞은 키가 없고 뒤는 false 다 — 둘을 같은 값으로 두면 남은 일이
    #   파일에서 안 보인다
    assert coerce(_PARKING, []) is None
    assert coerce(_PARKING, None) is None
    assert coerce(_PARKING, False) is False


def test_들머리가_갈리면_자리도_갈린다():
    # Given: 오름 하나에 남쪽 주차장과 북동쪽 갓길이 따로 있고 한쪽만 유료일 때
    # When: 저장하면
    # Then: 자리마다 요금이 따로 남는다 — 관측지에 한 값으로 적으면 어느 자리
    #   말인지 알 수 없다
    assert coerce(_PARKING, [
        {"name": "남쪽 주차장", "lat": _A[0], "lon": _A[1], "fee": "유료"},
        {"name": "북동쪽 갓길", "lat": _B[0], "lon": _B[1], "fee": "무료"},
    ]) == [
        {"name": "남쪽 주차장", "lat": _A[0], "lon": _A[1], "fee": "유료"},
        {"name": "북동쪽 갓길", "lat": _B[0], "lon": _B[1], "fee": "무료"},
    ]


def test_요금을_아직_안_봤으면_키를_만들지_않는다():
    # Given: 자리는 찍었는데 유료인지 무료인지는 아직 못 본 상태일 때
    # When: 저장하면
    # Then: fee 키가 없다 — 이 파일에서 없는 키가 곧 '아직 안 봤다'다
    got = coerce(_PARKING, [{"name": "", "lat": _A[0], "lon": _A[1], "fee": ""}])
    assert got == [{"name": "", "lat": _A[0], "lon": _A[1]}]


def test_모르는_요금을_막는다():
    # Given: 유료·무료 밖의 말이 왔을 때
    # When: 저장하면
    # Then: 막는다 — 액수는 `요금` 칸이 받고 여기는 돈을 받는가만 둔다
    with pytest.raises(ValueError, match="모르는 요금"):
        coerce(_PARKING, [{"lat": _A[0], "lon": _A[1], "fee": "3000원"}])


def test_주차_자리도_제주_밖을_막는다():
    with pytest.raises(ValueError, match="제주 밖"):
        coerce(_PARKING, [{"lat": 35.1, "lon": 129.0}])


# --- 화장실 -------------------------------------------------------------------


def test_화장실도_세_상태를_그대로_둔다():
    # Given: 아직 안 본 관측지와, 가 봤는데 없던 관측지일 때
    # When: 저장하면
    # Then: 앞은 키가 없고 뒤는 false 다 — 여럿이 됐다고 빈 목록이 '없다'가 되지
    #   않는다. 빈 목록은 아직 아무것도 안 적은 것이라 미확인이다
    assert coerce(_TOILET, []) is None
    assert coerce(_TOILET, None) is None
    assert coerce(_TOILET, False) is False


def test_쓸_만한_화장실을_다_적는다():
    # Given: 주차장 옆과 들머리 위에 하나씩 있을 때
    # When: 저장하면
    # Then: 둘 다 남는다 — 밤에 어느 쪽이 열려 있는지는 여기서 알 수 없어서,
    #   한 곳만 남기면 가 보고 잠겨 있을 때 나머지가 파일에 없다
    assert coerce(_TOILET, [
        {"name": "주차장 화장실", "lat": _A[0], "lon": _A[1]},
        {"name": "들머리 화장실", "lat": _B[0], "lon": _B[1]},
    ]) == [
        {"name": "주차장 화장실", "lat": _A[0], "lon": _A[1]},
        {"name": "들머리 화장실", "lat": _B[0], "lon": _B[1]},
    ]


def test_화장실에는_요금이_붙지_않는다():
    # Given: 화면이 주차 자리처럼 요금을 실어 보냈을 때
    # When: 저장하면
    # Then: 버린다 — 자리마다 갈리는 값이 있는 것은 주차뿐이고, 개방시간·비상벨은
    #   공중화장실 원본(`core.toilet`)이 들고 있지 여기 옮겨 적을 것이 아니다
    got = coerce(_TOILET, [{"name": "", "lat": _A[0], "lon": _A[1], "fee": "유료"}])
    assert got == [{"name": "", "lat": _A[0], "lon": _A[1]}]


def test_화장실도_제주_밖을_막는다():
    with pytest.raises(ValueError, match="제주 밖"):
        coerce(_TOILET, [{"lat": 35.1, "lon": 129.0}])


# --- 편의시설 -----------------------------------------------------------------


def test_편의시설은_세_상태다():
    # Given: 화장실을 가 봤는데 없던 관측지일 때
    # When: 저장하면
    # Then: false 가 그대로 남는다 — 한때 true 만 남겼는데, 그러면 확인하러 간
    #   관측지와 아직 안 본 관측지가 파일에서 같아 보인다
    assert coerce(_AMENITIES, {"toilet": False}) == {"toilet": False}
    assert coerce(_AMENITIES, {"toilet": True}) == {"toilet": True}
    assert coerce(_AMENITIES, {}) is None


def test_편의시설의_미확인은_키가_없는_것이다():
    # Given: 화면이 '미확인'을 고른 항목을 아예 빼고 보냈을 때
    # When: 저장하면
    # Then: 그 키가 없다. 남은 항목만 적힌다
    assert coerce(_AMENITIES, {"toilet": False, "bench": None}) == {"toilet": False}


def test_편의시설에_예_아니오가_아닌_값을_막는다():
    with pytest.raises(ValueError, match="예·아니오"):
        coerce(_AMENITIES, {"toilet": "있음"})


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


def test_좌표를_옮기면_해발높이가_따라온다():
    # Given: 다른 자리의 해발높이를 들고 있는 관측지에서
    spot = {"name_ko": "옮기는 곳", "lat": _A[0], "lon": _A[1],
            "elevation_m": 808, "slope_deg": 17.4}
    # When: 좌표만 옮겨 저장하면
    apply(spot, [_COORDS], {"coords": {"lat": _B[0], "lon": _B[1]}})
    # Then: 두 칸이 그 자리 값으로 따라 바뀐다. 예전에는 배치를 따로 부르지 않으면
    #   옛 자리 값이 그대로 남았고, 실제로 27곳이 그렇게 어긋나 있었다
    assert spot["elevation_m"] == round(elevation.at(*_B))
    assert spot["slope_deg"] == elevation.slope_at(*_B)


def test_해발높이는_사람이_적는_값이_아니다():
    # Given: 화면이 해발높이를 지어내 보냈을 때
    spot = {"name_ko": "손댄 곳", "lat": _A[0], "lon": _A[1]}
    # When: 저장하면
    # Then: 저장 **자체가** 막힌다. 경로의 잰 값(위)은 조용히 다시 재면 되지만,
    #   이쪽은 사람이 친 숫자를 받아 둘 자리가 아예 없다 — 좌표만으로 정해지는
    #   값이라 둘이 갈리면 어느 쪽이 맞는지 알 수가 없다
    with pytest.raises(ValueError):
        apply(spot, [_ELEVATION], {"elevation_m": 999})


def test_격자_두_칸보다_짧으면_경사를_안_낸다():
    # Given: 격자 두 칸(약 62m)보다 짧은 선일 때
    # When: 저장하면
    # Then: 키를 만들지 않는다 — 0° 로 두면 '평평하다'로 읽히는데, 실제로는
    #   양 끝점이 같은 칸이라 **못 잰** 것이다
    near = [_A, [_A[0] + 0.0001, _A[1]]]          # 약 11m
    assert elevation.length_m(near) < elevation.MIN_M
    got = coerce(_ROUTES, [{"points": near}])[0]
    assert "slope_deg" not in got and "climb_m" not in got
