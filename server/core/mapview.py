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


def _points(path: list[tuple[float, float]] | None) -> list[list[float]]:
    return [[lat, lon] for lat, lon in (path or [])]


def render(
    title: str,
    markers: list[Marker],
    satellite: Tiles | None = None,
    walk_segments: list[tuple[list[tuple[float, float]], str, str]] | None = None,
    items: list[Item] | None = None,
) -> str:
    """지도 HTML 한 장. 열기만 하면 되는 자립형 문서다.

    Args:
        title: 문서 제목이자 화면 왼쪽 위 제목.
        markers: 찍을 점들. 하나도 없으면 지도를 만들지 않는다(빈 문자열).
        satellite: 위성 배경. 생략하면 키가 필요 없는 기본 공급자를 쓴다.
        walk_segments: (점렬, 갈래, 설명) 짝들. 갈래는 `계단`·`돌길`·`흙길`·`포장`
            처럼 무엇을 밟는가이며 색이 거기서 갈린다. 설명은 구간을 눌렀을 때 뜨는
            한 줄(길이·노면·경사)이다.
        items: 패널에 펼 목록. 여러 곳을 그릴 때 어디가 어디인지와 각 곳의 난이도·
            계단·도보를 한눈에 견주게 한다.

    Returns:
        완결된 HTML 문자열. 마커가 하나도 없으면 빈 문자열 — 그릴 것이 없는데
        빈 지도를 내보내면 "지도가 있다"는 잘못된 신호가 된다.
    """
    if not markers:
        return ""

    sat = satellite or DEFAULT_SATELLITE
    data = {
        "sat": {
            "url": sat.url,
            "credit": sat.attribution,
            "maxNative": sat.max_native_zoom,
            "maxZoom": sat.max_zoom,
        },
        "markers": [
            {
                "lat": m.lat,
                "lon": m.lon,
                "color": _KINDS.get(m.kind, _FALLBACK)[0],
                "glyph": m.glyph or _KINDS.get(m.kind, _FALLBACK)[1],
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
                "note": note,
                "color": _WALK_COLORS.get(kind, _WALK_FALLBACK),
            }
            for pts, kind, note in (walk_segments or [])
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
  .ln {{ width:18px; height:0; border-top:3px solid var(--c); display:inline-block; }}
  .ln.dash {{ border-top-style:dashed; }}
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
  /* 위성 배경 위에서는 글자·컨트롤이 묻히므로 바탕을 확실히 준다. */
  .leaflet-control-layers {{ font-size:12px; }}
  .leaflet-control-attribution {{ font-size:10px; }}
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <h1>{title}</h1>
  <div id="list"></div>
  <div class="legend">{legend}</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const D = {data};

const map = L.map('map', {{ zoomControl: true }});
// 위성사진 — 기본 배경. 실사진이 있는 줌보다 더 당기면 마지막 타일을 늘린다.
const SAT = L.tileLayer(D.sat.url, {{
  maxZoom: D.sat.maxZoom,
  maxNativeZoom: D.sat.maxNative,
  attribution: D.sat.credit
}});
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
  }}).bindPopup(
    '<b>' + w.kind + '</b><span class="k">걷는 구간</span>' +
    (w.note ? '<br>' + w.note : '')
  ).addTo(map);
  w.points.forEach(p => bounds.push(p));
}});

// 같은 자리에 겹친 점은 살짝 벌려 그린다. 공공데이터의 화장실과 충전소가 같은
// 주소로 지오코딩돼 좌표가 0.1m 차이인 경우가 있는데, 그대로 두면 나중에 그린 것이
// 앞의 것을 통째로 덮어 "있다고 적혀 있는데 핀이 없다"가 된다.
//
// **좌표를 고치는 게 아니라 그리기만 옮긴다.** 팝업의 이름·거리는 원래 값 그대로다.
const SPREAD_M = 7;
const seen = new Map();
const pins = new Map();
const drawn = [];
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

// 마커 — 갈래마다 색과 글자를 함께 준다(색만으로 나누지 않는다).
D.markers.forEach(m => {{
  const icon = L.divIcon({{
    className: '',
    html: '<div style="min-width:22px;height:22px;padding:0 3px;' +
          'border-radius:11px;background:' + m.color +
          ';color:#fff;font:700 11px/22px system-ui;text-align:center;' +
          'box-shadow:0 0 0 2px #fff,0 1px 4px rgba(15,23,42,.4)">' +
          m.glyph + '</div>',
    iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -12]
  }});
  const note = m.note ? '<span class="k">' + m.note + '</span>' : '';
  const pin = L.marker([m.drawLat, m.drawLon], {{ icon }})
    .bindPopup('<b>' + m.name + '</b><span class="k">' + m.kindLabel + '</span>' +
               (note ? '<br>' + note : ''))
    .addTo(map);
  pins.set(m.lat.toFixed(5) + ',' + m.lon.toFixed(5), pin);
  drawn.push(pin);
  bounds.push([m.lat, m.lon]);
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

// 점을 눌러도 목록 줄을 누른 것과 같이 움직인다. 전체가 보이는 화면에서 점 하나를
// 겨우 눌렀는데 팝업만 뜨고 화면이 그대로면, 결국 손으로 다시 확대하게 된다.
drawn.forEach(pin => {{
  pin.on('click', () => map.setView(pin.getLatLng(), FOCUS_ZOOM));
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
      map.setView([it.lat, it.lon], FOCUS_ZOOM);
      const pin = pins.get(it.lat.toFixed(5) + ',' + it.lon.toFixed(5));
      if (pin) pin.openPopup();
    }});
    box.appendChild(row);
  }});
}}
</script>
</body>
</html>
"""
