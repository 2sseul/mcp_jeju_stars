"""VIIRS 야간광 GeoTIFF → 런타임용 격자(npz) 전처리 (연 1회, 오프라인).

`build_darkness_grid.py` 와 같은 규율이다 — 원본 .tif 를 **한 번** 읽어 복사휘도 격자와
좌표 아핀만 뽑아 두고, 런타임(`core/nightlight.py`)은 numpy 로 그 파일만 읽는다.
tifffile·imagecodecs·GDAL 의존이 서버에 남지 않는다.

두 래스터는 **해상도가 다르다**(SB 30초각 vs VIIRS 15초각). 격자를 하나로 합치지 않고
따로 두는 이유는 쓰임이 다르기 때문이다 — SB 는 좌표 1픽셀 조회("여기 하늘이 어두운가"),
VIIRS 는 반경 1·3km 집계("근처에 밝은 광원이 있는가"). 재샘플링해 맞추면 없는 정밀도가
생긴 것처럼 보이므로 원 해상도를 유지한다.

실행(전처리 의존은 커밋하지 않고 임시로 끌어온다):
    uv run --with tifffile --with imagecodecs python -m scripts.build_viirs_grid

입력  : data/light_pollution/jeju_2025_viirs_npp.tif  (복사휘도 nW·cm⁻²·sr⁻¹, LZW)
출력  : data/light_pollution/jeju_viirs_grid.npz
        grid   : float32 (nrows, ncols)  — 복사휘도, 결측은 nodata
        affine : float64 [origin_lon, origin_lat, scale_deg, nodata]
                 origin = 좌상단 픽셀의 '모서리'(GeoTIFF RasterPixel.IsArea)
        source : 귀속 문자열
"""

from __future__ import annotations

import numpy as np
import tifffile

from server import path

_SRC = path.VIIRS_RAW
_OUT = path.VIIRS_GRID

# 검증(star_research.md 야간광 절)과 대조할 기대 사양·통계.
_EXPECT_SHAPE = (260, 311)
_EXPECT_SCALE = 0.004166666666666667  # 15초각
_EXPECT_ZERO_RATIO = 0.719  # 유효 픽셀의 71.9% 가 정확히 0
_EXPECT_SUBTHRESHOLD = 3864  # 0 < v < 0.5 구간 픽셀 수(재샘플링 파생물 근거)

_SOURCE = (
    "야간광: NASA's Black Marble nighttime lights product (VNP46A4) 연간 합성 "
    "복사휘도 (nW·cm⁻²·sr⁻¹, 2025). 근거리 광원 탐지 전용 — 유효 픽셀의 71.9%가 "
    "0 이라 어두운 곳끼리는 구별하지 못하므로 픽셀 절댓값을 판정에 쓰지 않는다."
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

    assert abs(scale_lon - scale_lat) < 1e-12, "경위도 픽셀 크기가 다르면 아핀이 깨진다"
    assert grid.shape == _EXPECT_SHAPE, f"격자 {grid.shape} != {_EXPECT_SHAPE}"
    assert abs(scale_lon - _EXPECT_SCALE) < 1e-9, f"픽셀 크기 {scale_lon} != 15초각"

    affine = np.array([origin_lon, origin_lat, scale_lon, nodata], dtype=np.float64)

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(_OUT, grid=grid, affine=affine, source=np.array(_SOURCE))

    # nodata 는 부동소수라 근사로 거른다(-999.9 가 float32 로 안 떨어짐).
    valid = grid[np.abs(grid - nodata) > 1e-3].astype(np.float64)
    zero_ratio = float((valid == 0).sum()) / valid.size
    sub = int(((valid > 0) & (valid < 0.5)).sum())

    print(f"입력: {_SRC.name}  shape={grid.shape}  scale={scale_lon:.8f}°")
    print(f"원점(좌상단 모서리): lon={origin_lon}, lat={origin_lat}  nodata={nodata}")
    print(f"유효 픽셀: {valid.size} / {grid.size}")
    print(f"복사휘도: min={valid.min():.4f} p50={np.median(valid):.4f} "
          f"p99={np.percentile(valid, 99):.2f} max={valid.max():.2f}")
    print(f"정확히 0: {(valid == 0).sum()} ({zero_ratio:.1%})  [기대 ~71.9%]")
    print(f"0 < v < 0.5: {sub}  [기대 {_EXPECT_SUBTHRESHOLD}]")

    # 문서의 두 근거 수치를 재현하는지 확인한다.
    #   ① 71.9% 제로 — Black Marble 이 0.5 미만 복사휘도를 0 으로 두는 처리(User Guide)
    #   ② 0<v<0.5 구간 존재 — 임계가 살아 있는 원본이면 비어야 하므로, 보유 파일은
    #      재샘플링 파생물. 이것이 "픽셀 절댓값 불신·방위 집계 전용" 원칙의 근거다.
    assert abs(zero_ratio - _EXPECT_ZERO_RATIO) < 0.005, f"제로 비율 {zero_ratio:.3f}"
    assert sub == _EXPECT_SUBTHRESHOLD, f"0<v<0.5 픽셀 {sub}"
    assert (valid >= 0).all(), "유효 픽셀에 음수 복사휘도가 있으면 전제가 깨진다"

    print(f"저장: {_OUT.relative_to(path.ROOT)}  ({_OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
