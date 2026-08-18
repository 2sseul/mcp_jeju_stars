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

import pytest

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


# --- 도보 시간 ----------------------------------------------------------------


def _route_of(name: str, longest: bool = True) -> list:
    """관측지 이름으로 도보 경로 하나의 점 목록. 픽스처를 파일에서 가져온다."""
    doc = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    spot = next(s for s in doc["spots"] if s["name_ko"] == name)
    routes = sorted(
        spot["walk_routes"], key=lambda r: elevation.length_m(r["points"])
    )
    return (routes[-1] if longest else routes[0])["points"]


def test_마지막_자투리를_버리지_않는다():
    # Given: 창 하나를 못 채우는 꼬리가 남는 짧은 경로에서(망동산 292m)
    points = _route_of("망동산")
    # When: 도막으로 다시 묶으면
    spans = elevation.spans(points)
    # Then: 도막들이 경로 전체를 덮는다. 꼬리를 버리면 고도의 절반이 사라졌다 —
    #   망동산은 실제로 31.1m 중 14.5m 만 잡혔다
    assert sum(s.metres for s in spans) == pytest.approx(
        elevation.length_m(points), rel=1e-9
    )


def test_묶으면_계단의_고도가_되살아난다():
    # Given: 목재계단이 섞인 오름 경로에서(다랑쉬오름)
    points = _route_of("다랑쉬오름", longest=False)
    # When: 도막으로 다시 묶어 오른 높이를 더하면
    ascent = elevation.ascent_m(points)
    # Then: 경로 순고도와 맞는다. 사람이 나눠 둔 구간만 보면 계단이 전부
    #   격자 두 칸보다 짧아 209m 중 132m 밖에 잡히지 않았다 — 격자가 계단을
    #   못 본 것이 아니라 분모가 작아 잡음이 컸을 뿐이다
    assert ascent == pytest.approx(elevation.climb_m(points), abs=2.0)


def test_오르내리는_길은_순고도보다_더_오른다():
    # Given: 중간에 내려갔다 다시 오르는 경로에서(저지오름)
    points = _route_of("저지오름")
    # When: 오른 높이와 순 고도차를 나란히 보면
    ascent = elevation.ascent_m(points)
    net = elevation.climb_m(points)
    # Then: 오른 높이가 더 크다. `climb_m` 은 양 끝만 보므로 이런 길에서 모자란다
    assert ascent > net + 10


def test_평균_경사_하나로_재면_짧게_나온다():
    # Given: 완만한 구간과 급경사가 섞인 경로에서(새별오름)
    points = _route_of("새별오름")
    metres = elevation.length_m(points)
    flat = elevation.slope_deg(points)
    # When: 도막마다 잰 시간과, 평균 경사 하나로 낸 시간을 대 보면
    by_span = elevation.walk_minutes(points)
    by_mean = metres / 1000.0 / elevation.walk_speed_kmh(flat) * 60.0
    # Then: 평균 쪽이 더 짧다. 함수가 볼록해 평균으로 재면 늘 덜 나온다 —
    #   새별오름은 평균 7.6도지만 실제로는 15도·21도 구간이 있다
    assert by_span > by_mean


def test_왕복은_편도의_두_배가_아니다():
    # Given: 오르막이 있는 경로에서(용눈이오름)
    points = _route_of("용눈이오름")
    # When: 거꾸로도 걸어 보면
    up = elevation.walk_minutes(points)
    down = elevation.walk_minutes(points[::-1])
    # Then: 내려오는 쪽이 빠르다. 보행 함수가 오르막·내리막에 비대칭이라
    #   왕복이 필요하면 반대 방향으로 다시 적분해야 한다
    assert down < up


def test_관측지의_도보_시간은_격자와_같다():
    # Given: 지금 파일에 적힌 도보 경로들에서
    doc = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    stale = []
    for spot in doc["spots"]:
        for route in spot.get("walk_routes") or []:
            stored = route.get("minutes")
            # When: 그 선을 격자에 다시 대 보면
            fresh = elevation.walk_minutes(route["points"])
            if stored != fresh:
                stale.append(f"{spot['name_ko']}: 적힌 값 {stored} != 격자 {fresh}")
    # Then: 같아야 한다. 다르면 선을 고치고 다시 재지 않은 것이다 —
    #   uv run python -m scripts.measure_walk_time
    assert not stale, "격자와 어긋난 경로:\n  " + "\n  ".join(stale)
