"""FABDEM 타일 → 제주 표고 격자 (전처리, 다시 돌려도 안전).

도보 경로가 얼마나 오르는지는 좌표만으로 정해진다. 그 값을 배치가 API 를 부를 때마다
받아 오면 판정 경로 밖이라도 외부에 매여 있으므로(`decisions.md` §2.10), 다른
래스터들과 같은 방식으로 **한 번 받아 잘라서 파일로 둔다**(`build_darkness_grid.py`).

**맨땅이어야 한다 (DSM 이 아니라 DTM)**
--------------------------------------------------------------------------
Copernicus GLO-30·SRTM·ASTER 는 전부 **DSM** 이라 수관·건물 높이가 표고에 섞인다.
숲길 오름에서는 사람이 나무를 밟고 걷는 것으로 계산된다. 제주 육지 2,665점에서
GLO-30 과 FABDEM 을 대 보면:

    DSM - DTM   평균 +3.76m · 중앙 +2.26m · p90 +9.99m · 최대 +17.9m
                1m 넘게 차이나는 곳 67.3% · 5m 넘는 곳 31.7%

**제주 육지의 3분의 2가 부풀어 있다.** 검증에 쓰던 용눈이가 하필 초지 오름이라
(수관 평균 +0.2m) 이 문제가 안 드러났었다 — 절물·사려니처럼 숲에 든 오름이었으면
바로 보였을 것이다.

FABDEM 은 GLO-30 에서 나무와 건물을 걷어낸 것이라 격자도 1초각으로 같고, 같은
용눈이 경로에서 가짜 내리막이 5개 → 3개로 준다.

라이선스 — 이 격자는 커밋하지 않는다
--------------------------------------------------------------------------
FABDEM 은 **CC BY-NC-SA 4.0**(비상업·동일조건변경허락)이다. 재배포하면 파생물도 같은
조건에 묶이므로 원본 tif 도, 여기서 만든 npz 도 `.gitignore` 에 둔다 —
`data/elevation/` 전체가 대상이다. 저장소가 나르는 것은 **이 스크립트**뿐이고,
받은 사람이 한 번 돌리면 된다.

담는 것
--------------------------------------------------------------------------
제주만 잘라 **데시미터 단위 int16** 으로 담는다. 원본이 float32 인데 그 정밀도는
DEM 자신의 오차보다 한참 아래라 의미가 없고, int16 이면 파일이 절반이다.

바다는 원본이 0.0 으로 채워 둔다(결측이 아니다). 그대로 둔다 — 해안 관측지의 표고가
실제로 0m 근처라 둘을 갈라 놓을 방법도, 갈라야 할 이유도 없다.

원본 타일
--------------------------------------------------------------------------
제주는 1도 x 1도 타일 **한 장**에 다 든다(N33E126 이 위도 33~34 · 경도 126~127 을
덮고, 제주는 33.19~33.56 · 126.15~126.97). 4.8MB.

    원본  https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn
    미러  huggingface.co/datasets/links-ads/fabdem-v12 (타일 낱개로 받을 수 있다)

원본 저장소는 10도 x 10도 zip 으로만 주므로 타일 하나를 받으려고 수 GB 를 내려받게
된다. 그래서 미러에서 낱개로 받는다.

실행:
    uv run --with tifffile --with imagecodecs python -m scripts.build_elevation_grid
"""

from __future__ import annotations

import urllib.request

import numpy as np
import tifffile

from server import path

#: 제주가 드는 1도 x 1도 타일.
TILE = "N33E126_FABDEM_V1-2"
URL = (
    "https://huggingface.co/datasets/links-ads/fabdem-v12/resolve/main"
    f"/tiles/N30E120-N40E130_FABDEM_V1-2/{TILE}.tif"
)

#: 잘라 담을 범위. `data/jeju_spots.json` 의 `meta.jeju_bounds` 에 여유를 준 값 —
#: 관측지 자체는 그 안이지만 도보 경로·주차 지점이 조금 밖으로 나갈 수 있다.
#: 경도 상한은 타일 끝(127.0)을 넘지 않는다.
BOUNDS = {"lat_min": 33.15, "lat_max": 33.60, "lon_min": 126.10, "lon_max": 127.00}

#: 결측 표시(데시미터). 원본은 -9999 로 적어 두는데 제주 타일에는 실제로 없다.
NODATA = np.iinfo(np.int16).min
_SRC_NODATA = -9000.0

#: 1초각. 이 값이 아니면 타일이 우리가 아는 그것이 아니다.
_EXPECT_SCALE = 1 / 3600

SOURCE = (
    "FABDEM V1-2 (Forest And Buildings removed Copernicus DEM, 1초각 ~30m) — "
    "Hawker et al. 2022, Environ. Res. Lett. · University of Bristol / Fathom · "
    "CC BY-NC-SA 4.0. 기반: Copernicus DEM GLO-30 (ESA / Airbus)"
)


def _fetch(dest) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"타일 내려받는 중 (약 5MB) — {URL}")
    urllib.request.urlretrieve(URL, dest)


def main() -> None:
    raw = path.DEM_RAW
    if not raw.exists():
        _fetch(raw)

    with tifffile.TiffFile(raw) as tf:
        page = tf.pages[0]
        tags = {t.name: t.value for t in page.tags.values()}
        grid = page.asarray()
        scale_lon, scale_lat = tags["ModelPixelScaleTag"][:2]
        tie = tags["ModelTiepointTag"]
        lon0, lat0 = float(tie[3]), float(tie[4])

    assert abs(scale_lon - scale_lat) < 1e-15, "경위도 픽셀 크기가 다르면 아핀이 깨진다"
    assert abs(scale_lon - _EXPECT_SCALE) < 1e-12, f"픽셀 {scale_lon} != 1초각"

    # 위쪽(북쪽)이 0행이다. 자를 행·열을 범위에서 바로 낸다.
    row0 = int((lat0 - BOUNDS["lat_max"]) / scale_lat)
    row1 = int(np.ceil((lat0 - BOUNDS["lat_min"]) / scale_lat))
    col0 = int((BOUNDS["lon_min"] - lon0) / scale_lon)
    col1 = int(np.ceil((BOUNDS["lon_max"] - lon0) / scale_lon))
    cut = grid[row0:row1, col0:col1].astype(np.float64)

    # 잘린 조각의 좌상단 좌표. 조회는 이 둘과 픽셀 크기만 있으면 된다.
    top = lat0 - row0 * scale_lat
    left = lon0 + col0 * scale_lon

    missing = cut <= _SRC_NODATA
    decimetres = np.where(missing, NODATA, np.rint(cut * 10)).astype(np.int16)

    path.DEM_GRID.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path.DEM_GRID,
        elevation_dm=decimetres,
        top=top, left=left, scale=scale_lon,
        nodata=NODATA, source=SOURCE,
    )

    good = decimetres[decimetres != NODATA] / 10
    land = good[good > 0]
    size = path.DEM_GRID.stat().st_size / 1024 / 1024
    print(f"격자 {decimetres.shape} · 1초각(~30m) → "
          f"{path.DEM_GRID.relative_to(path.ROOT)} ({size:.1f} MB)")
    print(f"  덮는 범위 lat {top - decimetres.shape[0] * scale_lat:.4f}~{top:.4f} · "
          f"lon {left:.4f}~{left + decimetres.shape[1] * scale_lon:.4f}")
    print(f"  결측 {int(missing.sum()):,} · 표고 0 초과 화소 {land.size:,} "
          f"({100 * land.size / decimetres.size:.1f}%, 나머지는 바다) · "
          f"최고 {good.max():.1f}m")
    print(f"  출처: {SOURCE}")
    print("  한라산 정상 1,947m 근처가 최고로 나와야 맞다"
          " (격자 30m 라 봉우리는 깎인다).")
    print("  이 격자는 CC BY-NC-SA 라 커밋하지 않는다"
          " — data/elevation/ 은 gitignore 다.")


if __name__ == "__main__":
    main()
