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
그래서 Esri World Imagery 를 기본 배경으로 깔고 일반 지도를 토글로 둔다.

제주 상공의 실제 사진은 **z18 까지**다(그 위 줌은 빈 타일이 온다 — 새별오름·성판악·
해안 세 곳에서 z19 부터 2KB 짜리가 왔다). 그래서 `maxNativeZoom` 을 18 로 두어 더
당기면 z18 타일을 늘려 보여준다. 빈 타일을 그대로 받으면 화면이 회색으로 비어 버린다.

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
    "parking": ("#22c55e", "P", "주차"),
    "toilet": ("#a855f7", "화", "화장실"),
}
_FALLBACK = ("#94a3b8", "·", "지점")

#: 도보 구간 갈래 → 색. "20분 걷는다"까지만 보이면 **어디서 계단이 시작되는지**를
#: 모른다. 밤에 초행으로 오르는 사람에게는 그게 준비를 가르는 정보다.
#: 밟기 힘든 순으로 색이 진해진다 — 포장(하늘) → 흙(주황) → 돌(황토) → 암반(갈색)
#: → 계단(빨강). 모르는 구간은 회색으로, 쉬운 쪽으로 오해되지 않게 둔다.
_WALK_COLORS: dict[str, str] = {
    "포장": "#38bdf8",
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


def _points(path: list[tuple[float, float]] | None) -> list[list[float]]:
    return [[lat, lon] for lat, lon in (path or [])]


def render(
    title: str,
    markers: list[Marker],
    walk_segments: list[tuple[list[tuple[float, float]], str]] | None = None,
    caption: str = "",
    items: list[Item] | None = None,
) -> str:
    """지도 HTML 한 장. 열기만 하면 되는 자립형 문서다.

    Args:
        title: 문서 제목이자 화면 왼쪽 위 제목.
        markers: 찍을 점들. 하나도 없으면 지도를 만들지 않는다(빈 문자열).
        walk_segments: (점렬, 갈래) 짝들. 갈래는 `계단`·`돌길`·`흙길`·`포장` 처럼
            무엇을 밟는가이며, 색이 거기서 갈린다.
        caption: 제목 아래 한 줄 설명(소요시간 등).
        items: 옆에 펼 목록. 여러 곳을 그릴 때 어디가 어디인지와 각 곳의 난이도·
            계단·도보를 한눈에 견주게 한다. 비면 목록 박스를 만들지 않는다.

    Returns:
        완결된 HTML 문자열. 마커가 하나도 없으면 빈 문자열 — 그릴 것이 없는데
        빈 지도를 내보내면 "지도가 있다"는 잘못된 신호가 된다.
    """
    if not markers:
        return ""

    data = {
        "markers": [
            {
                "lat": m.lat,
                "lon": m.lon,
                "color": _KINDS.get(m.kind, _FALLBACK)[0],
                "glyph": _KINDS.get(m.kind, _FALLBACK)[1],
                "kindLabel": _KINDS.get(m.kind, _FALLBACK)[2],
                "name": m.name,
                "note": m.note,
            }
            for m in markers
        ],
        "walks": [
            {
                "points": _points(pts),
                "kind": kind,
                "color": _WALK_COLORS.get(kind, _WALK_FALLBACK),
            }
            for pts, kind in (walk_segments or [])
            if len(pts or []) > 1
        ],
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
            legend.append(f'<i class="ln dash" style="--c:{color}"></i>{kind}')
    for kind in ("spot", "parking", "toilet"):
        if any(m.kind == kind for m in markers):
            color, glyph, label = _KINDS[kind]
            legend.append(f'<i class="pin" style="--c:{color}">{glyph}</i>{label}')

    return _TEMPLATE.format(
        title=html.escape(title),
        caption=html.escape(caption),
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
  #map {{ position:absolute; inset:0; background:var(--bg); }}
  .panel {{
    position:absolute; z-index:1000; top:12px; left:12px;
    max-width:min(340px, calc(100% - 24px));
    background:var(--card); border-radius:10px; padding:12px 14px;
    box-shadow:0 2px 12px rgba(15,23,42,.16); color:var(--ink);
  }}
  .panel h1 {{ margin:0 0 4px; font-size:15px; font-weight:650; }}
  .panel p {{ margin:0 0 10px; font-size:12px; color:var(--ink-2); line-height:1.5; }}
  .legend {{
    display:flex; flex-wrap:wrap; gap:6px 12px;
    font-size:11.5px; color:var(--ink);
  }}
  .legend span {{ display:inline-flex; align-items:center; gap:5px; }}
  .pin {{
    width:16px; height:16px; border-radius:50%; background:var(--c); color:#fff;
    font-size:9px; font-weight:700; display:inline-flex; align-items:center;
    justify-content:center; font-style:normal;
  }}
  .ln {{ width:18px; height:0; border-top:3px solid var(--c); display:inline-block; }}
  .ln.dash {{ border-top-style:dashed; }}
  .leaflet-popup-content {{ margin:10px 12px; font-size:12px; line-height:1.6; }}
  .leaflet-popup-content b {{ display:block; font-size:13px; margin-bottom:2px; }}
  .leaflet-popup-content .k {{ color:#64748b; font-size:11px; }}
  /* 목록 박스 — 여러 곳을 한눈에 견주는 표. 좁은 화면에서는 지도 아래로 내린다. */
  .list {{
    position:absolute; z-index:1000; top:12px; right:12px; width:290px;
    max-height:calc(100% - 24px); overflow-y:auto;
    background:var(--card); border-radius:10px; padding:8px;
    box-shadow:0 2px 12px rgba(15,23,42,.16); color:var(--ink);
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
    .list {{
      position:static; width:auto; max-height:45%; margin:0;
      border-radius:0; box-shadow:none; border-top:1px solid #e2e8f0;
    }}
    #map {{ position:absolute; inset:0 0 45% 0; }}
    body {{ display:flex; flex-direction:column; }}
  }}
  /* 위성 배경 위에서는 글자·컨트롤이 묻히므로 바탕을 확실히 준다. */
  .leaflet-control-layers {{ font-size:12px; }}
  .leaflet-control-attribution {{ font-size:10px; }}
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <h1>{title}</h1>
  <p>{caption}</p>
  <div class="legend">{legend}</div>
</div>
<div class="list" id="list" hidden></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D = {data};

const map = L.map('map', {{ zoomControl: true }});
// 위성사진 — 기본 배경. 제주 실사진은 z18 까지라 그 위는 늘려 보여준다.
const SAT = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/' +
  'MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{
    maxZoom: 20, maxNativeZoom: 18,
    attribution: '위성사진 &copy; Esri · Maxar · Earthstar Geographics'
  }}
);
// 일반 지도 — 지명·도로 이름을 읽어야 할 때. 위성 위에서는 글자가 잘 안 읽힌다.
const PLAIN = L.tileLayer(
  'https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png',
  {{
    maxZoom: 20,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' +
      ' 기여자 · 타일 &copy; <a href="https://carto.com/attributions">CARTO</a>'
  }}
);
SAT.addTo(map);
L.control.layers({{ '위성사진': SAT, '일반 지도': PLAIN }}, null,
                 {{ collapsed: false }}).addTo(map);
L.control.scale({{ imperial:false }}).addTo(map);

const bounds = [];

// 도보 경로 — 갈래별 색. 계단이 어디서 시작되는지가 보여야 한다.
// 흰 테두리를 깔아 위성 타일 위에서 선이 묻히지 않게 한다.
D.walks.forEach(w => {{
  L.polyline(w.points, {{ color:'#ffffff', weight:8, opacity:.9 }}).addTo(map);
  L.polyline(w.points, {{
    color:w.color, weight:4, opacity:.95, dashArray:'7 6'
  }}).bindPopup('걷는 구간: <b>' + w.kind + '</b>').addTo(map);
  w.points.forEach(p => bounds.push(p));
}});

// 마커 — 갈래마다 색과 글자를 함께 준다(색만으로 나누지 않는다).
D.markers.forEach(m => {{
  const icon = L.divIcon({{
    className: '',
    html: '<div style="width:22px;height:22px;border-radius:50%;background:' + m.color +
          ';color:#fff;font:700 10px/22px system-ui;text-align:center;' +
          'box-shadow:0 0 0 2px #fff,0 1px 4px rgba(15,23,42,.4)">' +
          m.glyph + '</div>',
    iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -12]
  }});
  const note = m.note ? '<span class="k">' + m.note + '</span>' : '';
  L.marker([m.lat, m.lon], {{ icon }})
    .bindPopup('<b>' + m.name + '</b><span class="k">' + m.kindLabel + '</span>' +
               (note ? '<br>' + note : ''))
    .addTo(map);
  bounds.push([m.lat, m.lon]);
}});

// 목록 박스 — 마커만으로는 어디가 어디인지 모른다. 눌러서 그 자리로 이동한다.
if (D.items.length) {{
  const box = document.getElementById('list');
  box.hidden = false;
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
    row.addEventListener('click', () => map.setView([it.lat, it.lon], 16));
    box.appendChild(row);
  }});
}}

if (bounds.length > 1) map.fitBounds(bounds, {{ padding:[48, 48] }});
else map.setView(bounds[0], 15);
</script>
</body>
</html>
"""
