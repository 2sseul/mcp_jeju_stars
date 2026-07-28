"""SB(Sky Brightness) GeoTIFF → 런타임용 격자(npz) 전처리 (연 1회, 오프라인).

광공해 래스터는 T0 정적 데이터(도시 확장·가로등은 수년 단위)라 실행 때마다 GeoTIFF 를
디코딩할 이유가 없다. 이 스크립트가 원본 .tif 를 **한 번** 읽어 인공 밝기 격자와 좌표
아핀만 뽑아 `data/darkness/jeju_sb_grid.npz` 로 저장한다. 런타임(darkness.py)은 numpy
로 이 파일만 읽으므로 tifffile·imagecodecs·GDAL 의존이 서버에 남지 않는다
(star_research.md: "MCP 서버 컨테이너는 배치 결과 파일을 읽기만 한다").

실행(전처리 의존은 커밋하지 않고 임시로 끌어온다):
    uv run --with tifffile --with imagecodecs python data/script/build_darkness_grid.py

입력  : data/raw/jeju_2025_GeoTIFF_raw.tif  (= sb_202500, 인공 밝기 mcd/m², LZW)
출력  : data/darkness/jeju_sb_grid.npz
        grid   : float32 (nrows, ncols)  — 인공 밝기 mcd/m², 결측은 nodata
        affine : float64 [origin_lon, origin_lat, scale_deg, nodata]
                 origin = 좌상단 픽셀의 '모서리'(GeoTIFF RasterPixel.IsArea)
        source : 귀속 문자열
"""

from __future__ import annotations

import json

import numpy as np
import tifffile

from server import path

_SRC = path.SB_RAW
_OUT = path.SB_GRID
_OUT_DIR = _OUT.parent

# 검증(star_research_validation.md [A-추가])과 대조할 기대 사양·통계.
_EXPECT_SHAPE = (98, 118)
_EXPECT_SCALE = 0.008333333333333333
_SOURCE = (
    "광공해(Sky Brightness): NASA Black Marble (VNP46A4/VJ146A4) 기반, "
    "lightpollutionmap.info 산출 레이어 (sb_2025). "
    "영점 1.08e8 mcd/m² · 자연 밤하늘 22.00 mag/arcsec² 규약."
)


def main() -> None:
    with tifffile.TiffFile(_SRC) as tf:
        page = tf.pages[0]
        grid = page.asarray().astype(np.float32)
        tags = {t.name: t.value for t in page.tags}
        scale_lon, scale_lat = tags["ModelPixelScaleTag"][:2]
        # ModelTiepoint: (i, j, k, X, Y, Z) — 래스터 (i,j)=(0,0) 이 지리좌표 (X,Y).
        _, _, _, origin_lon, origin_lat, _ = tags["ModelTiepointTag"][:6]
        nodata = float(tags.get("GDAL_NODATA", -999.9))

    assert abs(scale_lon - scale_lat) < 1e-12, "경위도 픽셀 크기가 다르면 아핀 가정이 깨진다"
    assert grid.shape == _EXPECT_SHAPE, f"격자 크기 {grid.shape} != 기대 {_EXPECT_SHAPE}"
    assert abs(scale_lon - _EXPECT_SCALE) < 1e-9, f"픽셀 크기 {scale_lon} != 30초각"

    affine = np.array([origin_lon, origin_lat, scale_lon, nodata], dtype=np.float64)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(_OUT, grid=grid, affine=affine, source=np.array(_SOURCE))

    valid = grid[grid != nodata]
    print(f"입력: {_SRC.name}  shape={grid.shape}  scale={scale_lon:.8f}°")
    print(f"원점(좌상단 모서리): lon={origin_lon}, lat={origin_lat}  nodata={nodata}")
    print(f"인공 밝기(mcd/m²): min={valid.min():.4f} p50={np.median(valid):.4f} "
          f"max={valid.max():.4f}")
    print(f"저장: {_OUT.relative_to(path.ROOT)}  ({_OUT.stat().st_size} bytes)")

    # star_research_validation.md 와 교차 검증: SQM 분포가 재현되는지.
    art = valid.astype(np.float64)
    sqm = np.log10((art + 0.171168465) / 1.08e8) / -0.4
    print(f"환산 SQM: min={sqm.min():.2f} p25={np.percentile(sqm, 25):.2f} "
          f"p50={np.median(sqm):.2f} p95={np.percentile(sqm, 95):.2f} max={sqm.max():.2f}")
    print(json.dumps({"expected": "min19.14 p25~21.12 p50~21.50 p95~21.86 max21.93"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
