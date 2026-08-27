"""경로 지도 HTML 만들기 — 문자열을 돌려주는 순수 함수 (파일도 네트워크도 없다).

좌표를 말로 설명하지 않는다(`plan.md` P13). "차로 29분" 다음에 사람이 실제로 묻는
것은 "어느 길로, 어디에 세우고, 거기서 얼마나 걷나"이고, 그건 선으로 보여야 한다.

무엇을 그리나 — **도착한 다음**만 그린다
--------------------------------------------------------------------------
    도보 경로   주차 지점 → 관측 지점. `jeju_spots.json` 의 `walk_routes[].segments`
    마커        관측지 · 주차장 · 화장실

**주행 경로는 그리지 않는다.** 제주를 가로지르는 선이 들어오면 지도가 섬 전체로
줌아웃되고, 그러면 정작 봐야 할 것 — 어디에 세우고 어디로 걷고 어디가 계단인지 —
가 점으로 뭉개진다. 주행시간은 도구 응답의 숫자와 문장으로 답하면 되고, 지도는
**도착한 다음**을 맡는다.

파일 쓰기와 URL 은 여기 없다
--------------------------------------------------------------------------
`core` 는 I/O 를 하지 않으므로 이 모듈은 HTML **문자열**까지만 만든다. 그것을 어디에
저장하고 어떤 주소로 내보낼지는 `server/maps.py` 소관이다.

배경은 위성사진이 기본이다
--------------------------------------------------------------------------
주차 자리가 포장인지 흙바닥인지, 탐방로가 어디로 나 있는지는 **선 지도로는 안 보인다**.
그래서 위성사진을 기본 배경으로 깔고 일반 지도를 토글로 둔다.

**어느 위성을 쓸지는 이 모듈이 정하지 않는다.** 키가 필요한 공급자가 있어(VWorld)
환경을 읽어야 하는데 `core` 는 그런 일을 하지 않는다. `server/maps.py` 가 골라
`satellite` 인자로 넘긴다.

실사진이 있는 최대 줌은 공급자마다 다르다(`Tiles.max_native_zoom`). 그보다 더 당기면
마지막 타일을 늘려 보여준다 — 없는 줌을 그대로 요청하면 화면이 회색으로 비어 버린다.

키가 죽으면 **화면에서 갈아탄다**(`fallback`). 키가 필요한 공급자는 언젠가 막히고,
그때 배경만 통째로 사라진 지도는 이유를 아무 데도 안 적어 준다. 서버가 미리 확인할
수도 없다 — 타일은 지도를 여는 사람의 브라우저가 직접 받아 가기 때문이다.

타일과 Leaflet 만 인터넷에서 받는다. 나머지 데이터는 전부 파일 안에 들어 있어서,
지도를 띄우는 데 이 서버가 살아 있을 필요가 없다.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass

#: 마커 갈래 → (색, 표시 문자, 사람이 읽는 이름). 갈래를 색으로만 나누면 색맹·흑백
#: 출력에서 구분이 사라지므로 문자를 함께 찍는다.
_KINDS: dict[str, tuple[str, str, str]] = {
    "spot": ("#f59e0b", "★", "관측 지점"),
    "origin": ("#3b82f6", "출", "출발지"),
    "parking": ("#22c55e", "P", "주차"),
    "toilet": ("#a855f7", "화", "화장실"),
}
_FALLBACK = ("#94a3b8", "·", "지점")

#: 도보 구간 갈래 → 색. "20분 걷는다"까지만 보이면 **어디서 계단이 시작되는지**를
#: 모른다. 밤에 초행으로 오르는 사람에게는 그게 준비를 가르는 정보다.
#: 밟기 힘든 순으로 색이 진해진다 — 포장길(하늘) → 흙(주황) → 돌(황토) → 암반(갈색)
#: → 계단(빨강). 모르는 구간은 회색으로, 쉬운 쪽으로 오해되지 않게 둔다.
_WALK_COLORS: dict[str, str] = {
    "포장길": "#38bdf8",
    "흙길": "#f59e0b",
    "돌길": "#a16207",
    "암반": "#b45309",
    "계단": "#ef4444",
    "모름": "#94a3b8",
}
_WALK_FALLBACK = "#94a3b8"



#: 조각의 결 → (바탕색, 글자색). 조각이 전부 같은 회색이면 줄이 길어질수록 눈이
#: 미끄러져 아무것도 안 읽힌다. 축마다 색을 줘 **훑어서 견주게** 한다.
#:   drive 차로 가는 시간 · walk 걷는 시간·거리 · hard 각오해야 하는 것(계단·어려움)
#:   warn 확인되지 않은 것(난이도 미상·주차 미확인) · plain 나머지
_TONES: dict[str, tuple[str, str]] = {
    "drive": ("#dbeafe", "#1d4ed8"),
    "walk": ("#ffedd5", "#9a3412"),
    "hard": ("#fee2e2", "#b91c1c"),
    "warn": ("#fef9c3", "#854d0e"),
    "plain": ("#eef2f7", "#334155"),
}


@dataclass(frozen=True)
class Tiles:
    """배경 타일 한 겹 — 주소·귀속·실사진 최대 줌.

    `max_native_zoom` 은 **실제 사진이 있는 가장 큰 줌**이다. 그보다 더 당기면
    Leaflet 이 마지막 타일을 늘려 보여준다. 없는 줌을 그대로 요청하면 공급자가
    빈 타일이나 오류를 주고, 화면은 회색으로 빈다.
    """

    url: str
    attribution: str
    max_native_zoom: int = 18
    max_zoom: int = 21


#: 키가 없을 때 쓰는 위성 배경. 전 세계를 덮고 키가 필요 없지만, 제주는 대부분
#: z18 까지다(z19 를 요청하면 네 장이 바이트까지 같은 '자료 없음' 타일이 온다).
DEFAULT_SATELLITE = Tiles(
    url=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
    attribution="위성사진 &copy; Esri · Maxar · Earthstar Geographics",
    max_native_zoom=18,
)


@dataclass(frozen=True)
class Fact:
    """목록 한 줄의 조각 하나 — 짧은 말과 그 결."""

    text: str
    tone: str = "plain"


@dataclass(frozen=True)
class Item:
    """목록 박스의 한 줄 — 어느 점이 무엇인지, 무엇을 각오해야 하는지.

    여러 곳을 한 장에 그리면 마커만으로는 어디가 어디인지 모른다. 팝업은 하나씩
    눌러야 보이므로 **한눈에 견주지 못한다** — "어디가 더 가깝고 덜 힘든가"가
    고르는 기준인데 그게 안 보인다. 그래서 옆에 표로 편다.

    facts 는 짧은 조각들이다(예: "차 24분", "도보 31분", "계단 261m", "난이도 어려움").
    문장으로 이으면 줄이 길어져 견주기가 다시 어려워진다.
    """

    label: str
    lat: float
    lon: float
    #: 이름 아래 회색 한 줄(지역·유형 등).
    sub: str = ""
    #: 한눈에 견줄 짧은 조각들.
    facts: tuple[Fact, ...] = ()


@dataclass(frozen=True)
class Marker:
    """지도에 찍는 점 하나."""

    lat: float
    lon: float
    kind: str
    name: str
    #: 팝업 둘째 줄(거리·요금·개방시간 등). 없으면 이름만 뜬다.
    note: str = ""
    #: 점 위에 찍을 글자. 비우면 갈래의 기본 문자(★·P·화)를 쓴다.
    #: 여러 곳을 한 장에 그릴 때 **목록의 번호**를 여기 넣는다 — 전부 같은 ★ 이면
    #: 지도만 보고는 어느 점이 목록 몇 번인지 알 수 없다.
    glyph: str = ""


@dataclass(frozen=True)
class Icon:
    """마커에 얹는 그림 하나.

    `url` 은 `data:` 로 시작하는 **박아 넣은 그림**이다. 서버 주소를 쓰지 않는 이유는
    지도 한 장이 이 서버 없이도 열려야 하기 때문이다 — 내보낸 지도는 오래 살아남고,
    그때 이 서버가 떠 있으리라는 보장이 없다(`maps.py` 가 굽는다).

    `anchor` 는 그림의 어느 점이 **그 좌표인가**를 가로세로 비율로 적은 것이다.
    한가운데면 (0.5, 0.5). 물방울 모양 표지는 뾰족한 끝이 좌표이므로 아래쪽이고,
    가운데를 자리로 잡으면 주차 지점을 그림 절반만큼 위로 옮겨 알려 주는 셈이 된다.

    비율인 이유는 그림마다 끝이 다른 데다 여백·테두리를 두면 또 달라지기 때문이다.
    짐작하지 않고 `scripts/build_icons.py` 가 알파에서 재어 `anchor.json` 에 적는다.
    """

    url: str
    anchor: tuple[float, float] = (0.5, 0.5)


@dataclass(frozen=True)
class Walk:
    """도보 경로의 한 조각 — 어디를 무엇을 밟고 걷는가.

    조각은 원래 **한 줄이던 길**을 노면별로 자른 것이다. 색은 조각마다 달라야 하지만
    (계단이 어디서 시작되는지가 그 색에 있다), 진행 방향 화살표는 자른 자리를 무시하고
    길 전체에 고르게 얹혀야 한다. `route` 가 그 '원래 한 줄'을 되찾는 열쇠다.

    `route` 는 **한 장의 지도 안에서** 유일해야 한다. 여러 관측지를 한 장에 그릴 때
    각자의 0번 경로가 같은 값으로 들어오면, 서로 상관없는 두 길이 한 줄로 이어져
    엉뚱한 자리에 화살표가 생긴다. 번호를 겹치지 않게 매기는 것은 부르는 쪽 몫이다.
    """

    points: tuple[tuple[float, float], ...]
    kind: str
    #: 조각을 눌렀을 때 뜨는 한 줄.
    note: str = ""
    #: 이 조각이 원래 속했던 길.
    route: int = 0
    #: 그 자리에 있는 것의 짧은 이름("벤치"·"평상"). 있으면 지도에 라벨로 찍는다.
    landmark: str = ""


def _points(path: list[tuple[float, float]] | None) -> list[list[float]]:
    return [[lat, lon] for lat, lon in (path or [])]


def _tiles(t: Tiles) -> dict[str, object]:
    """배경 한 겹을 화면이 읽는 모양으로."""
    return {
        "url": t.url,
        "credit": t.attribution,
        "maxNative": t.max_native_zoom,
        "maxZoom": t.max_zoom,
    }


def render(
    title: str,
    markers: list[Marker],
    satellite: Tiles | None = None,
    fallback: Tiles | None = None,
    overlay: Tiles | None = None,
    walk_segments: list[Walk] | None = None,
    items: list[Item] | None = None,
    icons: dict[str, Icon] | None = None,
) -> str:
    """지도 HTML 한 장. 열기만 하면 되는 자립형 문서다.

    Args:
        title: 문서 제목이자 화면 왼쪽 위 제목.
        markers: 찍을 점들. 하나도 없으면 지도를 만들지 않는다(빈 문자열).
        satellite: 위성 배경. 생략하면 키가 필요 없는 기본 공급자를 쓴다.
        fallback: 위 배경이 타일을 못 줄 때 갈아탈 배경. 키가 필요한 공급자를 쓸 때만
            의미가 있다 — 만료·미등록으로 막히면 화면에 바탕색만 남기 때문이다.
        overlay: 위성 위에 얹는 **투명한** 도로·지명 겹. 위성사진만으로는 길 이름도
            마을 이름도 안 보여서 "여기가 어디쯤인가"를 못 잡는다. 없으면 안 얹는다.
        walk_segments: 도보 조각들(`Walk`). 갈래는 `계단`·`돌길`·`흙길`·`포장` 처럼
            무엇을 밟는가이며 색이 거기서 갈린다. 같은 `route` 를 단 조각들은 원래
            한 줄이던 길로 다시 이어져 그 위에 진행 방향 화살표가 얹힌다.
        items: 패널에 펼 목록. 여러 곳을 그릴 때 어디가 어디인지와 각 곳의 난이도·
            계단·도보를 한눈에 견주게 한다.
        icons: 마커 갈래 → 그 갈래에 얹을 그림. 그림이 없는 갈래는 색 동그라미와
            글자로 그린다(출발지가 그렇다) — 있는 것만 갈아 끼우면 되게 두었다.

    Returns:
        완결된 HTML 문자열. 마커가 하나도 없으면 빈 문자열 — 그릴 것이 없는데
        빈 지도를 내보내면 "지도가 있다"는 잘못된 신호가 된다.
    """
    if not markers:
        return ""

    sat = satellite or DEFAULT_SATELLITE
    data = {
        "sat": _tiles(sat),
        "fallback": _tiles(fallback) if fallback else None,
        "overlay": _tiles(overlay) if overlay else None,
        "markers": [
            {
                "lat": m.lat,
                "lon": m.lon,
                "kind": m.kind,
                "color": _KINDS.get(m.kind, _FALLBACK)[0],
                "glyph": m.glyph or _KINDS.get(m.kind, _FALLBACK)[1],
                "kindLabel": _KINDS.get(m.kind, _FALLBACK)[2],
                "name": m.name,
                "note": m.note,
                # 그림 자체는 마커마다 싣지 않는다. base64 로 6~10KB 씩이라, 같은
                # 갈래가 여럿이면 같은 그림이 그만큼 복사된다 — 세 곳을 그린 지도가
                # 137KB 였다. 갈래별로 한 번만 싣고(`D.icons`) 화면이 찾아 쓴다.
                #
                # 갈래의 기본 글자와 다르면 사람이 따로 넣은 것이다 — 목록 번호가
                # 그렇다. 그림 위에 작은 배지로 얹어야 "지도의 이 별이 목록 몇 번인가"
                # 가 남는다. 그림으로 갈아 끼우면서 이것을 잃으면 안 된다.
                "badge": m.glyph if (icons or {}).get(m.kind)
                         and m.glyph
                         and m.glyph != _KINDS.get(m.kind, _FALLBACK)[1] else "",
            }
            for m in markers
        ],
        "walks": [
            {
                "points": _points(list(w.points)),
                "kind": w.kind,
                "note": w.note,
                "route": w.route,
                "landmark": w.landmark,
                "color": _WALK_COLORS.get(w.kind, _WALK_FALLBACK),
            }
            for w in (walk_segments or [])
            if len(w.points or ()) > 1
        ],
        # 마커 갈래 → 그림. 여기 **한 번만** 싣는다. 그리고 실제로 찍은 갈래만
        # 싣는다 — 화장실이 없는 지도가 화장실 그림을 10KB 지고 다닐 이유가 없다.
        "icons": {
            kind: {"url": art.url, "at": list(art.anchor)}
            for kind, art in (icons or {}).items()
            if any(m.kind == kind for m in markers)
        },
        "items": [
            {
                "label": it.label,
                "lat": it.lat,
                "lon": it.lon,
                "sub": it.sub,
                "facts": [
                    {
                        "text": f.text,
                        "bg": _TONES.get(f.tone, _TONES["plain"])[0],
                        "fg": _TONES.get(f.tone, _TONES["plain"])[1],
                    }
                    for f in it.facts
                ],
            }
            for it in (items or [])
        ],
    }

    # 범례는 실제로 그린 것만 싣는다. 없는 것을 범례에만 두면 "왜 안 보이지"가 된다.
    legend = []
    # 도보는 갈래마다 한 칸씩. 실제로 그린 갈래만, 밟기 힘든 순으로 싣는다.
    drawn = {w["kind"] for w in data["walks"]}
    for kind in _WALK_COLORS:
        if kind in drawn:
            color = _WALK_COLORS[kind]
            legend.append(f'<i class="ln" style="--c:{color}"></i>{kind}')
    for kind in ("spot", "parking", "toilet", "origin"):
        if not any(m.kind == kind for m in markers):
            continue
        color, glyph, label = _KINDS[kind]
        if (icons or {}).get(kind):
            # 주소를 여기 적지 않고 갈래만 적는다. 그림 하나가 base64 로 6~10KB 라,
            # 여기 한 번 더 박으면 지도 파일이 그만큼 통째로 무거워진다 —
            # 화면이 `D.icons` 에서 찾아 끼운다.
            legend.append(f'<img class="ic" data-kind="{kind}" alt="">{label}')
        else:
            legend.append(f'<i class="pin" style="--c:{color}">{glyph}</i>{label}')

    return _TEMPLATE.format(
        title=html.escape(title),
        legend="".join(f"<span>{item}</span>" for item in legend),
        data=json.dumps(data, ensure_ascii=False),
    )


_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  :root {{ --ink:#0f172a; --ink-2:#64748b; --bg:#f8fafc; --card:#ffffff; }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin:0; height:100%;
    font-family: system-ui, -apple-system, "Malgun Gothic", sans-serif;
  }}
  /* 타일이 아직 안 온 자리의 바탕. 흰색이면 어두운 위성사진 사이로 흰 조각이
     번쩍여 화면이 깨져 보인다 — 사진과 비슷한 어둠으로 깔아 눈에 안 띄게 한다. */
  #map {{ position:absolute; inset:0; background:#0f1729; }}
  .legend {{
    display:flex; flex-wrap:wrap; gap:5px 10px;
    font-size:11px; color:var(--ink-2);
    padding:9px 9px 3px; border-top:1px solid #e2e8f0; margin-top:4px;
  }}
  .legend span {{ display:inline-flex; align-items:center; gap:5px; }}
  .pin {{
    width:16px; height:16px; border-radius:50%; background:var(--c); color:#fff;
    font-size:9px; font-weight:700; display:inline-flex; align-items:center;
    justify-content:center; font-style:normal;
  }}
  .ln {{ width:18px; height:0; border-top:4px solid var(--c); display:inline-block; }}
  /* 범례의 그림은 지도의 마커와 **같은 그림**이어야 한다. 범례에만 다른 모양을 두면
     그것은 범례가 아니라 또 하나의 수수께끼다. */
  .ic {{ width:18px; height:18px; object-fit:contain; display:inline-block; }}
  /* 그림 마커. 위성사진 위에서 밝은 그림은 밝은 자리에, 어두운 그림은 어두운 자리에
     묻힌다 — 그림 자신의 모양을 따라가는 그림자를 깔아 어느 배경에서도 떼어 놓는다.
     사각 상자를 두르지 않는 이유는 별·물방울의 윤곽이 곧 그 아이콘이기 때문이다. */
  .mk.art img {{
    display:block;
    /* 흰 테두리는 그림 파일에 구워져 있다(`scripts/build_icons.py`). 여기서 흰
       광채를 또 얹으면 흰색이 두 겹이 되어 알맹이가 허옇게 뜬다 — 그림자만 준다. */
    filter: drop-shadow(0 1px 2px rgba(11,16,32,.5));
  }}
  /* 목록 번호 배지. 그림 오른쪽 위 모서리에 앉힌다 — 가운데에 겹치면 그림이 무엇인지
     안 보이고, 번호도 그림 무늬에 섞여 안 읽힌다. */
  .mk.art u {{
    position:absolute; right:-5px; top:-5px; min-width:15px; height:15px;
    padding:0 3px; border-radius:8px; background:#0f172a; color:#fff;
    font:700 10px/15px system-ui, "Malgun Gothic", sans-serif;
    text-align:center; text-decoration:none; box-shadow:0 0 0 1.5px #fff;
  }}
  /* 길 위에 있는 것의 라벨(벤치·평상·사슴동상). 점은 자리를, 낱말은 무엇인지를 맡는다.
     낱말을 점 위에 겹쳐 놓으면 정작 어디인지가 가려지므로 옆으로 뺀다.
     자리는 Leaflet 이 바깥 요소의 transform 으로 잡으므로 안쪽은 절대위치로 매단다. */
  .lmk i {{
    position:absolute; left:-4.5px; top:-4.5px; width:9px; height:9px;
    border-radius:50%; background:#0f172a; box-shadow:0 0 0 2.5px #fff;
  }}
  .lmk b {{
    position:absolute; left:9px; top:-10px; white-space:nowrap;
    font:650 11px/1 system-ui, "Malgun Gothic", sans-serif; color:#fff;
    background:rgba(11,16,32,.82); border:1px solid rgba(255,255,255,.34);
    border-radius:4px; padding:3px 6px; box-shadow:0 1px 4px rgba(11,16,32,.45);
  }}
  /* 닫기 버튼이 절대위치라 제목 위에 올라탄다. 오른쪽을 비워 자리를 내준다. */
  .leaflet-popup-content {{
    margin:10px 12px; padding-right:16px; font-size:12px; line-height:1.6;
  }}
  .leaflet-popup-close-button {{ padding:6px 6px 0 0 !important; }}
  .leaflet-popup-content b {{ display:block; font-size:13px; margin-bottom:2px; }}
  .leaflet-popup-content .k {{ color:#64748b; font-size:11px; }}
  /* 패널 하나에 제목·목록·범례를 담는다. 둘로 나누면 화면 양쪽을 다 가린다.
     좁은 화면에서는 지도 아래로 내린다. */
  .panel {{
    position:absolute; z-index:1000; top:12px; right:12px; width:300px;
    max-height:calc(100% - 24px); overflow-y:auto;
    background:var(--card); border-radius:10px; padding:4px;
    box-shadow:0 2px 12px rgba(15,23,42,.16); color:var(--ink);
  }}
  .panel h1 {{
    margin:0; padding:9px 9px 8px; font-size:14px; font-weight:650;
    border-bottom:1px solid #e2e8f0;
  }}
  .row {{
    display:block; width:100%; text-align:left; border:0; background:none;
    padding:8px 9px; border-radius:7px; cursor:pointer; font:inherit;
  }}
  .row:hover {{ background:#f1f5f9; }}
  .row + .row {{ border-top:1px solid #e2e8f0; }}
  .row .nm {{ font-size:13px; font-weight:650; }}
  .row .sb {{ font-size:11px; color:var(--ink-2); margin-top:1px; }}
  .row .fx {{ display:flex; flex-wrap:wrap; gap:3px 5px; margin-top:5px; }}
  .row .fx b {{
    font-weight:650; font-size:10.5px; border-radius:4px; padding:2px 6px;
    white-space:nowrap;
  }}
  @media (max-width: 640px) {{
    .panel {{
      position:static; width:auto; max-height:42%; margin:0;
      border-radius:0; box-shadow:none; border-top:1px solid #e2e8f0;
    }}
    #map {{ position:absolute; inset:0 0 42% 0; }}
    body {{ display:flex; flex-direction:column; }}
  }}
  /* 편의시설 마커는 어느 줌에서 켜지고 꺼진다. 그냥 나타나면 줌이 끝나는 순간
     점이 툭 튀어 화면이 흔들린 것처럼 보인다 — 짧게 떠오르게 한다.
     자리는 Leaflet 이 **바깥** 요소의 transform 으로 잡으므로 안쪽 div 만 움직인다. */
  .mk > div, .mk.art img, .lmk i, .lmk b {{ animation: mk-in .22s ease-out; }}
  @keyframes mk-in {{
    from {{ opacity:0; transform:scale(.72); }}
    to   {{ opacity:1; transform:none; }}
  }}
  /* 위성 배경 위에서는 글자·컨트롤이 묻히므로 바탕을 확실히 준다. */
  .leaflet-control-layers {{ font-size:12px; }}
  .leaflet-control-attribution {{ font-size:10px; }}
</style>
</head>
<body>
<!-- 진행 방향 화살촉. 선 안쪽에 반복해 찍혀 "어느 쪽으로 걷는 길인가"를 말한다.
     `url(#arw)` 는 문서 전체에서 찾으므로 지도 밖에 정의해도 걸린다 — Leaflet 이
     자기 <svg> 를 언제 만들고 지우는지에 기대지 않으려고 여기 둔다.
     `userSpaceOnUse` 라 선 굵기와 무관하게 늘 8px 상자다. 그 안에서 화살촉의 바깥
     지름은 5.5px — 선(9px)보다 작아야 한다. 선 테두리가 흰색이라, 화살촉이 선 폭을
     다 채우면 테두리와 이어져 흰 덩어리가 되고 방향이 사라진다. -->
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
  <marker id="arw" viewBox="0 0 10 10" refX="5" refY="5"
          markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse"
          orient="auto">
    <path d="M2.4 2.4 L7.0 5 L2.4 7.6" fill="none" stroke="#ffffff"
          stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
  </marker>
</defs></svg>
<div id="map"></div>
<div class="panel">
  <h1>{title}</h1>
  <div id="list"></div>
  <div class="legend">{legend}</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D = {data};

// 줌이 뚝뚝 끊기지 않게 하는 값들.
//
// `zoomSnap` 은 1 그대로 둔다 — 반 단계에 멈추면 타일이 1.4배로 늘어나 위성사진이
// 쉬는 동안 내내 흐리다. 부드러움을 얻자고 선명함을 상시로 내주는 거래다.
// 대신 휠 한 단계에 필요한 스크롤 양을 늘려(60→120px) 한 번 굴릴 때 서너 단계가
// 통째로 넘어가는 일을 막는다. 급하게 지나친 줌을 되돌리는 게 바로 그 '깨지는' 느낌이다.
//
// `zoomAnimationThreshold` 를 키우는 것은 목록에서 한 곳을 눌러 z12 → z19 로 일곱
// 단계를 뛸 때다. 기본값(4)을 넘으면 Leaflet 이 애니메이션을 통째로 끄고 화면을
// 순간이동시킨다 — 어디서 어디로 갔는지 이어지지 않아 결국 손으로 다시 줌아웃하게 된다.
const map = L.map('map', {{
  zoomControl: true,
  zoomSnap: 1,
  zoomDelta: 1,
  wheelPxPerZoomLevel: 120,
  wheelDebounceTime: 20,
  zoomAnimationThreshold: 8
}});
// 위성사진 — 기본 배경. 실사진이 있는 줌보다 더 당기면 마지막 타일을 늘린다.
// 실사진이 있는 줌보다 **한 단계까지만** 더 당기게 둔다. 두 단계를 더 가면 픽셀이
// 가로세로 네 배로 늘어나 사진이라기보다 뭉갠 색덩어리가 된다 — 당길수록 잘 보일
// 거라 믿고 굴리다 화질만 잃는다. 한 단계(2배)까지는 아직 형태가 읽힌다.
//
// `keepBuffer` 는 화면 밖 타일을 몇 겹까지 살려 두느냐다. 기본 2로는 줌아웃하는
// 순간 바깥쪽이 빈 채로 나타났다가 채워진다. `updateWhenZooming: false` 는 줌이
// 움직이는 동안 새 타일을 요청하지 않는다는 뜻이고 — 애니메이션 중에 타일이
// 갈아 끼워지지 않으니 화면이 한 장으로 늘어났다 제자리를 찾는다.
const TILE = {{ keepBuffer: 4, updateWhenZooming: false }};
function tiles(t) {{
  return L.tileLayer(t.url, Object.assign({{}}, TILE, {{
    maxZoom: Math.min(t.maxZoom, t.maxNative + 1),
    maxNativeZoom: t.maxNative,
    attribution: t.credit
  }}));
}}
const SAT = tiles(D.sat);

// 선 지도(CARTO) — 두 군데서 쓴다. 아래 깔 바닥과, 사람이 고르는 '일반 지도'.
const PLAIN_URL =
  'https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png';
const PLAIN_CREDIT =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' +
  ' 기여자 · 타일 &copy; <a href="https://carto.com/attributions">CARTO</a>';
function plain(opts) {{
  return L.tileLayer(PLAIN_URL, Object.assign({{}}, TILE, {{
    maxZoom: 20, attribution: PLAIN_CREDIT
  }}, opts || {{}}));
}}

// 바닥 — 위성 **아래** 항상 깔아 두는 선 지도.
//
// 위성 배경(브이월드)은 CDN 이 아니라 단일 호스트 origin 이고 HTTP/1.1 이다. 타일
// 한 장의 TTFB 가 0.8~1.5초인데, 브라우저는 한 호스트에 연결을 여섯 개까지만 연다.
// 한 화면치 서른 장이 여섯 줄로 줄을 서니 배경이 다 차기까지 십수 초가 걸리고,
// 그동안 화면에는 바탕색뿐이다 — **오는 중인데 고장 난 것처럼 보인다.**
//
// 그래서 먼저 오는 것을 먼저 그린다. CARTO 는 CDN 이고 하위도메인이 넷이라 위성과
// 연결을 나눠 쓰지 않는다. 해안선과 길이 먼저 깔리고 위성사진이 그 위로 채워진다.
// 위성이 오는 시간을 줄이지는 못하지만 **비어 있는 시간을 없앤다**. 덤으로, 위성
// 타일이 빠진 자리(제주 밖·자료 없는 줌)도 회색 대신 이 겹이 받는다.
//
// 고르는 목록에는 넣지 않는다. 이건 선택지가 아니라 땅이다.
map.createPane('ground');
map.getPane('ground').style.zIndex = 190;   // tilePane(200) 바로 아래
plain({{ pane:'ground' }}).addTo(map);

// 일반 지도 — 지명·도로 이름을 읽어야 할 때. 위성 위에서는 글자가 잘 안 읽힌다.
const PLAIN = plain();
SAT.addTo(map);

// 도로·지명 — 위성 위에 얹는 투명한 겹. 위성사진만으로는 길 이름도 마을 이름도 안
// 보여서 "여기가 어디쯤인가"를 못 잡는다. 위성으로 보는 것(주차 자리가 포장인지,
// 탐방로가 어디로 났는지)과 선 지도로 보는 것(어느 길로 들어가는지)은 서로 다른
// 물음이라, 둘 중 하나를 고르게 하지 않고 **겹쳐서** 답한다.
//
// '일반 지도'로 바꾸면 내린다 — 그쪽은 이미 길과 이름을 그리고 있어서, 위에 또 얹으면
// 같은 지명이 두 번 찍힌다. 사람이 직접 끈 경우에는 위성으로 돌아와도 켜지 않는다.
const ROADS = D.overlay ? tiles(D.overlay) : null;
let roadsWanted = !!ROADS, roadsSyncing = false;
// 이 겹은 **위성이 다 온 다음에** 얹는다.
//
// 도로·지명은 위성과 같은 공급자·같은 호스트에서 온다. 둘을 함께 켜면 한 호스트에
// 허용된 연결 여섯 개를 서로 나눠 갖고, 정작 먼저 보여야 할 위성사진이 절반 속도로
// 온다 — 예순 장이 한 줄에 서는 셈이다. 위성이 먼저 차고 나서 얹으면 같은 연결을
// 통째로 쓴다.
//
// 그 사이 길과 지명이 비지 않는다. 바닥에 깔아 둔 선 지도가 이미 그리고 있다.
// 위성이 끝내 안 오는 날(키가 막힌 날)에도 겹은 얹혀야 하므로 시간으로도 연다.
if (ROADS) {{
  let roadsOpened = false;
  const openRoads = () => {{
    if (roadsOpened) return;
    roadsOpened = true;
    if (roadsWanted) ROADS.addTo(map);
  }};
  SAT.once('load', openRoads);
  setTimeout(openRoads, 4000);
}}

const LAYERS = L.control.layers(
  {{ '위성사진': SAT, '일반 지도': PLAIN }},
  ROADS ? {{ '도로·지명': ROADS }} : null,
  {{ collapsed: false }}).addTo(map);
L.control.scale({{ imperial:false }}).addTo(map);

// 줌은 **지금 깔린 배경이 갈 수 있는 데까지만** 연다.
//
// Leaflet 의 지도 최대 줌은 깔린 겹들 중 가장 큰 값이다. 바닥에 항상 깔아 둔 선
// 지도가 z20 까지 가므로, 배경이 그보다 낮은 겹으로 바뀌면(Esri 로 갈아탄 뒤 z19)
// 그 사이에 한 단계가 뜬다 — 위성 겹이 통째로 비워지고 아래 깔린 선 지도가 그대로
// 드러난다. **배경을 고른 적이 없는데 배경이 바뀐 것처럼 보인다.**
//
// 그래서 바탕이 바뀔 때마다 그 겹의 최대 줌으로 지도를 다시 묶는다. 더 당기려 하면
// 줌 버튼이 서고, 이미 그 너머에 있으면 Leaflet 이 되돌린다. 못 보던 배경이 뜨느니
// 여기까지라고 말하는 편이 낫다.
const capZoom = layer => map.setMaxZoom(layer.options.maxZoom);
capZoom(SAT);
map.on('baselayerchange', e => capZoom(e.layer));

if (ROADS) {{
  map.on('overlayadd overlayremove', e => {{
    if (e.layer === ROADS && !roadsSyncing) roadsWanted = (e.type === 'overlayadd');
  }});
  map.on('baselayerchange', e => {{
    const want = roadsWanted && e.layer !== PLAIN;
    if (want === map.hasLayer(ROADS)) return;
    roadsSyncing = true;
    if (want) ROADS.addTo(map); else map.removeLayer(ROADS);
    roadsSyncing = false;
  }});
  // 도로 겹도 키가 필요한 공급자에서 온다. 키가 막히면 위성과 같이 죽는데, 이쪽은
  // 투명한 겹이라 죽어도 화면에 아무 표시가 없다 — 조용히 내려서 오류 타일을
  // 계속 받아 오지 않게 한다.
  let roadMisses = 0;
  ROADS.on('tileerror', () => {{
    if (++roadMisses < 6 || !map.hasLayer(ROADS)) return;
    ROADS.off('tileerror');
    roadsSyncing = true;
    map.removeLayer(ROADS);
    roadsSyncing = false;
    LAYERS.removeLayer(ROADS);
  }});
}}

// 위성 배경이 안 오면 키가 필요 없는 공급자로 갈아탄다.
//
// 키가 만료되거나 등록에서 빠지면 공급자는 그림 대신 오류 문서를 준다 — 게다가 200 으로
// 준다(브이월드가 그렇다). 브라우저는 그것을 그림으로 못 읽고, 남는 것은 타일이 아직
// 안 온 자리의 바탕색뿐이다. **지도는 열리는데 배경만 없는** 화면이 되고, 여는 사람에게는
// 이유가 아무 데도 안 보인다.
//
// 서버가 미리 막을 수 없는 종류의 고장이다. 타일은 지도를 여는 브라우저가 공급자에게
// 직접 받아 가고, 한 번 내보낸 지도 파일은 그 뒤로도 계속 열린다 — 어제 되던 키가
// 오늘 막히면 이미 나간 지도들이 전부 같이 죽는다. 그래서 실패를 화면에서 받는다.
//
// 넉 장이 실패해야 옮긴다. 가장자리 한 장이 비는 것과 배경이 통째로 없는 것은 다르고,
// 앞의 것 때문에 공급자를 바꾸면 더 선명한 사진을 공짜로 내주는 셈이다.
// 사람이 직접 '일반 지도'로 바꿔 둔 뒤라면 건드리지 않는다.
if (D.fallback) {{
  const BACKUP = tiles(D.fallback);
  let misses = 0;
  SAT.on('tileerror', () => {{
    if (++misses < 4 || !map.hasLayer(SAT)) return;
    SAT.off('tileerror');
    map.removeLayer(SAT);
    LAYERS.removeLayer(SAT);
    BACKUP.addTo(map);
    LAYERS.addBaseLayer(BACKUP, '위성사진');
    // 목록에서 고른 것이 아니라 baselayerchange 가 안 뜬다 — 직접 묶는다.
    capZoom(BACKUP);
  }});
}}

const bounds = [];

// 도보 경로 — 갈래별 색. 계단이 어디서 시작되는지가 보여야 한다.
//
// 실선이다. 한때 파선이었는데 그건 주행선(실선)과 갈라 보이려던 것이고, 주행선을
// 지도에서 뺀 뒤로는 갈라야 할 상대가 없다. 파선은 짧은 구간에서 점 몇 개로 흩어져
// 오히려 안 보인다 — 1100고지의 10m 계단이 그랬다.
//
// 흰 테두리를 깔아 위성 타일 위에서 선이 묻히지 않게 한다.
//
// 안쪽에 얹는 화살촉도 흰색이라 **둘이 붙으면 방향이 안 읽힌다.** 그래서 화살촉을
// 색 선 안에 확실히 가둔다 — 화살촉 바깥 지름이 5.5px 이고 선이 9px 이라 좌우로
// 1.7px 씩 색이 남는다. 이 여백이 화살표와 테두리를 갈라 놓는 전부다.
// 화살촉을 키우거나 선을 얇게 하면 그 여백부터 사라진다(`#arw` 의 markerWidth).
const WALK_W = 9;
D.walks.forEach(w => {{
  L.polyline(w.points, {{
    color:'#ffffff', weight:WALK_W + 4, opacity:.95, interactive:false
  }}).addTo(map);
  L.polyline(w.points, {{
    color:w.color, weight:WALK_W, opacity:.95
  }}).bindPopup(
    '<b>' + w.kind + '</b><span class="k">걷는 구간</span>' +
    (w.note ? '<br>' + w.note : '')
  ).addTo(map);
  w.points.forEach(p => bounds.push(p));
}});

// 그 자리에 있는 것 — 벤치·평상·사슴동상처럼 사람이 가 보고 적어 둔 것.
//
// 지금까지 이것은 구간 팝업 안에만 있었다. 즉 **선을 눌러야 보였다.** 밤에 짐을 들고
// 오르는 사람에게 "여기 앉을 데가 있다"는 미리 보여야 쓸모가 있는 정보이고, 눌러서
// 찾아낼 리가 없다. 그래서 지도 위로 꺼낸다.
//
// 찍는 자리는 구간의 가운데 점이다. 원자료가 이 말을 점이 아니라 `from`–`to` 구간에
// 달아 두었기 때문이고, 대부분 한 칸짜리라 사실상 그 점이다.
const landmarks = L.layerGroup();
D.walks.forEach(w => {{
  if (!w.landmark) return;
  const at = w.points[Math.floor(w.points.length / 2)];
  const icon = L.divIcon({{
    className: 'lmk',
    html: '<i></i><b></b>',
    iconSize: [0, 0], iconAnchor: [0, 0], popupAnchor: [0, -6]
  }});
  const pin = L.marker(at, {{ icon, zIndexOffset: -100 }})
    .bindPopup('<b>' + w.landmark + '</b><span class="k">걷는 길에</span>' +
               (w.note ? '<br>' + w.note : ''));
  // 낱말은 넣어 두지 않고 심고 나서 넣는다 — 사람이 적은 말이 그대로 HTML 로 읽히면
  // 안 된다. `textContent` 는 무엇이 들어오든 글자로만 그린다.
  pin.on('add', () => {{
    const b = pin.getElement() && pin.getElement().querySelector('b');
    if (b) b.textContent = w.landmark;
  }});
  landmarks.addLayer(pin);
}});

// 진행 방향 — 굵은 선 안쪽에 흰 화살촉을 일정 간격으로 얹는다.
//
// **조각마다 얹지 않는다.** 조각은 한 줄이던 길을 노면별로 자른 것이라 10m 짜리도
// 있고(1100고지의 계단), 그런 조각에는 화살표가 한 개도 안 들어간다. 같은 `route`
// 끼리 다시 이어 붙여 길 전체에 고르게 얹는다.
function samePoint(a, b) {{
  return Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
}}
const routes = new Map();
D.walks.forEach(w => {{
  const line = routes.get(w.route) || [];
  // 이웃한 조각은 자른 자리의 점을 서로 나눠 갖는다. 그대로 이으면 같은 점이 두 번
  // 들어가 그 자리에서 길이 0 인 마디가 생긴다.
  const head = (line.length && samePoint(line[line.length - 1], w.points[0])) ? 1 : 0;
  for (let i = head; i < w.points.length; i++) line.push(w.points[i]);
  routes.set(w.route, line);
}});

// 화살표는 SVG `marker-mid` 로 그린다 — 꼭짓점마다 진행 방향으로 브라우저가 직접
// 돌려 준다. 각도를 우리가 재지 않으므로 줌이 바뀌어도 틀어질 데가 없다.
//
// `marker-mid` 는 **가운데 꼭짓점에만** 찍힌다. 그래서 리샘플한 점 앞뒤로 길의 첫
// 점과 끝 점을 덧대, 찍고 싶은 점이 전부 '가운데'가 되게 한다.
//
// 선 자체는 안 보이게 두되 `stroke` 를 없애지는 않는다(투명하게만 한다) — 칠할 선이
// 아예 없는 도형에 마커를 그려 주는지는 브라우저마다 믿을 것이 못 된다.
const ARROW_GAP = 26;
// 화면 범위(`fitBounds`)는 아래에서 잡는다. 그 전까지 지도는 '아직 안 열린' 상태이고
// Leaflet 은 그동안 얹은 겹의 `onAdd` 를 미뤄 둔다 — 즉 지금 `getElement()` 는 아직
// 없다. 생겼을 때 붙인다.
function markArrows(path) {{
  const el = path.getElement();
  if (el) el.setAttribute('marker-mid', 'url(#arw)');
  else path.once('add', () => markArrows(path));
}}
const arrows = [];
routes.forEach(line => {{
  if (line.length < 2) return;
  const path = L.polyline([], {{
    color:'#ffffff', weight:1, opacity:0, interactive:false,
    // **단순화를 꺼야 한다.** Leaflet 은 기본으로 폴리라인을 화면좌표에서 줄이는데
    // (`smoothFactor`), 곧은 구간의 공선점부터 지운다. 여기 점들은 화살촉을 앉히려고
    // 일부러 고르게 심어 둔 것이라, 그러면 **직선에서 화살표가 통째로 사라지고
    // 꺾이는 데만 남아** 간격이 들쭉날쭉해진다.
    smoothFactor: 0
  }}).addTo(map);
  markArrows(path);
  arrows.push({{ line: line, path: path }});
}});

// 간격은 **화면 픽셀**로 잡는다. 미터로 고정하면 줌아웃했을 때 화살촉이 서로 겹쳐
// 선이 흰 띠가 되고, 당기면 한 화면에 한두 개만 남아 방향이 안 보인다.
function resample(line, gap) {{
  const P = line.map(p => map.latLngToLayerPoint(L.latLng(p[0], p[1])));
  const out = [];
  // 첫 화살촉은 반 칸 뒤에서 — 출발 지점 마커와 겹치면 둘 다 안 읽힌다.
  let carry = gap * 0.6;
  for (let i = 1; i < P.length; i++) {{
    const a = P[i - 1], b = P[i];
    const d = Math.sqrt((b.x - a.x) * (b.x - a.x) + (b.y - a.y) * (b.y - a.y));
    if (d < 1e-6) continue;
    let t = 0;
    while (t + carry <= d) {{
      t += carry;
      carry = gap;
      out.push(map.layerPointToLatLng(
        L.point(a.x + (b.x - a.x) * t / d, a.y + (b.y - a.y) * t / d)));
    }}
    carry -= (d - t);
  }}
  return out;
}}

// 같은 자리에 겹친 점은 살짝 벌려 그린다. 공공데이터의 화장실과 충전소가 같은
// 주소로 지오코딩돼 좌표가 0.1m 차이인 경우가 있는데, 그대로 두면 나중에 그린 것이
// 앞의 것을 통째로 덮어 "있다고 적혀 있는데 핀이 없다"가 된다.
//
// **좌표를 고치는 게 아니라 그리기만 옮긴다.** 팝업의 이름·거리는 원래 값 그대로다.
const SPREAD_M = 7;
const seen = new Map();
const pins = new Map();
const drawn = [];

// 편의시설(주차·화장실)은 따로 담는다. 전체가 보이는 화면에서는 관측지 넷만 보여야
// 어디가 어디인지 읽히고, 핀 열두 개가 뭉쳐 있으면 그게 안 된다. 한 곳을 들여다볼
// 만큼 당겼을 때 켠다.
const facilities = L.layerGroup();
D.markers.forEach(m => {{
  const key = m.lat.toFixed(5) + ',' + m.lon.toFixed(5);
  const n = seen.get(key) || 0;
  seen.set(key, n + 1);
  m.drawLat = m.lat;
  m.drawLon = m.lon;
  if (n > 0) {{
    const angle = (n - 1) * (Math.PI * 2 / 6) + Math.PI / 6;
    const dLat = (SPREAD_M / 111194) * Math.cos(angle);
    const dLon = (SPREAD_M / (111320 * Math.cos(m.lat * Math.PI / 180)))
                 * Math.sin(angle);
    m.drawLat += dLat;
    m.drawLon += dLon;
  }}
}});

// 범례의 그림 — 지도 마커와 같은 그림을 같은 자리에서 꺼내 끼운다.
document.querySelectorAll('.ic[data-kind]').forEach(el => {{
  const art = D.icons[el.dataset.kind];
  if (art) el.src = art.url;
}});

// 마커 — 그림이 있는 갈래는 그림으로, 없으면 색 동그라미에 글자로 그린다.
//
// 그림이 색과 글자를 **둘 다 대신한다**. 별·P·화장실 픽토그램은 색맹이나 흑백
// 출력에서도 형태로 갈리므로, 색만으로 나누지 않는다는 원칙은 그대로 지켜진다.
//
// 목록 번호(`badge`)는 그림 위에 따로 얹는다. 여러 곳을 한 장에 그리면 별이 전부
// 같은 모양이라, 번호가 없으면 지도의 이 별이 목록 몇 번인지 알 길이 없다.
// 그림에 흰 테두리를 두르느라 둘레에 여백이 있다(`build_icons.py` 의 `PAD`).
// 그만큼 알맹이가 작아 보이므로 상자를 조금 키워 예전 크기감을 되찾는다.
const ICON_PX = 32;
D.markers.forEach(m => {{
  const art = D.icons[m.kind];
  // 그림의 어느 점이 그 좌표인지는 그림마다 다르다(물방울 표지는 뾰족한 끝).
  // 비율로 받아 지금 크기에 곱한다.
  const anchor = art
    ? [art.at[0] * ICON_PX, art.at[1] * ICON_PX]
    : [11, 11];
  const face = art
    ? '<img src="' + art.url + '" width="' + ICON_PX + '" height="' + ICON_PX +
      '" alt="" draggable="false">'
    : '<div style="min-width:22px;height:22px;padding:0 3px;' +
      'border-radius:11px;background:' + m.color +
      ';color:#fff;font:700 11px/22px system-ui;text-align:center;' +
      'box-shadow:0 0 0 2px #fff,0 1px 4px rgba(15,23,42,.4)">' +
      m.glyph + '</div>';
  const icon = L.divIcon({{
    className: art ? 'mk art' : 'mk',
    html: face + (m.badge ? '<u></u>' : ''),
    iconSize: [art ? ICON_PX : 22, art ? ICON_PX : 22],
    iconAnchor: anchor,
    popupAnchor: [0, -anchor[1] - 2]
  }});
  const note = m.note ? '<span class="k">' + m.note + '</span>' : '';
  const pin = L.marker([m.drawLat, m.drawLon], {{ icon }})
    .bindPopup('<b>' + m.name + '</b><span class="k">' + m.kindLabel + '</span>' +
               (note ? '<br>' + note : ''));
  // 번호는 심고 나서 글자로 넣는다 — 무엇이 들어오든 HTML 로 읽히지 않게.
  if (m.badge) {{
    pin.on('add', () => {{
      const b = pin.getElement() && pin.getElement().querySelector('u');
      if (b) b.textContent = m.badge;
    }});
  }}
  if (m.kind === 'spot') {{
    pin.addTo(map);
    // 화면 범위는 관측지로만 잡는다. 편의시설까지 넣으면 처음 화면이 넓어져
    // 정작 봐야 할 점들이 더 작아진다.
    bounds.push([m.lat, m.lon]);
  }} else if (m.kind === 'origin') {{
    // 출발지는 늘 보이되 **화면 범위에는 넣지 않는다**. 넣으면 제주를 가로지르는
    // 사각형이 되어 지도가 섬 전체로 줌아웃된다 — 그러면 정작 봐야 할 도보 경로와
    // 계단이 점으로 뭉개진다. 줌아웃하면 "내가 여기서 저만큼 떨어져 있구나"가 보인다.
    pin.addTo(map);
  }} else {{
    facilities.addLayer(pin);
  }}
  pins.set(m.lat.toFixed(5) + ',' + m.lon.toFixed(5), pin);
  drawn.push(pin);
}});

// 실사진이 있는 줌보다 더 당기지 않는다. 도보 경로가 짧은 곳(1100고지는 25m·26m·
// 10m·7m)은 fitBounds 가 z20 까지 당기는데, 그 줌엔 사진이 없어 마지막 타일을 늘린
// 흐릿한 화면이 된다. 조금 덜 확대하고 선명한 편이 낫다.
//
// **처음 화면은 찍은 것이 전부 보이게** 연다. 어디가 어디쯤인지를 먼저 잡고, 목록에서
// 하나를 누르면 그때 들여다본다.
if (bounds.length > 1) {{
  map.fitBounds(bounds, {{ padding:[48, 48], maxZoom: D.sat.maxNative }});
}} else {{
  map.setView(bounds[0], Math.min(16, D.sat.maxNative));
}}

// 한 곳을 눌렀을 때 들어갈 깊이 — **실사진이 있는 만큼 끝까지**(`maxNative`).
//
// 누르는 이유가 "이 자리를 들여다보려고"라서, 주차 구획과 세워진 차·탐방로 초입이
// 보여야 답이 된다. 그건 z19 쯤부터 보인다.
//
// 처음 화면에서 몇 단계로 잡는 방식은 버렸다. 섬 전체가 보이는 추천 지도는 z12 쯤에서
// 열리는데 거기서 네 단계면 z16 이고, 그 줌에서는 산비탈만 보이지 주차장이 안 보인다.
// 필요한 깊이는 처음 화면과 무관하게 정해져 있으므로 그것을 바로 쓴다.
//
// 그 위로는 안 간다 — 사진이 없는 줌이라 마지막 타일을 늘린 흐릿한 화면이 될 뿐이다.
// 한 곳만 그린 지도가 이미 그보다 깊게 열렸다면 그대로 둔다.
const OVERVIEW_ZOOM = map.getZoom();
const FOCUS_ZOOM = Math.max(D.sat.maxNative, OVERVIEW_ZOOM);

// 이만큼 당기면 자세한 것들을 켠다. z16 이면 타일 하나가 600m 쯤이라 주차장과 화장실이
// 서로 갈려 보이기 시작한다. 그보다 얕으면 점이 겹쳐 무엇이 무엇인지 알 수 없다.
// 한 곳만 그린 지도는 이미 그보다 깊게 열리므로 처음부터 켜져 있다.
//
// 화살표와 벤치 라벨도 같은 문턱을 쓴다. 섬 전체가 보이는 화면에서 길은 몇 픽셀짜리
// 실인데, 거기 화살촉과 낱말을 얹으면 길이 무엇이었는지조차 안 보인다.
const DETAIL_ZOOM = Math.min(16, D.sat.maxNative);
function syncDetail() {{
  const near = map.getZoom() >= DETAIL_ZOOM;
  [facilities, landmarks].forEach(group => {{
    if (near && !map.hasLayer(group)) group.addTo(map);
    else if (!near && map.hasLayer(group)) map.removeLayer(group);
  }});
  // 화살촉은 켜고 끄는 것이 아니라 **다시 심는다**. 간격이 화면 픽셀이라 줌이 바뀌면
  // 자리가 통째로 달라진다.
  arrows.forEach(a => {{
    const mid = near ? resample(a.line, ARROW_GAP) : [];
    a.path.setLatLngs(mid.length
      ? [a.line[0]].concat(mid, [a.line[a.line.length - 1]])
      : []);
  }});
}}
map.on('zoomend', syncDetail);
syncDetail();

// 한 곳으로 옮겨 갈 때는 **날아간다**. `setView` 는 화면을 통째로 갈아치우므로
// 지금 보던 자리와 도착한 자리가 이어지지 않는다 — 일곱 단계를 뛰면 특히 그렇다.
// `flyTo` 는 줌아웃했다가 옮겨서 다시 당기는 한 동작이라, 어디서 어디로 갔는지가
// 화면에 남는다.
//
// 팝업은 **도착한 뒤에** 연다. 나는 도중에 열면 팝업이 화면 안에 들어오려고 지도를
// 따로 밀어서 두 움직임이 겹친다. 듣는 등록을 먼저 해 두는 것은 애니메이션이 꺼진
// 환경에서 `flyTo` 가 그 자리에서 끝나 버리기 때문이다.
function fly(latlng, then) {{
  if (then) map.once('moveend', then);
  map.flyTo(latlng, FOCUS_ZOOM, {{ duration: .8 }});
}}

// 점을 눌러도 목록 줄을 누른 것과 같이 움직인다. 전체가 보이는 화면에서 점 하나를
// 겨우 눌렀는데 팝업만 뜨고 화면이 그대로면, 결국 손으로 다시 확대하게 된다.
drawn.forEach(pin => {{
  pin.on('click', () => fly(pin.getLatLng()));
}});

// 목록 — 마커만으로는 어디가 어디인지 모른다. 눌러서 그 자리로 이동한다.
if (D.items.length) {{
  const box = document.getElementById('list');
  D.items.forEach(it => {{
    const row = document.createElement('button');
    row.className = 'row';
    row.innerHTML =
      '<span class="nm"></span><div class="sb"></div><div class="fx"></div>';
    row.querySelector('.nm').textContent = it.label;
    row.querySelector('.sb').textContent = it.sub;
    const fx = row.querySelector('.fx');
    it.facts.forEach(f => {{
      const tag = document.createElement('b');
      tag.textContent = f.text;
      tag.style.background = f.bg;
      tag.style.color = f.fg;
      fx.appendChild(tag);
    }});
    row.addEventListener('click', () => {{
      const pin = pins.get(it.lat.toFixed(5) + ',' + it.lon.toFixed(5));
      fly([it.lat, it.lon], pin ? () => pin.openPopup() : null);
    }});
    box.appendChild(row);
  }});
}}
</script>
</body>
</html>
"""
