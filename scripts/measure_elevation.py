"""관측지 해발높이·경사도를 표고 격자에서 잰다 (배치, 다시 돌려도 안전).

둘 다 사람이 손으로 적을 값이 아니다 — 지형은 좌표만 있으면 정해진다.

무엇을 재는가 — 정상 높이가 아니다
--------------------------------------------------------------------------
    elevation_m  그 **좌표 지점**의 해발높이(m)
    slope_deg    그 지점 주변 90m 격자의 경사(도)

오름의 공표 표고(용눈이 247.8m 같은)와는 다른 값이다. 관측지 좌표는 대개 정상이
아니라 주차장·초입이고, 정상에 찍혀 있어도 좁은 봉우리는 격자에서 주변과 섞인다.

그래도 이 값이 맞는 값이다 — 화면과 추천이 말하는 것은 "정상이 얼마나 높은가"가
아니라 **"차를 세우고 서 있을 그 자리가 어떤 지형인가"**이기 때문이다. 경사도는
삼각대를 세울 만한지·주차 자리가 비탈인지를 가른다.

어디서 읽는가
--------------------------------------------------------------------------
`server/core/elevation.py` 의 FABDEM 격자(1초각 ~30m, **맨땅**)다. 도보 경로가
쓰는 것과 같은 격자다 — 한 관측지의 표고를 두 격자에서 읽으면 관측지 좌표의
해발높이와 그 관측지 경로의 고도차가 서로 어긋난다(`decisions.md` §2.20).

한때 Open-Meteo Elevation(Copernicus GLO-90)을 배치로 받았다. 그쪽은 수관·건물
높이가 섞인 DSM 이고, 제주 육지의 3분의 2가 1m 이상 부풀어 있다(§2.17).

왜 배치가 아직 있나
--------------------------------------------------------------------------
`edit_spots.py` 는 저장할 때 그 자리에서 다시 재므로, 사람이 옮긴 좌표는 이 배치를
안 불러도 맞다. 그런데 관측지를 만드는 길이 편집기만은 아니다 —
`merge_upland_parking.py`·`merge_swept_spots.py` 가 붙인 항목은 아직 빈 채로 들어온다.

**늘 전부 다시 잰다.** 예전에는 값이 빈 곳만 채우고 `--all` 을 붙여야 다시 쟀는데,
좌표를 옮겨 놓고 그 명령을 안 부르면 값이 옛 자리에 남았다 — 실제로 120곳 중 27곳이
그렇게 어긋나 있었다(2026-08-13). 격자를 읽는 데 드는 시간은 이 목록 전체에 한
호흡이라 나눌 이유가 없다.

실행:
    uv run python -m scripts.measure_elevation
"""

from __future__ import annotations

import json

from server import path
from server.core import elevation

#: 채우는 두 칸. `scripts/edit_spots.py` 의 컬럼 키와 같아야 한다.
ELEVATION_KEY = "elevation_m"
SLOPE_KEY = "slope_deg"


def measure_site(spot: dict) -> None:
    """관측지 하나의 두 칸을 격자에서 다시 잰다. `edit_spots` 도 이것을 부른다.

    못 재면(격자 밖) **키를 지운다** — 이 파일의 규약대로 없는 키가 곧 '모른다'이고,
    0 으로 채우면 '해수면의 평지'로 읽힌다.

    있는 키는 자리를 지킨 채 값만 바꾼다(지웠다 다시 넣지 않는다) — 그래야 저장할
    때 diff 가 고친 줄에만 난다.
    """
    height = elevation.at(spot["lat"], spot["lon"])
    slope = elevation.slope_at(spot["lat"], spot["lon"])

    if height is None:
        spot.pop(ELEVATION_KEY, None)
    else:
        spot[ELEVATION_KEY] = round(height)
    if slope is None:
        spot.pop(SLOPE_KEY, None)
    else:
        spot[SLOPE_KEY] = slope


def main() -> None:
    doc = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    spots = doc["spots"]

    changed, blank = [], []
    for spot in spots:
        before = (spot.get(ELEVATION_KEY), spot.get(SLOPE_KEY))
        measure_site(spot)
        after = (spot.get(ELEVATION_KEY), spot.get(SLOPE_KEY))
        if after != before:
            changed.append((spot["name_ko"], before, after))
        if None in after:
            blank.append(spot["name_ko"])

    tmp = path.SPOTS.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path.SPOTS)

    print(f"관측지 {len(spots):,}곳 — 바뀐 값 {len(changed):,}곳")
    for name, before, after in changed:
        print(f"  {name:<24} {_fmt(before)} → {_fmt(after)}")
    if blank:
        print(f"\n표고 격자 밖이라 못 잰 곳 {len(blank):,}: {'·'.join(blank)}")

    filled = [s for s in spots if s.get(ELEVATION_KEY) is not None]
    if filled:
        highest = max(filled, key=lambda s: s[ELEVATION_KEY])
        steepest = max(filled, key=lambda s: s[SLOPE_KEY])
        print(f"\n{path.SPOTS.relative_to(path.ROOT)} — "
              f"{len(filled):,}/{len(spots):,}곳 잼 ({elevation.SOURCE})")
        print(f"  가장 높은 곳  {highest['name_ko']} {highest[ELEVATION_KEY]:,} m")
        print(f"  가장 가파른 곳 {steepest['name_ko']} {steepest[SLOPE_KEY]:.1f}°")
    print("  공표 표고가 아니라 **그 좌표 지점**의 값이다.")


def _fmt(value: tuple) -> str:
    height, slope = value
    return f"{'—' if height is None else f'{height}m'} / " \
           f"{'—' if slope is None else f'{slope}°'}"


if __name__ == "__main__":
    main()
