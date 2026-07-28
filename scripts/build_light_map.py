"""제주 인공광 지도 HTML 생성 (발표용, 오프라인 배치).

OSM 타일 위에 이 프로젝트가 판정에 쓰는 광원 3신호를 그대로 겹쳐 한 장으로 보여준다.
결과물은 **파일 하나**(`outputs/jeju_light_map.html`)라 브라우저로 열기만 하면 된다 —
타일만 인터넷에서 받고 데이터는 전부 파일 안에 들어 있다.

레이어 — `server/core` 의 세 축을 그대로 옮긴 것
--------------------------------------------------------------------------
    가로등          `core.lamps`      점 좌표    — 발밑 광원
    가로등 밀도      위 점을 278m 격자로 집계·평활 (개/km²)
    광공해(Falchi)  `core.darkness`   30초각 격자 — 광역 하늘밝기
    야간광(VIIRS)   `core.nightlight` 15초각 격자 — 국지 지상광
    관측지 20곳      `core.darkness.assess_site` 종합 판정을 팝업에

좌표·교정·서비스 범위는 전부 `core` 모듈이 정한 것을 그대로 쓴다. 이 스크립트는
CSV 를 다시 읽지 않는다 — 지도와 판정이 다른 숫자를 말하면 발표 자료로 쓸 수 없다.
(그래서 추자도는 지도에도 없다. `core.lamps` 의 서비스 범위 33.0~33.7 밖이라
가로등 641개가 판정에서 빠지는데, 지도만 예외를 두면 둘이 어긋난다.)

래스터 세 장은 겹쳐 보면 서로를 가리기만 하므로 **한 번에 하나만** 켜지게 묶었다.
확대해도 픽셀을 뭉개지 않는다(`image-rendering: pixelated`) — 원본 해상도가
30초각·15초각·278m 라는 사실을 매끈한 보간으로 감추지 않기 위해서다.

실행:
    uv run python -m scripts.build_light_map
"""

from __future__ import annotations

import base64
import json
import math
import struct
import zlib

import numpy as np

from server import path
from server.core import darkness, lamps, nightlight

# --- 색 ----------------------------------------------------------------------
# dataviz 기준 팔레트의 단일 색상(blue) 순차 램프 100→700. 어두운 베이스맵 위에
# 쓰므로 **역방향**으로 읽는다 — 값이 작으면 어두운 단계(지도에 묻힘), 크면 밝은 단계.
# 순차 인코딩이라 무지개 램프를 쓰지 않는다.
_BLUE = (
    "#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5",
    "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb",
)

#: Falchi 6등급의 순서형 단계(i=가장 어두움 → vi=가장 밝음). 위 램프에서 균등 추출.
#: 어두운 표면 위 순서형 램프는 표면에 가장 가까운 단계도 2:1 을 넘겨야 하므로
#: 600 단계(#184f95)보다 어둡게 내려가지 않는다(dataviz palette.md § Sequential).
_FALCHI_STEPS = ("#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb")

#: 가로등 점 색 — 어두운 지도 표면(#1a1a1a) 기준 대비 3:1 이상(validate_palette.js).
#: 래스터가 전부 파랑 계열이라 점은 보색 쪽 주황으로 떼어 놓는다.
_LAMP_COLOR = "#d95926"

#: 래스터 불투명도 — 타일의 지형·도로가 비쳐야 위치를 읽을 수 있어 1.0 을 쓰지 않는다.
_RASTER_OPACITY = 0.72

# --- 격자 --------------------------------------------------------------------

#: 밀도 격자 한 칸(도). 위도 0.0025° ≈ 278m, 경도 0.003° ≈ 278m(북위 33.4 기준)로
#: 대략 정사각. 칸 면적은 여기서 파생한다.
_DENSITY_DLAT = 0.0025
_DENSITY_DLON = 0.003

#: 밀도 격자 평활 반경(칸). 278m 칸 단위 히스토그램은 얼룩져 읽기 어려워
#: 반경 2칸(≈±550m) 박스 평활을 축마다 한 번씩 건다. 값은 개/km² 로 유지된다.
_DENSITY_BLUR = 2

#: 밀도·야간광 램프의 상한 분위수. 최댓값에 맞추면 도심 몇 칸이 램프를 독점해
#: 나머지가 전부 바닥에 깔린다.
_UPPER_PCT = 99.0

#: 좌표 전송 배율 — 십진 6자리(≈0.1m)면 지도 표시에 충분하고 Int32 에 들어간다.
_COORD_SCALE = 1_000_000

_ATTRIBUTION = (
    '지도 &copy; <a href="https://www.openstreetmap.org/copyright">'
    'OpenStreetMap</a> 기여자 · '
    '타일 &copy; <a href="https://carto.com/attributions">CARTO</a>'
)


# --- PNG 인코딩 ---------------------------------------------------------------

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    """PNG 청크 하나(길이 + 태그 + 데이터 + CRC)."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _png_bytes(rgba: np.ndarray) -> bytes:
    """(h, w, 4) uint8 배열 → PNG 바이트. 필터 0(None) 고정의 최소 구현.

    Pillow 를 쓰지 않는 이유는 이 스크립트 하나 때문에 의존을 늘리지 않기
    위해서다(`build_viirs_grid.py` 가 tifffile 을 임시 의존으로 두는 것과 같은 규율).
    """
    h, w, _ = rgba.shape
    scanlines = np.hstack([np.zeros((h, 1), np.uint8), rgba.reshape(h, w * 4)])
    header = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8bit RGBA, 인터레이스 없음
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(scanlines.tobytes(), 9))
        + _png_chunk(b"IEND", b"")
    )


def _data_uri(rgba: np.ndarray) -> str:
    """RGBA 배열 → `data:` URI. 파일 하나로 유지하려고 외부 이미지를 만들지 않는다."""
    return "data:image/png;base64," + base64.b64encode(_png_bytes(rgba)).decode("ascii")


# --- 램프 ---------------------------------------------------------------------

def _hex_rgb(code: str) -> tuple[int, int, int]:
    return int(code[1:3], 16), int(code[3:5], 16), int(code[5:7], 16)


def _ramp_rgb(t: np.ndarray) -> np.ndarray:
    """0~1 배열 → 파랑 순차 램프 RGB(uint8). t=0 이 가장 어두운 단계."""
    stops = np.array([_hex_rgb(c) for c in _BLUE], dtype=np.float64)
    pos = np.clip(t, 0.0, 1.0) * (len(stops) - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, len(stops) - 1)
    f = (pos - lo)[..., None]
    return np.rint(stops[lo] * (1 - f) + stops[hi] * f).astype(np.uint8)


# --- 래스터 레이어 -------------------------------------------------------------

def _grid_bounds(affine: np.ndarray, shape: tuple[int, int]) -> list[list[float]]:
    """아핀(좌상단 모서리 원점) → Leaflet 경계 [[남, 서], [북, 동]]."""
    origin_lon, origin_lat, scale = affine[0], affine[1], affine[2]
    nrows, ncols = shape
    return [
        [origin_lat - nrows * scale, origin_lon],
        [origin_lat, origin_lon + ncols * scale],
    ]


def _falchi_layer() -> dict:
    """Sky Brightness 격자 → Falchi 등급 6색 래스터 + 등급별 픽셀 수."""
    npz = np.load(path.SB_GRID)
    grid = npz["grid"]
    affine = npz["affine"]
    valid = np.abs(grid - float(affine[3])) > 1e-3

    # 등급 판정은 core 의 순수 함수를 그대로 태운다 — 경계표를 여기서 베끼지 않는다.
    index_of = {g: i for i, g in enumerate(darkness.FALCHI_GRADES)}
    grade_of = np.vectorize(lambda v: index_of[darkness.falchi_of(v)], otypes=[np.int8])
    grades = np.full(grid.shape, -1, dtype=np.int8)
    grades[valid] = grade_of(grid[valid].astype(np.float64))

    rgba = np.zeros((*grid.shape, 4), dtype=np.uint8)
    counts: dict[str, int] = {}
    for idx, grade in enumerate(darkness.FALCHI_GRADES):
        sel = grades == idx
        counts[grade] = int(sel.sum())
        rgba[sel, :3] = _hex_rgb(_FALCHI_STEPS[idx])
    rgba[valid, 3] = 255

    total = int(valid.sum())
    legend = [
        {
            "swatch": _FALCHI_STEPS[i],
            "label": f"{g} — {darkness.falchi_label(g)}",
            "note": (f"제주 육지 {counts[g] / total:.0%}"
                     if counts[g] else "제주에 없음"),
            "dim": counts[g] == 0,
        }
        for i, g in enumerate(darkness.FALCHI_GRADES)
    ]
    return {
        "id": "falchi",
        "name": "광공해 등급 (Falchi)",
        "url": _data_uri(rgba),
        "bounds": _grid_bounds(affine, grid.shape),
        "legendTitle": "광공해 등급 — Falchi et al. (2016)",
        "legendRows": legend,
        "legendNote": "픽셀 30초각(약 0.9km). 값이 클수록 하늘이 밝다(오염).",
    }


def _log_raster(values: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, float]:
    """양수 구간을 로그로 펴서 램프에 태운다. 0·결측은 완전 투명.

    반환은 (RGBA, 램프 상한값). 알파도 값에 따라 올려 '광원 없음'이 지도에 아무 것도
    덧칠하지 않게 한다 — 0 픽셀에 색을 칠하면 없는 정보가 생긴다.
    """
    lit = mask & (values > 0)
    pos = values[lit]
    upper = float(np.percentile(pos, _UPPER_PCT)) if pos.size else 1.0

    t = np.zeros_like(values, dtype=np.float64)
    t[lit] = np.log1p(values[lit]) / math.log1p(upper)
    t = np.clip(t, 0.0, 1.0)

    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    rgba[..., :3] = _ramp_rgb(t)
    rgba[..., 3] = np.rint(np.where(lit, 90 + 165 * t, 0)).astype(np.uint8)
    return rgba, upper


def _ramp_legend(upper: float, unit: str, fmt: str = "{:,.0f}") -> list[dict]:
    """연속 램프의 눈금 4칸(0 · 상한의 1/4 · 1/2 · 상한)."""
    rows = []
    for frac in (0.0, 0.25, 0.5, 1.0):
        val = upper * frac
        t = math.log1p(val) / math.log1p(upper) if upper > 0 else 0.0
        rgb = _ramp_rgb(np.array([t]))[0]
        rows.append(
            {
                "swatch": "#%02x%02x%02x" % tuple(int(c) for c in rgb),
                "label": ("0" if frac == 0 else fmt.format(val)) + f" {unit}",
                "note": "",
                "dim": False,
            }
        )
    rows[-1]["note"] = f"상위 {100 - _UPPER_PCT:.0f}% 는 상한으로 잘림"
    return rows


def _viirs_layer() -> dict:
    """VIIRS 야간광 격자 → 로그 스케일 래스터."""
    npz = np.load(path.VIIRS_GRID)
    grid = npz["grid"].astype(np.float64)
    affine = npz["affine"]
    valid = np.abs(grid - float(affine[3])) > 1e-3

    rgba, upper = _log_raster(grid, valid)
    return {
        "id": "viirs",
        "name": "야간광 (VIIRS/DNB)",
        "url": _data_uri(rgba),
        "bounds": _grid_bounds(affine, grid.shape),
        "legendTitle": "야간광 복사휘도 (로그)",
        "legendRows": _ramp_legend(upper, "nW·cm⁻²·sr⁻¹", "{:,.1f}"),
        "legendNote": (
            f"픽셀 15초각(약 0.46km). 임계 {nightlight.NOISE_FLOOR:g} 미만은 "
            "원본이 0 으로 두므로 칠하지 않는다 — 빈칸은 '어둡다'가 아니라 '모른다'."
        ),
    }


def _blur(grid: np.ndarray, radius: int) -> np.ndarray:
    """축마다 한 번씩 거는 박스 평활(가장자리는 0 으로 채움)."""
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        padded = np.pad(grid, pad)
        acc = np.zeros_like(grid)
        for shift in range(2 * radius + 1):
            sl: list[slice] = [slice(None), slice(None)]
            sl[axis] = slice(shift, shift + grid.shape[axis])
            acc = acc + padded[tuple(sl)]
        grid = acc / (2 * radius + 1)
    return grid


def _density_layer(lat: np.ndarray, lon: np.ndarray) -> dict:
    """가로등 점 → 278m 격자 밀도(개/km²) 래스터."""
    lat_min = math.floor(lat.min() / _DENSITY_DLAT) * _DENSITY_DLAT
    lat_max = math.ceil(lat.max() / _DENSITY_DLAT) * _DENSITY_DLAT
    lon_min = math.floor(lon.min() / _DENSITY_DLON) * _DENSITY_DLON
    lon_max = math.ceil(lon.max() / _DENSITY_DLON) * _DENSITY_DLON
    nrows = int(round((lat_max - lat_min) / _DENSITY_DLAT))
    ncols = int(round((lon_max - lon_min) / _DENSITY_DLON))

    counts, _, _ = np.histogram2d(
        lat, lon,
        bins=[nrows, ncols],
        range=[[lat_min, lat_max], [lon_min, lon_max]],
    )
    counts = counts[::-1]  # 위도 오름차순 → 래스터(북→남) 순서

    mid_lat = math.radians((lat_min + lat_max) / 2)
    cell_km2 = (
        (_DENSITY_DLAT * lamps.KM_PER_DEG)
        * (_DENSITY_DLON * lamps.KM_PER_DEG * math.cos(mid_lat))
    )
    density = _blur(counts / cell_km2, _DENSITY_BLUR)

    rgba, upper = _log_raster(density, np.ones_like(density, dtype=bool))
    return {
        "id": "density",
        "name": "가로등 밀도",
        "url": _data_uri(rgba),
        "bounds": [[lat_min, lon_min], [lat_max, lon_max]],
        "legendTitle": "가로등 밀도 (로그)",
        "legendRows": _ramp_legend(upper, "개/km²"),
        "legendNote": (
            f"278m 격자 집계 후 반경 {_DENSITY_BLUR}칸(±약 550m) 평활. "
            "등이 하나도 없는 칸은 칠하지 않는다."
        ),
    }


# --- 점 레이어 ----------------------------------------------------------------

def _b64_int32(values: np.ndarray) -> str:
    """리틀엔디언 Int32 배열 → base64. JS 쪽 Int32Array 가 그대로 읽는다."""
    return base64.b64encode(values.astype("<i4").tobytes()).decode("ascii")


# --- 관측지 -------------------------------------------------------------------

def spot_rows() -> list[dict]:
    """관측지 20곳 + 그 지점의 어둡기 종합 판정(`core.darkness.assess_site`)."""
    spots = json.loads(path.SPOTS.read_text(encoding="utf-8"))["spots"]
    rows = []
    for spot in spots:
        site = darkness.assess_site(spot["lat"], spot["lon"])
        d, n, lamp = site.darkness, site.nightlight, site.lamps
        rows.append(
            {
                "name": spot["name_ko"],
                "region": spot["region"],
                "type": spot["type"],
                "lat": spot["lat"],
                "lon": spot["lon"],
                "why": spot["why"],
                "confidence": spot["coord_confidence"],
                "sqm": d.sqm if d else None,
                "falchi": d.falchi_grade if d else None,
                "bortle": d.bortle if d else None,
                "milkyWay": d.milky_way if d else None,
                "nearestM": lamp.nearest_m,
                "lampNear": lamp.near,
                "lampFar": lamp.far,
                "viirsNear": n.near_max if n else None,
                "score": site.score,
                "cap": site.cap,
            }
        )
    return rows


# --- HTML ---------------------------------------------------------------------

_HTML = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>제주 인공광 지도 — 가로등·광공해·관측지</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  :root {
    --panel: rgba(20, 20, 19, 0.88);
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --ink-muted: #898781;
    --hairline: rgba(255, 255, 255, 0.12);
  }
  html, body { margin: 0; height: 100%; background: #0d0d0d; }
  #map { position: absolute; inset: 0; background: #0d0d0d; }
  .leaflet-container {
    font: 13px/1.5 system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
    background: #0d0d0d;
  }
  /* 원본 해상도(30초각·15초각·278m)를 보간으로 감추지 않는다. */
  .raster { image-rendering: pixelated; }

  .panel {
    background: var(--panel);
    color: var(--ink);
    border: 1px solid var(--hairline);
    border-radius: 10px;
    padding: 12px 14px;
    backdrop-filter: blur(6px);
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
  }
  .title h1 {
    margin: 0 0 4px; font-size: 16px; font-weight: 600; letter-spacing: -0.01em;
  }
  .title p { margin: 0; font-size: 12px; color: var(--ink-2); max-width: 34ch; }
  .title .stats { margin-top: 10px; display: flex; gap: 18px; }
  .title .stat b { display: block; font-size: 20px; font-weight: 600; }
  .title .stat span { font-size: 11px; color: var(--ink-muted); }

  .legend { max-width: 280px; }
  .legend h2 { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: var(--ink); }
  .legend .row {
    display: flex; align-items: flex-start; gap: 8px; margin: 5px 0; font-size: 12px;
  }
  .legend .sw {
    flex: 0 0 auto; width: 14px; height: 14px; border-radius: 3px; margin-top: 1px;
  }
  .legend .sw.dot { border-radius: 50%; width: 10px; height: 10px; margin: 3px 2px 0; }
  .legend .lbl { color: var(--ink-2); }
  .legend .note { color: var(--ink-muted); font-size: 11px; }
  .legend .dim { opacity: 0.42; }
  .legend .foot {
    margin-top: 10px; padding-top: 9px; border-top: 1px solid var(--hairline);
    font-size: 11px; color: var(--ink-muted);
  }
  .legend + .legend { margin-top: 8px; }

  .leaflet-control-layers {
    background: var(--panel); color: var(--ink);
    border: 1px solid var(--hairline); border-radius: 10px;
  }
  .leaflet-control-layers-expanded { padding: 10px 12px; }
  .leaflet-control-layers label { font-size: 12px; }
  .leaflet-control-layers-separator { border-top: 1px solid var(--hairline); }
  .leaflet-control-attribution {
    background: rgba(13, 13, 13, 0.82) !important; color: var(--ink-muted) !important;
    font-size: 10px;
  }
  .leaflet-control-attribution a { color: var(--ink-2) !important; }
  .leaflet-control-scale-line {
    background: rgba(13, 13, 13, 0.7); color: var(--ink-2);
    border-color: var(--hairline);
  }
  .leaflet-popup-content-wrapper, .leaflet-popup-tip {
    background: #161615; color: var(--ink); border: 1px solid var(--hairline);
  }
  .leaflet-popup-content { margin: 12px 14px; font-size: 12px; line-height: 1.6; }
  .pop h3 { margin: 0 0 2px; font-size: 14px; }
  .pop .sub { color: var(--ink-muted); font-size: 11px; margin-bottom: 8px; }
  .pop dl { margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 2px 12px; }
  .pop dt { color: var(--ink-muted); }
  .pop dd { margin: 0; font-variant-numeric: tabular-nums; }
  .pop .why { margin: 8px 0 0; color: var(--ink-2); max-width: 30ch; }
  .sources {
    position: absolute; left: 12px; bottom: 12px; z-index: 800;
    max-width: 40ch; font-size: 10px; line-height: 1.5; color: var(--ink-muted);
  }
</style>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const DATA = /*__DATA__*/;

/* base64 → Int32Array (numpy 가 리틀엔디언으로 실어 보낸다). */
function decodeInt32(b64) {
  const bin = atob(b64), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Int32Array(bytes.buffer);
}

/* 위경도 → 웹 메르카토르 정규 좌표(0~1).
   한 번만 계산해 두고 그릴 때는 곱하기만 한다. */
function project(latE6, lonE6, scale) {
  const n = latE6.length, wx = new Float64Array(n), wy = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    wx[i] = (lonE6[i] / scale + 180) / 360;
    const s = Math.sin((latE6[i] / scale) * Math.PI / 180);
    wy[i] = 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
  }
  return { wx: wx, wy: wy, n: n };
}

/* 9만 개 점을 캔버스 한 장에 직접 찍는 레이어. 마커를 쓰면 DOM 이 못 버틴다. */
const DotLayer = L.Layer.extend({
  initialize: function (pts, options) {
    this._pts = pts;
    L.Util.setOptions(this, options);
  },
  onAdd: function (map) {
    this._map = map;
    this._canvas = L.DomUtil.create('canvas', 'leaflet-zoom-animated');
    this._canvas.style.pointerEvents = 'none';
    this.getPane().appendChild(this._canvas);
    map.on('moveend zoomend resize', this._reset, this);
    if (map.options.zoomAnimation && L.Browser.any3d) {
      map.on('zoomanim', this._zoomAnim, this);
    }
    this._reset();
  },
  onRemove: function (map) {
    map.off('moveend zoomend resize', this._reset, this);
    map.off('zoomanim', this._zoomAnim, this);
    L.DomUtil.remove(this._canvas);
  },
  _zoomAnim: function (e) {
    const scale = this._map.getZoomScale(e.zoom);
    const offset = this._map._getCenterOffset(e.center)._multiplyBy(-scale)
      .subtract(this._map._getMapPanePos());
    L.DomUtil.setTransform(this._canvas, offset, scale);
  },
  _reset: function () {
    const map = this._map, size = map.getSize();
    const topLeft = map.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setPosition(this._canvas, topLeft);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this._canvas.width = Math.round(size.x * dpr);
    this._canvas.height = Math.round(size.y * dpr);
    this._canvas.style.width = size.x + 'px';
    this._canvas.style.height = size.y + 'px';
    this._draw(dpr, topLeft, size);
  },
  _draw: function (dpr, topLeft, size) {
    const map = this._map, ctx = this._canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.x, size.y);

    const z = map.getZoom();
    const world = 256 * Math.pow(2, z);
    const origin = map.getPixelOrigin();
    const ox = origin.x + topLeft.x, oy = origin.y + topLeft.y;

    /* 줌이 낮으면 점이 서로 덮어써 밀도가 뭉개진다 — 작게·반투명하게 찍어 겹칠수록
       진해지게 두고, 확대하면 개체로 또렷해지게 키운다. */
    const r = z <= 10 ? 0.9 : z <= 12 ? 1.4 : z <= 14 ? 2.2 : z <= 16 ? 3.2 : 4.5;
    ctx.globalAlpha = z <= 11 ? 0.5 : z <= 14 ? 0.68 : 0.85;
    ctx.fillStyle = this.options.color;

    const wx = this._pts.wx, wy = this._pts.wy;
    ctx.beginPath();
    for (let i = 0; i < this._pts.n; i++) {
      const x = wx[i] * world - ox, y = wy[i] * world - oy;
      if (x < -8 || y < -8 || x > size.x + 8 || y > size.y + 8) continue;
      ctx.moveTo(x + r, y);
      ctx.arc(x, y, r, 0, 6.283185307179586);
    }
    ctx.fill();
  }
});

const map = L.map('map', { zoomControl: true })
  .setView(DATA.view.center, DATA.view.zoom);
L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

/* 쌓임 순서를 못 박는다: 타일(200) < 래스터 < 가로등 점 < 관측지(overlayPane 400).
   기본 pane 하나에 다 넣으면 추가 순서에 따라 래스터가 점을 덮는다. */
['rasterPane', 'lampPane'].forEach(function (name, i) {
  const pane = map.createPane(name);
  pane.style.zIndex = 300 + i * 50;
  pane.style.pointerEvents = 'none';
});

/* 베이스맵 둘 다 OSM 데이터 — 어두운 쪽(CARTO Dark Matter)이 광원 레이어와 대비가 커
   기본값이고, 지명·상호를 읽어야 할 때 표준 OSM 으로 바꾼다. */
const bases = {
  '어두운 지도 (OSM/CARTO)': L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    { maxZoom: 19, attribution: DATA.attribution }),
  '표준 OSM': L.tileLayer(
    'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    { maxZoom: 19, attribution: DATA.attribution })
};
bases['어두운 지도 (OSM/CARTO)'].addTo(map);

const overlays = {};
const legends = {};          // 레이어명 → 범례 DOM
const rasterNames = [];      // 한 번에 하나만 켜지는 래스터 레이어명

DATA.rasters.forEach(function (spec) {
  overlays[spec.name] = L.imageOverlay(spec.url, spec.bounds, {
    opacity: DATA.rasterOpacity, className: 'raster',
    pane: 'rasterPane', interactive: false
  });
  rasterNames.push(spec.name);
  legends[spec.name] = buildLegend(
    spec.legendTitle, spec.legendRows, spec.legendNote, false);
});

const lampSpec = DATA.lampLayer;
overlays[lampSpec.name] = new DotLayer(
  project(decodeInt32(lampSpec.lat), decodeInt32(lampSpec.lon), DATA.coordScale),
  { color: lampSpec.color, pane: 'lampPane' }
);
legends[lampSpec.name] = buildLegend(
  '가로등·보안등',
  [{ swatch: lampSpec.color, label: lampSpec.name, note: '', dim: false }],
  '점 하나가 등 하나. 확대할수록 개체로 또렷해진다.',
  true
);

const spotName = '관측지 ' + DATA.spots.length + '곳';
overlays[spotName] = L.layerGroup(DATA.spots.map(function (s) {
  const m = L.circleMarker([s.lat, s.lon], {
    radius: 6, color: '#ffffff', weight: 2, fillColor: '#0d0d0d', fillOpacity: 0.85
  });
  m.bindPopup(popupHtml(s), { maxWidth: 320 });
  m.bindTooltip(s.name, { direction: 'top', offset: [0, -8] });
  return m;
}));

function popupHtml(s) {
  const milky = { visible: '보임', degraded: '흐릿함', lost: '보기 어려움' };
  const rows = [
    ['종합 점수', s.score !== null ? s.score.toFixed(3) + ' · ' + s.cap : '격자 밖'],
    ['하늘 밝기', s.sqm !== null ? s.sqm.toFixed(2) + ' SQM' : '—'],
    ['광공해 등급', s.falchi ? 'Falchi ' + s.falchi + ' · Bortle ' + s.bortle : '—'],
    ['은하수', milky[s.milkyWay] || '—'],
    ['최근접 가로등',
      s.nearestM !== null ? s.nearestM.toFixed(0) + ' m' : '1km 안에 없음'],
    ['가로등 100m / 1km', s.lampNear + ' / ' + s.lampFar + '개'],
    ['야간광 1km 최대', s.viirsNear !== null ? s.viirsNear.toFixed(2) : '—']
  ];
  return '<div class="pop"><h3>' + s.name + '</h3>'
    + '<div class="sub">' + s.region + ' · ' + s.type
    + ' · 좌표 신뢰도 ' + s.confidence + '</div>'
    + '<dl>' + rows.map(function (r) {
        return '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>';
      }).join('') + '</dl>'
    + '<p class="why">' + s.why + '</p></div>';
}

function buildLegend(title, rows, note, dots) {
  const el = L.DomUtil.create('div', 'panel legend');
  el.innerHTML = '<h2>' + title + '</h2>' + rows.map(function (r) {
    return '<div class="row' + (r.dim ? ' dim' : '') + '">'
      + '<span class="sw' + (dots ? ' dot' : '')
      + '" style="background:' + r.swatch + '"></span>'
      + '<span><span class="lbl">' + r.label + '</span>'
      + (r.note ? '<br><span class="note">' + r.note + '</span>' : '')
      + '</span></div>';
  }).join('') + (note ? '<div class="foot">' + note + '</div>' : '');
  return el;
}

const legendBox = L.control({ position: 'bottomright' });
legendBox.onAdd = function () {
  const wrap = L.DomUtil.create('div');
  L.DomEvent.disableClickPropagation(wrap);
  this._wrap = wrap;
  return wrap;
};
legendBox.addTo(map);

function refreshLegend() {
  const wrap = legendBox._wrap;
  wrap.innerHTML = '';
  rasterNames.concat([lampSpec.name]).forEach(function (name) {
    if (map.hasLayer(overlays[name])) wrap.appendChild(legends[name]);
  });
}

/* 래스터를 겹치면 서로를 가리기만 하므로 한 번에 하나만 남긴다. */
map.on('overlayadd', function (e) {
  if (rasterNames.indexOf(e.name) !== -1) {
    rasterNames.forEach(function (name) {
      if (name !== e.name && map.hasLayer(overlays[name])) {
        map.removeLayer(overlays[name]);
      }
    });
  }
  refreshLegend();
});
map.on('overlayremove', refreshLegend);

L.control.layers(bases, overlays, { collapsed: false, position: 'topright' })
  .addTo(map);

const title = L.control({ position: 'topleft' });
title.onAdd = function () {
  const el = L.DomUtil.create('div', 'panel title');
  L.DomEvent.disableClickPropagation(el);
  el.innerHTML = '<h1>' + DATA.title + '</h1><p>' + DATA.subtitle + '</p>'
    + '<div class="stats">' + DATA.stats.map(function (s) {
        return '<div class="stat"><b>' + s.value + '</b>'
          + '<span>' + s.label + '</span></div>';
      }).join('') + '</div>';
  return el;
};
title.addTo(map);

const sources = document.createElement('div');
sources.className = 'sources';
sources.innerHTML = DATA.sources.join('<br>');
document.body.appendChild(sources);

DATA.initial.forEach(function (name) {
  if (overlays[name]) overlays[name].addTo(map);
});
refreshLegend();
</script>
"""


def render(payload: dict) -> str:
    """페이로드를 HTML 골격에 주입한다(중괄호 충돌이 없도록 치환만 쓴다)."""
    return _HTML.replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False))


def main() -> None:
    lat, lon = lamps.points()
    rasters = [_density_layer(lat, lon), _falchi_layer(), _viirs_layer()]
    spots = spot_rows()
    spot_name = f"관측지 {len(spots)}곳"

    payload = {
        "title": "제주 인공광 지도",
        "subtitle": (
            f"가로등 {lamps.COUNT:,}개와 위성 광공해 관측을 한 장에 겹쳐, "
            "'제주에서 별이 보이는 곳'이 어디인지 눈으로 확인한다."
        ),
        "stats": [
            {"value": f"{lamps.COUNT:,}", "label": "가로등·보안등"},
            {"value": f"{len(spots)}", "label": "큐레이션 관측지"},
            {"value": "3", "label": "광공해 신호"},
        ],
        "view": {"center": [33.38, 126.55], "zoom": 10},
        "attribution": _ATTRIBUTION,
        "sources": [darkness.SOURCE, nightlight.SOURCE, lamps.SOURCE],
        "rasterOpacity": _RASTER_OPACITY,
        "coordScale": _COORD_SCALE,
        "rasters": rasters,
        "lampLayer": {
            "name": f"가로등 ({lamps.COUNT:,}개)",
            "color": _LAMP_COLOR,
            "lat": _b64_int32(np.rint(lat * _COORD_SCALE)),
            "lon": _b64_int32(np.rint(lon * _COORD_SCALE)),
        },
        "spots": spots,
        "initial": [rasters[0]["name"], spot_name],
    }

    path.OUTPUTS.mkdir(parents=True, exist_ok=True)
    path.LIGHT_MAP.write_text(render(payload), encoding="utf-8")

    print(f"가로등: {lamps.COUNT:,}개 (core.lamps 교정·범위 적용 후)")
    for spec in rasters:
        print(f"래스터 {spec['name']}: {len(spec['url']) // 1024}KB (base64 data URI)")
    print(f"관측지: {len(spots)}곳")
    print(f"저장: {path.LIGHT_MAP.relative_to(path.ROOT)} "
          f"({path.LIGHT_MAP.stat().st_size / 1_048_576:.2f} MB)")


if __name__ == "__main__":
    main()
