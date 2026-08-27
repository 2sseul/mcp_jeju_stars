"""core.constellation — 별자리가 하늘 어디에 있나.

성표를 실제로 읽으므로 네트워크는 없지만 계산은 진짜다. 그래서 여기서 보는 것은
**하늘이 그렇게 생겼는가**다 — 제주 위도에서 반드시 참인 사실(주극·남천)을 걸어 두면,
좌표계를 잘못 다루거나 데이터가 어긋났을 때 바로 드러난다.

문헌 경계(Bortle 한계등급)는 경계값 자체를 케이스로 넣는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from server.core import constellation as C

KST = ZoneInfo("Asia/Seoul")

#: 새별오름. 제주 중산간의 대표 관측지.
JEJU = (33.3663, 126.3576)

#: 제주 위도. 주극/남천 판정의 기준이다.
LAT = JEJU[0]

WHEN = datetime(2026, 8, 27, 23, 0, tzinfo=KST)


def _by_abbr(got: list[C.Constellation]) -> dict[str, C.Constellation]:
    return {c.abbr: c for c in got}


# --- 하늘이 그렇게 생겼는가 -------------------------------------------------------


def test_작은곰자리는_밤새_북쪽에_떠_있다():
    # Given: 적위가 90-위도(약 56.6도)보다 큰 별자리는 제주에서 지지 않는다(주극).
    #        작은곰자리는 북극성을 품으므로 그 조건에 든다
    # When: 밤새 여섯 시각을 재면
    for h in range(0, 24, 4):
        got = _by_abbr(C.assess(*JEJU, WHEN + timedelta(hours=h)))
        umi = got["UMi"]
        # Then: 언제나 지평 위이고, 언제나 북쪽이다 — 하나라도 어긋나면 좌표계가
        #       뒤집혔거나 방위 변환이 틀린 것이다
        assert umi.up, f"{h}시에 작은곰자리가 졌다 (고도 {umi.altitude_deg})"
        assert umi.bearing.startswith("북"), f"{h}시 방위가 {umi.bearing}"


def test_북극성_방향의_고도는_관측지_위도와_같다():
    # Given: 천구 북극의 고도는 관측자의 위도와 같다(구면천문학의 기본)
    got = _by_abbr(C.assess(*JEJU, WHEN))
    umi = got["UMi"]
    # Then: 작은곰자리의 방향 평균은 북극 근처이므로 고도가 위도에 가깝다.
    #       15도 안쪽이면 별자리 크기를 감안해 맞다고 본다
    assert abs(umi.altitude_deg - LAT) < 15.0


def test_남십자자리는_제주에서_뜨지_않는다():
    # Given: 남십자자리는 적위가 약 -60도라, 제주(북위 33.4도)에서는
    #        (-90 + 위도) = -56.6도보다 남쪽이라 지평 위로 올라오지 못한다
    # When: 하루를 통틀어 재면
    for h in range(0, 24, 3):
        got = _by_abbr(C.assess(*JEJU, WHEN + timedelta(hours=h)))
        # Then: 한 번도 뜨지 않는다 — 뜬다고 답하면 "남쪽 하늘을 보세요"라는
        #       영영 이룰 수 없는 안내를 하게 된다
        assert not got["Cru"].up, f"{h}시에 남십자자리가 떴다"


def test_별자리는_한_시간에_약_15도씩_돈다():
    # Given: 지구 자전으로 하늘은 한 시간에 15도 돈다
    a = _by_abbr(C.assess(*JEJU, WHEN))["Ori"]
    b = _by_abbr(C.assess(*JEJU, WHEN + timedelta(hours=1)))["Ori"]
    # When: 같은 별자리를 한 시간 간격으로 재면
    # Then: 위치가 실제로 움직인다. 안 움직이면 시각이 계산에 안 들어간 것이다
    moved = abs(a.altitude_deg - b.altitude_deg) + abs(a.azimuth_deg - b.azimuth_deg)
    assert moved > 5.0, f"한 시간 동안 {moved:.1f}도밖에 안 움직였다"


def test_여름밤_제주에서는_여름_대삼각형이_높이_뜬다():
    # Given: 8월 말 23시 — 백조·거문고·독수리자리(여름 대삼각형)의 계절이다
    got = _by_abbr(C.assess(*JEJU, WHEN))
    # Then: 셋 다 지평 위이고, 지형에 가릴 걱정 없는 높이(30도 위)다.
    #       계절이 어긋나면 여기서 드러난다
    for abbr, name in (("Cyg", "백조"), ("Lyr", "거문고"), ("Aql", "독수리")):
        c = got[abbr]
        assert c.altitude_deg > C.HIGH_ALT_DEG, f"{name}자리 고도 {c.altitude_deg}"


# --- 방향 평균 (적경 0시를 걸쳐도 맞나) --------------------------------------------


def test_적경_0시를_걸친_별자리도_제_방향을_가리킨다():
    # Given: 페가수스자리는 적경 21시~0시에 걸쳐 있다. 각도를 산술평균하면
    #        350도와 10도의 평균이 180도가 되어 하늘 반대편을 가리킨다
    got = _by_abbr(C.assess(*JEJU, WHEN))
    peg = got["Peg"]
    # When: 8월 말 23시에 보면
    # Then: 페가수스는 동쪽에서 올라오는 중이다(가을 별자리). 반대편(서쪽)을
    #       가리킨다면 벡터 평균이 아니라 각도 평균을 쓴 것이다
    assert peg.up
    assert peg.bearing in ("동", "북동", "남동"), f"방위가 {peg.bearing}"


def test_방향_평균은_별이_없으면_None이다():
    # Given: 별이 하나도 없는 목록에서
    # When: 방향을 구하면
    # Then: 0도가 아니라 None 이다 — 0도로 두면 "북쪽을 보세요"라고 답하게 된다
    assert C._direction([]) is None


# --- 방위 변환 -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("azimuth", "expected"),
    [
        pytest.param(0.0, "북", id="정북"),
        pytest.param(22.4, "북", id="북_경계_직전"),
        pytest.param(22.5, "북동", id="북동_경계"),
        pytest.param(180.0, "남", id="정남"),
        pytest.param(270.0, "서", id="정서"),
        pytest.param(359.9, "북", id="한바퀴_직전"),
        pytest.param(360.0, "북", id="한바퀴"),
        pytest.param(-90.0, "서", id="음수도_감는다"),
    ],
)
def test_방위각은_8방위로_바뀐다(azimuth, expected):
    # Given: 방위각이 경계에 있을 때
    # When: 사람 말로 옮기면
    # Then: 북이 0도이고 시계방향이다. 경계에서 한 칸 밀리면 "동"을 "북동"이라 한다
    assert C.bearing_ko(azimuth) == expected


# --- 한계등급 (Bortle 2001) --------------------------------------------------------


@pytest.mark.parametrize(
    ("bortle", "nelm"),
    [
        pytest.param(1, 7.6, id="Bortle1_최상급_암흑"),
        pytest.param(4, 6.1, id="Bortle4_시골_교외_전이"),
        pytest.param(5, 5.6, id="Bortle5_교외"),
        pytest.param(9, 4.0, id="Bortle9_도심"),
    ],
)
def test_Bortle_등급은_원문_한계등급으로_바뀐다(bortle, nelm):
    # Given: Bortle(2001)이 등급마다 밝힌 맨눈 한계등급이 있고,
    #        범위로 준 등급은 보수적으로 하한을 쓴다
    # When/Then: 값 자체를 케이스로 둔다 — 임의로 바뀌면 여기서 걸린다
    assert C.nelm_of(bortle) == nelm


@pytest.mark.parametrize("bortle", [None, 0, 99])
def test_모르는_등급은_교외_하늘로_본다(bortle):
    # Given: 어둡기 격자 밖이거나 등급이 이상할 때
    # When: 한계등급을 물으면
    # Then: 다 보인다고도, 다 못 본다고도 하지 않고 교외(Bortle 5)로 둔다
    assert C.nelm_of(bortle) == C.NELM_FALLBACK


def test_하늘이_밝을수록_보이는_별이_줄어든다():
    # Given: 같은 자리·같은 시각에서 하늘 밝기만 바꾸면
    dark = _by_abbr(C.assess(*JEJU, WHEN, bortle=2))
    bright = _by_abbr(C.assess(*JEJU, WHEN, bortle=9))
    # When: 별자리마다 보이는 별 수를 비교하면
    # Then: 밝은 하늘에서 더 많이 보이는 별자리는 하나도 없다.
    #       (달이 뜨면 줄어드는 것도 같은 경로를 탄다 — assess_sky 의 등급이 올라간다)
    for abbr, d in dark.items():
        assert bright[abbr].visible_stars <= d.visible_stars, abbr


def test_별_하나만_걸리면_별자리로_치지_않는다():
    # Given: 지평 위에 있고 별이 하나만 한계등급을 넘는 상황
    one = C.Constellation(
        abbr="Xxx", latin="X", english="X", korean="엑스자리",
        altitude_deg=50.0, azimuth_deg=180.0, bearing="남",
        visible_stars=1, total_stars=8, brightest=1.0,
    )
    # Then: 선을 이으려면 둘이 필요하므로 '알아볼 만하다'고 하지 않는다
    assert one.up
    assert not one.naked_eye


# --- 데이터 계약 -------------------------------------------------------------------


def test_별자리는_88개이고_전부_한국어_이름이_있다():
    # Given: IAU 공인 별자리는 88개다
    got = C.assess(*JEJU, WHEN)
    # Then: 하나도 빠지지 않고, 응답에 쓸 한국어 이름이 다 있다.
    #       비어 있으면 한국어 답 안에 "Camelopardalis" 가 섞인다
    assert len(got) == 88
    for c in got:
        assert c.korean, c.abbr
        assert c.korean.endswith("자리"), c.korean


def test_출처를_축어로_들고_있다():
    # Given: 별자리 구성 데이터는 CC BY-SA 4.0 이라 **귀속이 라이선스 조건**이다
    # When: 모듈이 노출하는 출처를 보면
    # Then: 비어 있지 않고, 두 1차 출처가 이름으로 들어 있다
    joined = " / ".join(C.SOURCES)
    assert "Stellarium" in joined
    assert "Hipparcos" in joined


def test_고도가_높은_순으로_돌려준다():
    # Given: 부르는 쪽은 "가장 잘 보이는 것부터" 몇 개만 쓴다
    got = C.assess(*JEJU, WHEN)
    # Then: 이미 정렬돼 있어 호출자가 다시 정렬하지 않아도 된다
    alts = [c.altitude_deg for c in got]
    assert alts == sorted(alts, reverse=True)


# --- 무엇을 먼저 말하나 ------------------------------------------------------------


def _fake(
    korean: str, alt: float, mag: float | None, stars: int = 6
) -> C.Constellation:
    """서술만 보려고 만든 별자리. 성표를 타지 않는다."""
    return C.Constellation(
        abbr=korean[:3], latin=korean, english=korean, korean=korean,
        altitude_deg=alt, azimuth_deg=180.0, bearing="남",
        visible_stars=stars, total_stars=stars, brightest=mag,
    )


def test_밝기로_거르고_고도로_정렬한다():
    # Given: 지평선에 걸린 밝은 별자리와 천정의 밝은 별자리, 그리고 어두운 것이 있을 때
    got = [
        _fake("전갈자리", 3.0, 1.06),
        _fake("백조자리", 79.0, 1.25),
        _fake("작은여우자리", 73.0, 4.44),
    ]
    top = C.highlights(got)
    # Then: 1등성이 아닌 작은여우자리는 빠지고, 남은 둘은 **고도순**이다.
    #       밝기순으로 늘어놓으면 지평선 3도가 천정 79도보다 앞에 온다
    assert [c.korean for c in top] == ["백조자리", "전갈자리"]


def test_1등성이_없으면_고르지_않는다():
    # Given: 죄다 어두운 별자리뿐일 때
    got = [_fake("조랑말자리", 64.0, 3.92), _fake("도마뱀자리", 68.0, 3.77)]
    # Then: 빈 목록이다 — 개수를 채우려고 어두운 것을 끌어올리지 않는다
    assert C.highlights(got) == []
    assert C.describe(got) == []


def test_등급을_모르는_별자리는_고르지_않는다():
    # Given: 성표에서 등급을 못 받은 별자리가 섞여 있을 때
    got = [_fake("이름없음", 70.0, None)]
    # Then: 밝다고도 어둡다고도 할 수 없으므로 앞세우지 않는다
    assert C.highlights(got) == []


def test_높이_뜬_것과_낮게_뜬_것을_문장부터_가른다():
    # Given: 천정 근처와 지평선 근처가 섞여 있을 때
    got = [_fake("백조자리", 79.0, 1.25), _fake("전갈자리", 3.0, 1.06)]
    lines = C.describe(got)
    # Then: 두 문장으로 갈린다. 한 줄에 섞으면 지평선에 걸린 것을 천정의 것과
    #       같은 무게로 읽게 된다
    assert len(lines) == 2
    assert "잘 보이는" in lines[0] and "백조자리" in lines[0]
    assert "낮게" in lines[1] and "전갈자리" in lines[1]
    # 그리고 낮은 것에는 단정 대신 단서를 붙인다(지형을 실제로 재지 않으므로)
    assert "가릴 수 있으니" in lines[1]


def test_지평_아래는_아예_말하지_않는다():
    # Given: 1등성을 품었지만 진 별자리
    got = [_fake("남십자자리", -20.0, 0.77)]
    # Then: 목록에도 문장에도 없다 — "남쪽을 보세요"라고 하면 영영 못 볼 것을 시킨다
    assert C.highlights(got) == []
    assert C.describe(got) == []
