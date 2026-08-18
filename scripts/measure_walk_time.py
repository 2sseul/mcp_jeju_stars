"""도보 경로의 편도 소요시간·누적 오름을 표고 격자에서 잰다 (배치, 다시 돌려도 안전).

사람이 손으로 적을 값이 아니다 — 선을 그어 두면 시간은 정해진다. 실제로 손으로
적혀 있던 `walk_minutes` 5곳은 **경로와 다른 지점까지의 시간**이었다(새별오름은
경로가 관측 지점 504m 에서 끝나는데 적힌 30분은 정상 519.3m 까지였다). 이 배치가
그 칸을 대신하고, 넣을 때 지운다.

무엇을 재는가
--------------------------------------------------------------------------
    walk_routes[].minutes    그 경로를 걷는 **편도** 시간(분)
    walk_routes[].ascent_m   그 경로에서 실제로 오르는 높이(m)
    walk_routes[].stair_m    계단·로프 등 손발을 더 쓰는 구간의 길이(m)

`ascent_m` 은 이미 있는 `climb_m`(양 끝의 순 고도차)과 다르다. 오르내리는 길에서
갈린다 — 저지오름은 순 111.7m 인데 실제로 오르는 것은 149.7m 다.

`stair_m` 은 **시간에 들어가지 않는다**(`core/trail.STAIRS_FROM`). 같은 기울기에서
계단이 느리다는 근거가 없어 계수를 붙이지 않고, 잰 사실을 그대로 내보내 사람이
판단하게 한다 — "503m 중 319m가 목재계단"(지미봉). 힘든 정도는 국립공원공단 탐방로
등급이 노면·암릉을 36% 가중치로 이미 말한다. 전체 경로의 12.6%가 계단이고,
100m 넘는 경로 50개 중 31개는 계단이 아예 없다.

**왕복이 아니라 편도다.** 경로가 주차장 → 관측 지점 단방향으로 그어져 있고,
보행 함수가 오르막·내리막에 비대칭이라 왕복은 이 값의 두 배가 아니다.

무엇에 기대는가
--------------------------------------------------------------------------
Márquez-Pérez et al.(2017)의 수정 Tobler 함수다(`core/elevation.walk_minutes`).
스페인 공인 등산로 21개의 **실제 완주 기록**으로 맞춘 것이라, 재는 대상이 우리가
내보낼 값과 같다. 원본 Tobler(1993)는 표본 미상 2차 자료이고 `3/5 배` 는 *길 없는 곳*
계수라 목재계단·흙길에 쓸 근거가 없다 — 경위는 `docs/decisions.md`.

**국내 오름에서는 검증하지 못했다.** 대 볼 실측 시간이 없다.

왜 배치인가
--------------------------------------------------------------------------
표고 격자(FABDEM)는 라이선스상 커밋하지 않는 파일이라 배포 컨테이너에 없다. 여기서
미리 재어 `jeju_spots.json` 에 넣어 두면 서버가 격자 없이 답할 수 있다.
`measure_elevation.py` 와 같은 이유·같은 방식이다.

**늘 전부 다시 잰다.** 선을 고쳐 놓고 이 배치를 안 부르면 시간이 옛 선에 남는다.

실행:
    uv run python -m scripts.measure_walk_time
"""

from __future__ import annotations

import json

from server import path
from server.core import elevation, trail

#: 채우는 칸. `scripts/edit_spots.py` 의 경로 키와 같아야 한다.
MINUTES_KEY = "minutes"
ASCENT_KEY = "ascent_m"
STAIR_KEY = "stair_m"

#: 이 배치가 대신하는, 사람이 손으로 적던 칸.
LEGACY_KEY = "walk_minutes"


def measure_route(route: dict) -> None:
    """경로 하나의 두 칸을 다시 잰다.

    못 재면(점이 모자라거나 격자 밖) **키를 지운다** — 이 파일의 규약대로 없는 키가
    곧 '모른다'이고, 0 으로 채우면 '걷지 않아도 되는 자리'로 읽힌다.

    있는 키는 자리를 지킨 채 값만 바꾼다 — 그래야 diff 가 고친 줄에만 난다.
    """
    points = route.get("points") or []

    minutes = elevation.walk_minutes(points)
    ascent = elevation.ascent_m(points)
    stair = _stair_metres(route)

    if minutes is None:
        route.pop(MINUTES_KEY, None)
    else:
        route[MINUTES_KEY] = minutes
    if ascent is None:
        route.pop(ASCENT_KEY, None)
    else:
        route[ASCENT_KEY] = ascent
    # 계단이 **없다**는 것과 **아직 안 봤다**는 것은 다른 말이다. 구간을 하나도 안
    # 적은 경로는 키를 만들지 않고, 적었는데 계단이 없으면 0 을 적는다.
    if stair is None:
        route.pop(STAIR_KEY, None)
    else:
        route[STAIR_KEY] = stair


def _stair_metres(route: dict) -> float | None:
    """계단·로프 등 손발을 더 쓰는 구간의 길이(m). 구간을 안 적었으면 None."""
    points = route.get("points") or []
    segments = route.get("segments") or []
    if len(points) < 2 or not any(s.get("rock") for s in segments):
        return None

    total = 0.0
    for segment in segments:
        if not trail.is_stairs(segment.get("rock") or ""):
            continue
        start, end = segment.get("from"), segment.get("to")
        if start is None or end is None:
            continue
        total += elevation.length_m(points[start : end + 1])
    return round(total, 1)


def main() -> None:
    doc = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    spots = doc["spots"]

    changed, blank, dropped = [], [], []
    for spot in spots:
        if spot.pop(LEGACY_KEY, None) is not None:
            dropped.append(spot["name_ko"])

        routes = spot.get("walk_routes") or []
        for route in routes:
            before = route.get(MINUTES_KEY)
            measure_route(route)
            after = route.get(MINUTES_KEY)
            if after != before:
                changed.append((spot["name_ko"], before, after))

        if routes and all(r.get(MINUTES_KEY) is None for r in routes):
            blank.append(spot["name_ko"])

    tmp = path.SPOTS.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path.SPOTS)

    timed = []
    for spot in spots:
        routes = spot.get("walk_routes") or []
        got = [r[MINUTES_KEY] for r in routes if MINUTES_KEY in r]
        if got:
            # 갈래가 여럿이면 **가장 짧은 길**이 그 관측지의 시간이다.
            timed.append((min(got), spot["name_ko"]))

    print(f"관측지 {len(timed):,}/{len(spots):,}곳 잼 — 바뀐 경로 {len(changed):,}개")
    for name, before, after in changed:
        print(f"  {name:<24} {before if before is not None else '—'} → {after}분")
    if dropped:
        names = "·".join(dropped)
        print(f"  손으로 적힌 {LEGACY_KEY} 를 지움 {len(dropped)}곳: {names}")
    if blank:
        print(f"  격자 밖이라 못 잰 곳 {len(blank):,}: {'·'.join(blank)}")

    if timed:
        timed.sort()
        near = [n for m, n in timed if m <= 5]
        print(f"\n{path.SPOTS.relative_to(path.ROOT)} — 편도 기준")
        print(f"  {elevation.WALK_SOURCE}")
        print(f"  차에서 5분 이내 {len(near):,}곳")
        print(f"  가장 짧은 곳  {timed[0][1]} {timed[0][0]:.1f}분")
        print(f"  가장 먼 곳    {timed[-1][1]} {timed[-1][0]:.1f}분")

    stairs = [
        (r[STAIR_KEY] / r["over_m"], s["name_ko"], r)
        for s in spots
        for r in (s.get("walk_routes") or [])
        if r.get(STAIR_KEY) and r.get("over_m")
    ]
    if stairs:
        stairs.sort(reverse=True)
        share, name, route = stairs[0]
        print(f"  계단이 있는 경로 {len(stairs):,}개 — 비중이 가장 높은 곳은 "
              f"{name} ({route['over_m']:.0f}m 중 {route[STAIR_KEY]:.0f}m, "
              f"{share * 100:.0f}%)")
    lo, hi = elevation.WALK_ERROR_MIN_PER_KM
    print(f"  오차 km당 {lo}~{hi}분. 야간·짐은 들어 있지 않다.")


if __name__ == "__main__":
    main()
