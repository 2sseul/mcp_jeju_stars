"""별자리 축 — 어느 별자리가 하늘 어디에 있는가 (순수 함수 + 성표 조회).

`darkness.py` 가 **장소**를, `moon.py` 가 **그 밤**을 다룬다면 이 모듈은 **그 순간의
하늘**을 다룬다. 별자리는 지구 자전으로 한 시간에 15도씩 도므로, 같은 밤에도 시각마다
답이 다르다.

무엇을 답하는가
--------------------------------------------------------------------------
    "어느 별자리가 보이나"      →  지평 위에 있고, 그 하늘 밝기에서 눈에 잡히는 것들
    "어느 쪽을 봐야 하나"       →  방위(8방위)와 고도(도)

**개수는 세지 않는다**(`decisions.md` §2.14). "별 1,847개"는 어디로 갈지·어디를
볼지 정하는 데 쓰이지 않는다. 대신 이름과 방향을 준다 — 그건 현장에서 몸을 어느
쪽으로 돌릴지 바꾸는 정보다.

별자리의 '위치'를 무엇으로 잡는가 — 밝은 별들의 방향 평균
--------------------------------------------------------------------------
IAU 경계의 무게중심을 쓰지 않는다. 큰 별자리일수록 중심이 **별 없는 빈 하늘**이라,
"거기를 보세요" 가 틀린 안내가 된다.

대신 그 별자리를 이루는 별들(`data/constellations`)의 **단위벡터를 평균**해 방향을
정한다. 각도를 그냥 평균하면 적경 0시를 걸친 별자리(페가수스·물고기)에서 반대편을
가리키게 된다 — 350도와 10도의 산술평균은 180도다. 벡터로 더하면 그 문제가 없다.

밝기로 가중하지 않는 것은, 별자리를 찾을 때 사람이 보는 것이 가장 밝은 별 하나가 아니라
**무리 전체의 자리**이기 때문이다.

보이는가 — Bortle 한계등급으로 가른다
--------------------------------------------------------------------------
하늘이 밝으면 어두운 별부터 사라진다. 그 경계를 새로 만들지 않고 **Bortle(2001) 이
등급마다 명시한 맨눈 한계등급**을 그대로 쓴다(`NELM_BY_BORTLE`). 이 프로젝트는 이미
`darkness.py` 에서 Bortle 등급을 내고 있고, 달빛까지 더한 등급은
`darkness.assess_sky` 가 낸다 — 그래서 **달이 뜨면 보이는 별자리가 줄어드는 것이
저절로 따라온다.**

고도 — 낮게 뜬 것은 단서를 붙인다
--------------------------------------------------------------------------
지평 위에 있어도 낮으면 오름·나무·건물에 가린다. 고도 30도를 경계로 쓰는데, 이 값은
`cloud.py` 가 관측 시야를 잡을 때 쓰는 것과 같다("그 아래는 지형/수목에 가려지는 경우가
많아 제외"). 새 눈금을 만들지 않고 프로젝트 안에서 이미 근거를 밝힌 값을 재사용한다.

**지형을 재면 '가릴 수 있다'가 '막혀 있다'가 된다.** `horizon.profile` 이 낸 방위별
지평선을 넘겨받으면(`assess(..., horizon=...)`), 그 방위의 지평선보다 낮은 별자리는
`blocked` 가 된다 — 영실입구 주차장은 북동쪽이 한라산에 18도까지 막혀 있어, 그쪽
15도에 뜬 별자리는 하늘에 있어도 보이지 않는다.

지평선을 안 받으면 예전처럼 *가릴 수 있다*고만 말한다(배포 컨테이너에는 표고 격자가
없다). 받았더라도 격자는 **맨땅**이라 방풍림·건물은 안 잡히므로, 막히지 않았다고 나온
방위도 현장은 더 막혀 있을 수 있다 — 확인 안 된 것을 확인된 것처럼 말하지 않는
규율(`decisions.md` §2.31)이 여전히 적용된다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime

from skyfield.api import Star, wgs84

from modules import path
from modules.core.ephem import EPH, TS, require_aware
from modules.core.horizon import FIST_NOTE_TAIL, hand_span

__all__ = [
    "FIRST_MAGNITUDE",
    "HIGH_ALT_DEG",
    "HORIZON_DEG",
    "NELM_BY_BORTLE",
    "OVERHEAD_DEG",
    "SOURCES",
    "Constellation",
    "assess",
    "bearing_ko",
    "describe",
    "highlights",
    "nelm_of",
]

# --- 임계값 (전부 근거값) ------------------------------------------------------

#: 지평. 이 아래는 지구가 가린다.
HORIZON_DEG: float = 0.0

#: 이 고도 위면 지형에 가릴 걱정 없이 본다. `cloud.WINDOW_HALF` 를 정할 때 쓴 고도각
#: 컷오프와 같은 값이다 — "그 아래는 지형/수목에 가려지는 경우가 많아 제외".
HIGH_ALT_DEG: float = 30.0

#: Bortle 등급 → 맨눈 한계등급(NELM). John E. Bortle, "Gauging Light Pollution:
#: The Bortle Dark-Sky Scale", Sky & Telescope, 2001-02. 원문이 등급마다 밝힌 값이며,
#: 범위로 준 등급은 **보수적으로 하한**을 쓴다 — 안 보이는 별을 보인다고 하지 않으려고.
#:     1 "7.6 to 8.0 (with effort)"   2 "as faint as 7.1 to 7.5"
#:     3 "6.6 to 7.0"                 4 "maximum … 6.1 to 6.5"
#:     5 "around 5.6 to 6.0"          6 "about 5.5"
#:     7 "5.0 if you really try"      8 "down to magnitude 4.5 at best"
#:     9 "4.0 or less"
NELM_BY_BORTLE: dict[int, float] = {
    1: 7.6,
    2: 7.1,
    3: 6.6,
    4: 6.1,
    5: 5.6,
    6: 5.5,
    7: 5.0,
    8: 4.5,
    9: 4.0,
}

#: 이 고도 위면 "거의 머리 위"다. 천정(90도)에서 30도 안쪽인데, 그 30도는 지평에서
#: `HIGH_ALT_DEG` 로 쓰는 것과 같은 눈금이다 — 지평에서 30도가 '지형에 안 가리는
#: 높이'라면, 천정에서 30도는 '고개를 크게 젖혀야 하는 높이'다.
OVERHEAD_DEG: float = 90.0 - HIGH_ALT_DEG

#: 1등성의 경계. 등급 체계에서 "1등성 이상"으로 묶는 관례값이며, 눈에 먼저 들어오는
#: 별들이 여기 든다(베가 0.03 · 리겔 0.18 · 데네브 1.25 · 폴룩스 1.14).
#: 목록을 자를 때 **개수로 자르지 않고 이 밝기로 자른다** — "상위 3개"는 근거가 없지만
#: "1등성을 품은 별자리"는 왜 그것들인지 말할 수 있다.
FIRST_MAGNITUDE: float = 1.5

#: 별자리를 '알아본다'고 하려면 선 별이 몇 개는 보여야 하는가. 가장 밝은 별 하나만
#: 걸리는 것은 별 하나가 보이는 것이지 별자리가 보이는 것이 아니다 — 선을 이으려면
#: 둘이 필요하다. `naked_eye` 와 `lost` 가 같은 값을 봐야 경계가 어긋나지 않는다.
_MIN_LINE_STARS: int = 2

#: 한계등급을 모를 때(어둡기 격자 밖 등) 쓰는 값. Bortle 5(교외)는 제주 중산간의
#: 흔한 하늘이라, 모른다고 다 보인다고 하지 않으면서 다 못 본다고도 하지 않는다.
NELM_FALLBACK: float = NELM_BY_BORTLE[5]

#: 8방위. `spots._BEARINGS` 와 같은 이름을 쓴다 — 사용자가 같은 말("남동")을 땅과
#: 하늘에서 다르게 읽지 않게 한다.
_BEARINGS = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")


# --- 정적 데이터 (모듈 로드 시 1회) --------------------------------------------

_MISSING = (
    f"별자리 데이터가 없습니다: {path.CONSTELLATIONS}\n"
    "`uv run python -m scripts.build_constellations` 로 만드세요."
)

if not path.CONSTELLATIONS.exists():
    raise FileNotFoundError(_MISSING)

with open(path.CONSTELLATIONS, encoding="utf-8") as _f:
    _DOC = json.load(_f)

#: 데이터 귀속 — 응답 attribution 에 축어로 싣는다(CC BY-SA 4.0 은 귀속이 조건이다).
SOURCES: list[str] = list(_DOC["meta"]["sources"])


def _direction(stars: list[dict]) -> tuple[float, float] | None:
    """별들의 방향을 평균해 (적경 시, 적위 도)로. 별이 없으면 None.

    단위벡터를 더해 평균한다 — 각도를 그냥 평균하면 적경 0시를 걸친 별자리에서
    반대편을 가리킨다(모듈 docstring).
    """
    x = y = z = 0.0
    n = 0
    for s in stars:
        ra = math.radians(s["ra_deg"])
        dec = math.radians(s["dec_deg"])
        x += math.cos(dec) * math.cos(ra)
        y += math.cos(dec) * math.sin(ra)
        z += math.sin(dec)
        n += 1
    if n == 0 or (x == 0.0 and y == 0.0 and z == 0.0):
        return None
    ra_deg = math.degrees(math.atan2(y, x)) % 360.0
    dec_deg = math.degrees(math.atan2(z, math.hypot(x, y)))
    return (ra_deg / 15.0, dec_deg)


def _prepare() -> list[dict]:
    """별자리마다 방향과 밝기 목록을 미리 계산해 둔다(성표 조회는 시각마다 한다)."""
    out: list[dict] = []
    for c in _DOC["constellations"]:
        stars = [s for s in c["stars"] if s.get("vmag") is not None]
        direction = _direction(c["stars"])
        if direction is None:
            continue  # 좌표를 하나도 못 받은 별자리는 방향을 말할 수 없다
        mags = sorted(s["vmag"] for s in stars)
        out.append({
            "abbr": c["abbr"],
            "latin": c["latin"],
            "english": c["english"],
            "korean": c.get("korean") or c["latin"],
            "ra_hours": direction[0],
            "dec_deg": direction[1],
            "mags": mags,
            # 경계 안 잔별의 등급(오름차순). 선 별과 **섞지 않는다** — 선 별은 모양과
            # 방향을, 이쪽은 그 구역 하늘이 얼마나 촘촘한지를 담는다.
            "sky_mags": c.get("sky_mags") or [],
        })
    return out


_PREPARED = _prepare()

#: 미리 만들어 둔 skyfield 별 묶음. 88개를 **한 번에** 계산한다 — 하나씩 부르면
#: 관측 한 번에 88번의 성표 조회가 일어난다.
_STARS = Star(
    ra_hours=[c["ra_hours"] for c in _PREPARED],
    dec_degrees=[c["dec_deg"] for c in _PREPARED],
)

_EARTH = EPH["earth"]


# --- 반환 타입 ----------------------------------------------------------------

@dataclass(frozen=True)
class Constellation:
    """한 시각·한 지점에서 본 별자리 하나.

    abbr/latin/english: IAU 세 글자 약자와 이름.
    korean:        한국어 이름("오리온자리"). 응답에는 이것을 쓴다.
    altitude_deg:  지평 위 고도(도). 음수면 떠 있지 않다.
    azimuth_deg:   방위각(도, 북=0 시계방향).
    bearing:       방위를 사람 말로(8방위).
    visible_stars: 선 별 중 이 하늘에서 잡히는 수 — **알아보느냐**를 가른다.
    total_stars:   별자리를 이루는 선 별 수(등급을 아는 것만).
    brightest:     가장 밝은 별의 등급. 없으면 None.
    horizon_deg:   그 방위의 지형 지평선(도). 안 받았으면 None.
    sky_stars:     경계 안 성표 별 수(Vmag <= 6.5) — **얼마나 촘촘하냐**의 분모.
    visible_sky:   그중 이 하늘에서 잡히는 수. 달이 밝으면 여기가 먼저 줄어든다.
    visible_sky_dark: 달빛이 없었다면 잡혔을 수. 견줄 하늘을 안 받았으면 None.

    두 쌍을 나눠 두는 이유 — 보름달에도 백조자리 십자는 보인다(선 별이 다 3등급보다
    밝다). 사라지는 것은 그 사이의 잔별이다. 한 쌍으로 뭉치면 "백조자리가 안 보인다"는
    틀린 말을 하게 되고, 잔별을 안 세면 "달이 떠도 똑같다"는 틀린 말을 하게 된다.
    """

    abbr: str
    latin: str
    english: str
    korean: str
    altitude_deg: float
    azimuth_deg: float
    bearing: str
    visible_stars: int
    total_stars: int
    brightest: float | None
    horizon_deg: float | None = None
    sky_stars: int = 0
    visible_sky: int = 0
    visible_sky_dark: int | None = None
    visible_stars_dark: int | None = None

    @property
    def dimmed(self) -> bool:
        """달빛에 잔별이 깎였는가 — 견줄 하늘을 받았을 때만 답한다."""
        return (
            self.visible_sky_dark is not None
            and self.visible_sky < self.visible_sky_dark
        )

    @property
    def hidden(self) -> bool:
        """지형에 가려 못 보는가 — 그것만 아니면 알아봤을 것."""
        return self.blocked and self.visible_stars >= _MIN_LINE_STARS

    @property
    def lost(self) -> bool:
        """달이 없었다면 알아봤을 텐데 오늘은 못 알아보는가.

        선 별 기준이다(`naked_eye` 와 같은 잣대). 잔별이 줄어드는 것은 `dimmed` 이고,
        이쪽은 **별자리 자체가 넘어가는** 경계다 — 둘은 다른 말이라 따로 센다.
        """
        return (
            self.visible_stars_dark is not None
            and self.up
            and not self.blocked
            and self.visible_stars_dark >= _MIN_LINE_STARS
            and self.visible_stars < _MIN_LINE_STARS
        )

    @property
    def blocked(self) -> bool:
        """지평 위에 있지만 **지형에 가려** 안 보이는가.

        지평선을 안 받았으면 모르는 것이므로 False 다 — 모르는 것을 막혔다고
        하면 볼 수 있는 별자리를 지워 버린다.
        """
        return (
            self.horizon_deg is not None
            and self.altitude_deg > HORIZON_DEG
            and self.altitude_deg < self.horizon_deg
        )

    @property
    def up(self) -> bool:
        """지평 위에 있는가."""
        return self.altitude_deg > HORIZON_DEG

    @property
    def low(self) -> bool:
        """떠 있지만 낮은가 — 지형에 가릴 수 있는 높이."""
        return self.up and self.altitude_deg < HIGH_ALT_DEG

    @property
    def naked_eye(self) -> bool:
        """이 하늘에서 별자리라고 알아볼 만한가.

        가장 밝은 별 하나만 걸리는 것으로는 '별자리가 보인다'고 하지 않는다 —
        선을 이으려면 별이 둘 이상 필요하다. 지형에 가린 것도 빠진다.
        """
        return (
            self.up and not self.blocked and self.visible_stars >= _MIN_LINE_STARS
        )


# --- 보조 --------------------------------------------------------------------

def bearing_ko(azimuth_deg: float) -> str:
    """방위각(도) → 8방위. 북이 0도이고 시계방향으로 잰다."""
    return _BEARINGS[int((azimuth_deg % 360.0 + 22.5) % 360.0 // 45)]


def nelm_of(bortle: int | None) -> float:
    """Bortle 등급 → 맨눈 한계등급. 모르면 교외 하늘(Bortle 5)로 본다."""
    if bortle is None:
        return NELM_FALLBACK
    return NELM_BY_BORTLE.get(int(bortle), NELM_FALLBACK)


# --- 성표 조회 ----------------------------------------------------------------

def assess(
    lat: float,
    lon: float,
    when: datetime,
    bortle: int | None = None,
    horizon: dict[str, float] | None = None,
    bortle_dark: int | None = None,
) -> list[Constellation]:
    """(lat, lon, when) 에서 본 별자리 전부. 고도 높은 순으로 돌려준다.

    Args:
        lat, lon: 관측지 좌표.
        when: 관측 시각(tz-aware).
        bortle: 그 하늘의 Bortle 등급. 달빛까지 반영하려면 `darkness.assess_sky` 의
                값을 넘긴다 — 그러면 달이 뜬 시각에 보이는 별자리가 저절로 줄어든다.
        horizon: 방위별 지형 지평선(`horizon.profile`). 넘기면 그보다 낮은 별자리가
                `blocked` 가 된다. 안 넘기면 지형을 모르는 것으로 둔다.
        bortle_dark: **달빛을 뺀** 그 자리의 등급(`darkness.assess_site`). 넘기면
                같은 별자리를 두 하늘에서 세어 `visible_sky_dark` 를 채운다 — 달이
                무엇을 지웠는지 말하려면 지우기 전 값이 있어야 한다. 성표 조회는
                한 번뿐이라(방향은 하늘밝기와 무관) 값이 두 배로 드는 일은 없다.

    Returns:
        88개(데이터가 있는 것) 전부. 지평 아래인 것도 담아 돌려준다 — 거르는 기준은
        부르는 쪽이 정한다(`up`·`naked_eye` 속성).
    """
    when = require_aware(when)
    t = TS.from_datetime(when)
    observer = _EARTH + wgs84.latlon(lat, lon)

    alt, az, _ = observer.at(t).observe(_STARS).apparent().altaz()
    alts = alt.degrees
    azs = az.degrees

    limit = nelm_of(bortle)
    limit_dark = None if bortle_dark is None else nelm_of(bortle_dark)
    out: list[Constellation] = []
    for i, c in enumerate(_PREPARED):
        mags = c["mags"]
        sky_mags = c["sky_mags"]
        bearing = bearing_ko(float(azs[i]))
        out.append(
            Constellation(
                abbr=c["abbr"],
                latin=c["latin"],
                english=c["english"],
                korean=c["korean"],
                altitude_deg=round(float(alts[i]), 1),
                azimuth_deg=round(float(azs[i]), 1),
                bearing=bearing,
                visible_stars=sum(1 for m in mags if m <= limit),
                total_stars=len(mags),
                brightest=mags[0] if mags else None,
                horizon_deg=None if horizon is None else horizon.get(bearing),
                sky_stars=len(sky_mags),
                visible_sky=sum(1 for m in sky_mags if m <= limit),
                visible_sky_dark=(
                    None if limit_dark is None
                    else sum(1 for m in sky_mags if m <= limit_dark)
                ),
                visible_stars_dark=(
                    None if limit_dark is None
                    else sum(1 for m in mags if m <= limit_dark)
                ),
            )
        )
    out.sort(key=lambda c: c.altitude_deg, reverse=True)
    return out


# --- 서술 --------------------------------------------------------------------

def highlights(got: list[Constellation]) -> list[Constellation]:
    """지금 눈에 먼저 들어올 별자리들. 1등성으로 **거르고**, 고도로 **정렬**한다.

    두 축의 역할이 다르다. 밝기는 *왜 이것들인가*를 정하고(개수로 자르면 근거가
    없다 — `FIRST_MAGNITUDE` 주석), 고도는 *무엇부터 보이나*를 정한다. 밝기순으로
    늘어놓으면 지평선 3도에 걸린 전갈자리가 천정 79도의 백조자리보다 앞에 온다 —
    실제로 고개를 들면 백조자리가 먼저 보인다.
    """
    picked = [
        c for c in got
        if c.naked_eye and c.brightest is not None and c.brightest <= FIRST_MAGNITUDE
    ]
    picked.sort(key=lambda c: c.altitude_deg, reverse=True)
    return picked


def describe(
    got: list[Constellation], *, brief: bool = False, explain_fist: bool = True
) -> list[str]:
    """별자리를 **보이느냐 마느냐**로 끊어 말한다. 볼 것이 없으면 빈 목록.

    **판정하지 않는다.** 어느 별자리가 어느 쪽에 있고 보이느냐는 사실만 말한다 —
    등급은 `judge` 소관이고, 이 축은 등급을 바꾸지 않는다(`weather` 와 같은 자리).

    한 줄이 한 가지 답을 한다.

        볼 수 있어요            고도 30도 위 — 서서 고개만 들면 된다
        낮아서 놓치기 쉬워요     떠 있지만 낮다 — 그쪽이 트여야 보인다
        안 보여요               달빛에 묻혔거나 지형에 가렸다(괄호에 이유)

    센 수(`visible_sky` 등)는 문장에 넣지 않는다. "달이 없으면 2,443개인데 오늘은
    725개" 는 사실이지만, 갈지 말지를 정하는 사람이 읽을 말은 아니다 — 수치는
    `numbers` 에 그대로 실어 호출자가 쓰게 둔다.

    Args:
        brief: 판정이 '불가'인 밤이면 True. 한 줄만 낸다.
        explain_fist: '주먹'이 몇 도인지 여기서 알려 줄지. 지평선 축과 나눠 쓴다.
    """
    top = highlights(got)

    # 사용자가 정해야 하는 것은 **어느 쪽을 보고 서나**이므로 방위를 괄호에 남긴다.
    # 고도는 `numbers` 에 있다 — 문장에 숫자를 다섯 번 넣을 이유가 없다.
    def _names(cs: list[Constellation]) -> str:
        return "·".join(f"{c.korean}({c.bearing})" for c in cs)

    if not top:
        return []

    up = [c for c in top if not c.low]
    low = [c for c in top if c.low]

    # 비·구름으로 '불가'인 밤에는 "어느 쪽을 보고 서세요"가 쓸모없는 안내다 — 그 밤에
    # 사용자가 정할 것은 방향이 아니라 갈지 말지다. 그렇다고 통째로 지우면 "오늘은
    # 어떤 하늘이냐"에 답하지 못하므로, 한 줄로 줄여 남긴다.
    if brief:
        return [f"하늘이 열린다면 {_names((up or low)[:3])}를 볼 수 있는 밤이에요"]

    lines: list[str] = []
    if up:
        lines.append(f"볼 수 있어요 — {_names(up)}")

    if low:
        # 낮게 뜬 것만 높이를 붙인다 — 여기서는 높이가 곧 '보이느냐'라서다.
        names = "·".join(
            f"{c.korean}({c.bearing}·{hand_span(c.altitude_deg)})" for c in low
        )
        note = FIST_NOTE_TAIL if explain_fist else ""
        lines.append(f"낮아서 놓치기 쉬워요 — {names}{note}")

    # 못 보는 것은 **이유를 괄호에** 단다. 달빛은 날짜를 바꾸면 되고 지형은 자리를
    # 옮겨야 하니, 사용자가 할 수 있는 일이 다르다.
    #
    # 지형에 가린 것은 **원래 짚어 줬을 것**만 말한다. 지평선 언저리에는 늘 무언가
    # 걸쳐 있어서 다 세면 조각가자리·망원경자리 같은 이름이 예닐곱 개씩 나오는데,
    # 그것들은 지형이 없어도 안내에 안 나왔을 별자리다 — 없던 아쉬움을 만든다.
    # 달빛에 묻힌 것은 밝기와 무관하게 다 말한다. 날짜를 바꾸면 볼 수 있어서다.
    gone = [(c, "달빛") for c in got if c.lost]
    gone += [
        (c, "지형") for c in got
        if c.hidden and c.brightest is not None and c.brightest <= FIRST_MAGNITUDE
    ]
    if gone:
        # 밝은 것부터 — 이름을 알아볼 만한 것이 앞에 와야 잘린 뒤가 아쉽지 않다.
        gone.sort(key=lambda p: p[0].brightest if p[0].brightest is not None else 99)
        shown = "·".join(f"{c.korean}({why})" for c, why in gone[:3])
        more = f" 외 {len(gone) - 3}개" if len(gone) > 3 else ""
        lines.append(f"안 보여요 — {shown}{more}")

    return lines
