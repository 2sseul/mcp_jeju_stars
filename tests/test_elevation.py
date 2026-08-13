"""elevation — 표고 격자에서 잰 값.

격자가 무엇을 답하는지는 회귀 픽스처(`docs/decisions.md` §2.17)가 지키고, 여기서는
**관측지 목록의 두 칸이 그 격자와 같은 말을 하는지**를 본다. 이 둘이 갈리는 것이
실제로 났던 결함이다 — 좌표를 옮기고 값을 다시 안 재서 120곳 중 27곳이 옛 자리
값을 들고 있었다(2026-08-13, §2.20). 값이 파일에 박히는 종류의 결함은 다음에
열었을 때가 아니라 그 값을 믿고 추천이 나갈 때 드러난다.

격자 파일이 없으면 `core.elevation` 이 import 에서 죽으므로, 이 파일도 함께 죽는다 —
받은 저장소에서 처음 쓸 때 `scripts/build_elevation_grid.py` 를 한 번 돌리라는 뜻이다.
"""

from __future__ import annotations

import json

from scripts.measure_elevation import ELEVATION_KEY, SLOPE_KEY, measure_site
from server import path
from server.core import elevation

#: 용눈이오름 관측 좌표. 회귀 픽스처가 쓰는 것과 같은 오름이다.
_YONGNUNI = (33.45987399291166, 126.83273355024946)


def test_한_점의_경사는_방향이_없다():
    # Given: 관측지 한 점에서
    slope = elevation.slope_at(*_YONGNUNI)
    # When: 경사를 재면
    # Then: 0 이상이다 — 여기서 묻는 것은 '이 자리가 비탈인가'라 오르막·내리막이
    #   없다. 방향이 있는 것은 걸어간 선의 경사(`slope_deg`)다.
    assert slope is not None
    assert slope >= 0


def test_격자_밖이면_모른다고_답한다():
    # Given: 제주 격자 밖 좌표에서(N33 E126 타일 하나만 담고 있다)
    # When: 표고와 경사를 물으면
    # Then: 0 이 아니라 None 이다 — 0 으로 답하면 '해수면의 평지'로 읽힌다
    assert elevation.at(33.0, 125.0) is None
    assert elevation.slope_at(33.0, 125.0) is None


def test_관측지의_해발높이와_경사는_격자와_같다():
    # Given: 지금 파일에 적힌 관측지들에서
    doc = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    stale = []
    for spot in doc["spots"]:
        stored = (spot.get(ELEVATION_KEY), spot.get(SLOPE_KEY))
        measured = dict(spot)
        measure_site(measured)
        # When: 그 좌표를 격자에 다시 대 보면
        if (measured.get(ELEVATION_KEY), measured.get(SLOPE_KEY)) != stored:
            stale.append(
                f"{spot['name_ko']}: 적힌 값 {stored} != 격자 "
                f"{(measured.get(ELEVATION_KEY), measured.get(SLOPE_KEY))}"
            )
    # Then: 같아야 한다. 다르면 좌표를 옮기고 다시 재지 않은 것이다 —
    #   uv run python -m scripts.measure_elevation
    assert not stale, "격자와 어긋난 관측지:\n  " + "\n  ".join(stale)
