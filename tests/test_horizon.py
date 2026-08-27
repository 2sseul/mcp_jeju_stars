"""core.horizon — 이 자리에서 하늘이 어느 방위로 얼마나 막혔나.

표고 격자를 실제로 읽는다(네트워크는 없다). 그래서 여기서 보는 것은 **제주 지형이
그렇게 생겼는가**다 — 한라산이 어느 쪽인지, 바다가 어느 쪽인지는 좌표로 정해져 있어서,
계산이 틀리면 그 사실과 어긋난다.

격자가 없는 환경(배포 컨테이너)에서는 대부분을 건너뛴다 — `profile` 이 None 을 내는
것 자체가 계약이라 그것만 확인한다.
"""

from __future__ import annotations

import json

import pytest

from server import path
from server.core import elevation, horizon

pytestmark = pytest.mark.skipif(
    not elevation.HAS_GRID, reason="표고 격자가 없다(배포 묶음과 같은 상태)"
)

#: 관측지 좌표는 데이터에서 읽는다 — 여기에 베껴 두면 좌표가 바뀔 때 조용히 어긋난다.
_SPOTS = {
    s["name_ko"]: (s["lat"], s["lon"])
    for s in json.loads(path.SPOTS.read_text(encoding="utf-8"))["spots"]
}


def _profile(name: str) -> dict[str, float]:
    lat, lon = _SPOTS[name]
    prof = horizon.profile(lat, lon)
    assert prof is not None, name
    return prof


# --- 제주 지형이 그렇게 생겼는가 ---------------------------------------------------


def test_영실은_한라산_쪽이_가장_막힌다():
    # Given: 영실입구 주차장(해발 1,216m)은 한라산 **남서쪽 기슭**이다.
    #        정상은 거기서 북동쪽에 있다
    prof = _profile("영실입구 주차장")
    # Then: 가장 막힌 방위가 북동쪽이고, 10도를 넘는다 — 산이 코앞에 솟아 있다
    worst = max(prof, key=lambda k: prof[k])
    assert worst == "북동", prof
    assert prof["북동"] > 10.0


def test_화순방파제는_바다_쪽이_트이고_산방산_쪽이_막힌다():
    # Given: 화순방파제(해발 4m)는 남쪽이 바다, 북서쪽에 산방산(395m)이 있다
    prof = _profile("화순방파제")
    # Then: 바다 쪽은 지형이 없어 트여 있고, 산방산 쪽은 10도를 넘게 막힌다.
    #       바다를 '낮은 지형'으로 세면 여기가 뒤집힌다(결측은 버려야 한다)
    assert prof["남"] < horizon.OPEN_DEG, prof
    assert prof["북서"] > 10.0, prof


def test_사방이_개활한_오름은_지평선이_낮다():
    # Given: 용눈이오름은 데이터가 "사방 개활"이라 적어 둔 동부 중산간 관측지다
    prof = _profile("용눈이오름")
    # Then: 어느 방위도 크게 막히지 않는다. 5도를 넘으면 개활이라는 말과 어긋난다
    assert max(prof.values()) < 5.0, prof


def test_지평선은_여덟_방위를_빠짐없이_낸다():
    # Given: 별자리는 8방위로 답하므로 방위마다 값이 있어야 한다
    prof = _profile("새별오름")
    # Then: 이름과 순서가 별자리·관측지 쪽과 같고, 음수가 없다
    assert list(prof) == list(horizon.BEARINGS)
    assert all(v >= 0.0 for v in prof.values())


# --- 곡률 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("km", "metres"),
    [
        pytest.param(5.0, 2.0, id="5km"),
        pytest.param(20.0, 31.0, id="20km"),
        pytest.param(30.0, 71.0, id="30km"),
    ],
)
def test_지구_곡면_강하는_거리제곱에_비례한다(km, metres):
    # Given: drop = d²/2R (R = IUGG 평균 반지름)
    got = horizon.drop_m(km * 1000.0)
    # Then: 문서에 적어 둔 값과 맞는다. 이 보정을 빼면 먼 지형을 실제보다 높게 잡아
    #       한라산 쪽 지평선이 부풀어 오른다
    assert got == pytest.approx(metres, abs=1.0)


def test_곡률_보정이_먼_지형의_지평선을_낮춘다():
    # Given: 관측자와 같은 높이의 지형이 20km 밖에 있다면
    d = 20_000.0
    # When: 곡면 강하를 빼면
    # Then: 시선이 그 지형 위로 지나간다 = 고도각이 음수다.
    #       보정이 없으면 정확히 0도가 되어 "막혔다"고 잘못 셀 수 있다
    assert horizon.drop_m(d) > 0.0


# --- 서술 -----------------------------------------------------------------------


def test_트인_쪽을_먼저_말한다():
    # Given: 한쪽만 크게 막힌 자리(영실)에서
    lines = horizon.describe(_profile("영실입구 주차장"))
    # Then: 첫 문장이 트인 방위로 시작한다 — 관측자가 정해야 하는 것은
    #       "어디가 막혔나"보다 "어디를 보고 서나"다
    assert lines[0].startswith("하늘이 트인 쪽은")
    assert "북동쪽은 지형이" in lines[0]


def test_지형만_잰_값임을_밝힌다():
    # Given: 격자는 맨땅(FABDEM)이라 방풍림·건물이 빠져 있다
    lines = horizon.describe(_profile("새별오름"))
    # Then: 그 사실을 문장으로 남긴다 — 안 밝히면 "안 막혔다"가 확인된 사실처럼 읽힌다
    assert any("방풍림" in x for x in lines)


def test_못_쟀으면_아무_말도_하지_않는다():
    # Given: 표고 격자가 없어 지평선을 못 낸 경우
    # Then: 빈 목록이다 — 모르는 것을 "트여 있다"고 하지 않는다
    assert horizon.describe(None) == []
    assert horizon.describe({}) == []


def test_격자_밖_좌표는_None이다():
    # Given: 격자가 덮지 않는 좌표(제주 밖)
    # When: 지평선을 재면
    # Then: 0도가 아니라 None 이다. 0도로 두면 "사방이 트였다"고 답하게 된다
    assert horizon.profile(37.5665, 126.9780) is None
