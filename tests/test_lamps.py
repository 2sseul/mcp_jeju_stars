"""lamps — 가로등·보안등 근접도 (순수 함수 + 정적 CSV 조회).

데이터 출처·좌표 교정 근거는 `server/core/lamps.py` 모듈 독스트링과
`docs/decisions.md` §1.8.

네트워크는 쓰지 않는다. CSV 2종은 저장소에 있는 정적 파일이다.
"""

from __future__ import annotations

import pytest

from server.core import lamps
from server.core.lamps import assess, normalize_coord

# --- 좌표 교정 ----------------------------------------------------------------


def test_정상_좌표는_그대로_돌려준다():
    # Given: 제주 안의 정상 (위도, 경도) 가 주어졌을 때
    # When: 교정 함수를 통과시키면
    # Then: 손대지 않고 그대로 나온다
    assert normalize_coord(33.4762, 126.8229) == (33.4762, 126.8229)


def test_위경도가_뒤바뀐_행을_되돌린다():
    # Given: 원본 제주시 파일처럼 위도 칸에 경도가 든 행이 주어졌을 때
    #        (한림읍 실제 행: 위도=126.2964554, 경도=33.41672134)
    # When: 교정 함수를 통과시키면
    fixed = normalize_coord(126.2964554, 33.41672134)
    # Then: 제주의 위도(33)·경도(126) 범위가 겹치지 않으므로 확정적으로 되돌아온다
    assert fixed == (33.41672134, 126.2964554)


def test_제주_밖_좌표는_버린다():
    # Given: 추자면(≈33.95°N)처럼 서비스 범위를 벗어난 좌표가 주어졌을 때
    # When: 교정 함수를 통과시키면
    # Then: 어느 쪽으로도 해석되지 않아 None 이다
    assert normalize_coord(33.95, 126.30) is None


# --- 로드 ---------------------------------------------------------------------


def test_두_파일을_합쳐_충분한_수가_로드된다():
    # Given: 제주시(52,019행)·서귀포시(38,022행) CSV 를 합쳐 로드했을 때
    # When: 사용 가능한 가로등 수를 세면
    # Then: 좌표 교정이 동작해 8만 개 이상이 남는다
    #       (교정 없이 걸러내면 7만 3천 대로 떨어져 동부 중산간이 통째로 빠진다)
    assert lamps.COUNT > 80_000


# --- 조회 ---------------------------------------------------------------------


def test_한라산_고지대는_반경_1km에_가로등이_없다():
    # Given: 1100고지 휴게소 좌표가 주어졌을 때
    result = assess(33.3583, 126.4675)
    # When: 주변 가로등을 세면
    # Then: 한 개도 없고, 최근접 거리는 '없음'(None)이다
    assert result.far == 0
    assert result.nearest_m is None


def test_도심은_100m_안에_가로등이_여럿이다():
    # Given: 제주시청 좌표가 주어졌을 때
    result = assess(33.4996, 126.5312)
    # When: 주변 가로등을 세면
    # Then: 바로 옆에 여러 개가 있다
    assert result.nearest_m is not None and result.nearest_m < 100
    assert result.near >= 10


def test_반경_집계는_넓을수록_커진다():
    # Given: 가로등이 섞여 있는 지점(용눈이오름)에서
    result = assess(33.4762, 126.8229)
    # When: 100m·500m·1km 집계를 비교하면
    # Then: 포함관계가 성립한다 (100m ⊂ 500m ⊂ 1km)
    assert result.near <= result.mid <= result.far


@pytest.mark.parametrize(
    ("name", "lat", "lon"),
    [
        pytest.param("용눈이오름", 33.4762, 126.8229, id="동부 중산간(교정된 구좌읍)"),
        pytest.param("산굼부리", 33.4331, 126.6906, id="동부 중산간(교정된 조천읍)"),
    ],
)
def test_교정된_읍면_지역에도_가로등이_잡힌다(name, lat, lon):
    # Given: 원본에서 위경도가 뒤바뀌어 있던 읍·면의 관측지가 주어졌을 때
    result = assess(lat, lon)
    # When: 주변 가로등을 조회하면
    # Then: 0개가 아니다 — 교정을 빼먹으면 여기가 통째로 '가로등 없음'이 된다
    assert result.far > 0, f"{name}: 좌표 교정이 빠지면 거짓 '광원 없음'이 된다"
