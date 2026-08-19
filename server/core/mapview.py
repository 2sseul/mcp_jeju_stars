"""경로 지도 HTML 만들기 — 문자열을 돌려주는 순수 함수 (파일도 네트워크도 없다).

좌표를 말로 설명하지 않는다(`plan.md` P13). "차로 29분" 다음에 사람이 실제로 묻는
것은 "어느 길로, 어디에 세우고, 거기서 얼마나 걷나"이고, 그건 선으로 보여야 한다.

무엇을 그리나 — 축마다 선·점이 다르다
--------------------------------------------------------------------------
    주행 경로   출발지 → 주차 지점.  `core.routing.route_path` 의 점렬(실제 도로)
    도보 경로   주차 지점 → 관측 지점. `jeju_spots.json` 의 `walk_routes[].points`
    마커        출발지 · 관측지 · 주차장 · 화장실

**두 선을 다르게 그린다.** 차로 가는 구간과 걸어 올라가는 구간은 준비가 다르다 —
주행 20분에 도보 20분인 곳을 한 색으로 그으면 "40분 거리"로 뭉개진다.

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
    "origin": ("#3b82f6", "출", "출발지"),
    "spot": ("#f59e0b", "★", "관측 지점"),
    "parking": ("#22c55e", "P", "주차"),
    "toilet": ("#a855f7", "화", "화장실"),
}
_FALLBACK = ("#94a3b8", "·", "지점")

#: 선 색. 주행은 파랑 실선, 도보는 주황 파선 — 준비가 다른 구간이라 눈에 갈려야 한다.
_DRIVE_COLOR = "#3b82f6"
_WALK_COLOR = "#f59e0b"


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
    drive_path: list[tuple[float, float]] | None = None,
    walk_paths: list[list[tuple[float, float]]] | None = None,
    caption: str = "",
) -> str:
    """지도 HTML 한 장. 열기만 하면 되는 자립형 문서다.

    Args:
        title: 문서 제목이자 화면 왼쪽 위 제목.
        markers: 찍을 점들. 하나도 없으면 지도를 만들지 않는다(빈 문자열).
        drive_path: 주행 경로 점렬. 없으면 선을 안 그린다(출발지를 안 준 경우).
        walk_paths: 도보 경로 점렬들. 관측지에 경로가 여럿일 수 있다.
        caption: 제목 아래 한 줄 설명(소요시간 등).

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
        "drive": _points(drive_path),
        "walks": [_points(w) for w in (walk_paths or [])],
        "driveColor": _DRIVE_COLOR,
        "walkColor": _WALK_COLOR,
    }

    # 범례는 실제로 그린 것만 싣는다. 없는 것을 범례에만 두면 "왜 안 보이지"가 된다.
    legend = []
    if data["drive"]:
        legend.append(f'<i class="ln" style="--c:{_DRIVE_COLOR}"></i>차로 가는 길')
    if any(data["walks"]):
        legend.append(f'<i class="ln dash" style="--c:{_WALK_COLOR}"></i>걸어 가는 길')
    for kind in ("origin", "spot", "parking", "toilet"):
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

// 주행 경로 — 실선. 흰 테두리를 깔아 타일 위에서 선이 묻히지 않게 한다.
if (D.drive.length > 1) {{
  L.polyline(D.drive, {{ color:'#ffffff', weight:8, opacity:.9 }}).addTo(map);
  L.polyline(D.drive, {{ color:D.driveColor, weight:4, opacity:.95 }}).addTo(map);
  D.drive.forEach(p => bounds.push(p));
}}

// 도보 경로 — 파선. 차로 가는 구간과 눈에 갈려야 한다.
D.walks.forEach(w => {{
  if (w.length > 1) {{
    L.polyline(w, {{ color:'#ffffff', weight:8, opacity:.9 }}).addTo(map);
    L.polyline(w, {{
      color:D.walkColor, weight:4, opacity:.95, dashArray:'7 6'
    }}).addTo(map);
    w.forEach(p => bounds.push(p));
  }}
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

if (bounds.length > 1) map.fitBounds(bounds, {{ padding:[48, 48] }});
else map.setView(bounds[0], 15);
</script>
</body>
</html>
"""
