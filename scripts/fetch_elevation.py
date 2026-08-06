"""관측지 해발높이·경사도를 채운다 (배치, 다시 돌려도 안전).

둘 다 사람이 손으로 적을 값이 아니다 — 지형은 좌표만 있으면 정해진다. 그런데
저장소에는 수치표고모델(DEM)이 없고, 판정 경로는 실행 중에 외부를 부르지 않는다
(`decisions.md` §2.10). 그래서 화장실 좌표와 같은 방식으로 **배치에서 받아
데이터 파일에 적어 둔다**.

무엇을 재는가 — 정상 높이가 아니다
--------------------------------------------------------------------------
    elevation_m  그 **좌표 지점**의 해발높이(m)
    slope_deg    그 지점 주변 90m 격자의 경사(도)

오름의 공표 표고(용눈이 247.8m 같은)와는 다른 값이다. 관측지 좌표는 대개 정상이
아니라 주차장·초입이고, DEM 격자가 90m 라 좁은 봉우리는 주변과 섞여 낮게 나온다.
실제로 큐레이션 9곳을 공표값과 대 보면 **30~75m 낮게** 나온다.

그래도 이 값이 맞는 값이다 — 화면과 추천이 말하는 것은 "정상이 얼마나 높은가"가
아니라 **"차를 세우고 서 있을 그 자리가 어떤 지형인가"**이기 때문이다. 경사도는
삼각대를 세울 만한지·주차 자리가 비탈인지를 가른다.

경사는 중앙차분으로 낸다 — 동/서·남/북 90m 이웃 넷을 받아

    tan(경사) = √( ((E-W)/2d)² + ((N-S)/2d)² )

DEM 격자 한 칸(90m)을 그대로 d 로 쓴다. 그보다 촘촘히 물어도 같은 격자를 여러 번
읽는 것이라 없는 정밀도가 생길 뿐이다.

출처
--------------------------------------------------------------------------
Open-Meteo Elevation API — Copernicus DEM GLO-90 (90m). 키가 필요 없고 판정
경로가 아닌 배치에서만 부른다.

실행:
    uv run python -m scripts.fetch_elevation          # 비어 있는 곳만
    uv run python -m scripts.fetch_elevation --all    # 좌표를 옮겼을 때 전부 다시
"""

from __future__ import annotations

import json
import math
import sys

import requests

from server import path
from server.core import lamps

_URL = "https://api.open-meteo.com/v1/elevation"

#: 채우는 두 칸. `scripts/edit_spots.py` 의 컬럼 키와 같아야 한다.
ELEVATION_KEY = "elevation_m"
SLOPE_KEY = "slope_deg"

#: 이웃까지의 거리(m) = DEM 격자 한 칸. 경사의 공간 규모가 곧 이 값이다.
CELL_M = 90.0

#: 한 요청에 담을 좌표 수. API 상한이 100 이라 관측지 20곳(=100점)씩 끊는다.
_SPOTS_PER_REQUEST = 20

#: 한 관측지가 쓰는 점 다섯 — 가운데·서·동·남·북. 순서가 곧 응답 순서다.
_POINTS = 5

_TIMEOUT = 30.0


def ring(lat: float, lon: float) -> list[tuple[float, float]]:
    """가운데와 네 이웃(서·동·남·북) 좌표. 이웃은 CELL_M 만큼 떨어진다."""
    dlat = CELL_M / (lamps.KM_PER_DEG * 1000.0)
    dlon = CELL_M / (lamps.KM_PER_DEG * 1000.0 * math.cos(math.radians(lat)))
    return [
        (lat, lon),
        (lat, lon - dlon),
        (lat, lon + dlon),
        (lat - dlat, lon),
        (lat + dlat, lon),
    ]


def slope_deg(west: float, east: float, south: float, north: float) -> float:
    """네 이웃의 높이 → 경사(도). 중앙차분."""
    dz_dx = (east - west) / (2 * CELL_M)
    dz_dy = (north - south) / (2 * CELL_M)
    return math.degrees(math.atan(math.hypot(dz_dx, dz_dy)))


def fetch(points: list[tuple[float, float]]) -> list[float]:
    """좌표 목록 → 해발높이 목록. 순서는 그대로 유지된다."""
    response = requests.get(
        _URL,
        params={
            "latitude": ",".join(f"{lat:.6f}" for lat, _ in points),
            "longitude": ",".join(f"{lon:.6f}" for _, lon in points),
        },
        timeout=_TIMEOUT,
    )
    if response.status_code != 200:
        raise SystemExit(
            f"Open-Meteo Elevation {response.status_code}: {response.text[:200]}"
        )
    elevations = response.json().get("elevation")
    if not isinstance(elevations, list) or len(elevations) != len(points):
        raise SystemExit(
            f"응답이 좌표 수({len(points)})와 맞지 않습니다: {str(elevations)[:200]}"
        )
    return [float(value) for value in elevations]


def main() -> None:
    refresh = "--all" in sys.argv[1:]
    doc = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    spots = doc["spots"]

    todo = [
        spot for spot in spots
        if refresh or spot.get(ELEVATION_KEY) is None or spot.get(SLOPE_KEY) is None
    ]
    print(f"관측지 {len(spots):,}곳 — 채울 곳 {len(todo):,}"
          + (" (--all: 전부 다시)" if refresh else ""))
    if not todo:
        print("채울 것이 없습니다. 좌표를 옮겼다면 --all 로 다시 받으세요.")
        return

    changed = 0
    for start in range(0, len(todo), _SPOTS_PER_REQUEST):
        chunk = todo[start:start + _SPOTS_PER_REQUEST]
        points = [point for spot in chunk for point in ring(spot["lat"], spot["lon"])]
        heights = fetch(points)

        for i, spot in enumerate(chunk):
            centre, west, east, south, north = heights[i * _POINTS:(i + 1) * _POINTS]
            before = (spot.get(ELEVATION_KEY), spot.get(SLOPE_KEY))
            spot[ELEVATION_KEY] = round(centre)
            spot[SLOPE_KEY] = round(slope_deg(west, east, south, north), 1)
            if before != (spot[ELEVATION_KEY], spot[SLOPE_KEY]):
                changed += 1
        print(f"  {min(start + len(chunk), len(todo)):,}/{len(todo):,}", flush=True)

    tmp = path.SPOTS.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path.SPOTS)

    filled = [s for s in spots if s.get(ELEVATION_KEY) is not None]
    highest = max(filled, key=lambda s: s[ELEVATION_KEY])
    steepest = max(filled, key=lambda s: s[SLOPE_KEY])
    print(f"\n{path.SPOTS.relative_to(path.ROOT)} — "
          f"{len(filled):,}/{len(spots):,}곳 채움 (바뀐 값 {changed:,})")
    print(f"  가장 높은 곳  {highest['name_ko']} {highest[ELEVATION_KEY]:,} m")
    print(f"  가장 가파른 곳 {steepest['name_ko']} {steepest[SLOPE_KEY]:.1f}°")
    print("  공표 표고가 아니라 **그 좌표 지점**의 값이다 "
          "(DEM 90m — 정상은 30~75m 높게 나온다).")


if __name__ == "__main__":
    main()
