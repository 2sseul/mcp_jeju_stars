"""도로 OSM 태그에서 **잰 값**만 뽑아 둔다 (배치, 다시 돌려도 안전).

`jeju_road_darkness.npz` 는 도로 등급(`highway`)과 이름만 담고 있다. 그런데 밤에
초행으로 들어갈 수 있는지를 가르는 것은 등급이 아니라 **폭·차선·노면**이다 —
앞에서 차가 오면 비켜설 데가 있는가, 포장은 되어 있는가.

등급으로 그것을 대신 말하면 안 된다. `highway=track` 이 좁다는 보장도, `residential`
이 넓다는 보장도 없다. 그래서 원본 OSM 이 실제로 적어 둔 태그만 꺼내 싣는다.

얼마나 있나 — 대부분 없다
--------------------------------------------------------------------------
제주 도로 29,390개 중

    width     234개 (0.8%)
    lanes   1,149개 (3.9%)
    surface 1,714개 (5.8%)

**없다는 사실도 답이다.** 이 스크립트는 없는 값을 추정해 채우지 않는다(폭을 등급에서
역산하는 식). 화면은 "폭 정보 없음"이라고 적고, 그 자리는 위성사진·로드뷰로 사람이
본다 — 그러라고 지도에 위성 토글이 있다.

30MB 짜리 원본 JSON 을 `core` 가 열 수는 없으므로(모듈 로드가 몇 초씩 걸린다)
여기서 작은 배열로 줄여 둔다. 배열 순서는 `jeju_road_darkness.npz` 의 way 인덱스와
같다 — 원본 elements 순서를 두 파일이 그대로 쓰므로 위치로 맞물린다.

실행:
    uv run python -m scripts.build_road_tags
"""

from __future__ import annotations

import json
import re

import numpy as np

from server import path

#: 폭 태그의 숫자 부분. '6' · '6 m' · '3.5m' 를 모두 받는다.
_WIDTH = re.compile(r"^\s*(\d+(?:\.\d+)?)")

#: 노면 태그 → 사람이 읽는 말. OSM 값은 그대로 두고 화면에서만 바꾼다.
#: 여기 없는 값은 원문 그대로 싣는다 — 모르는 것을 그럴듯하게 덮지 않는다.
SURFACE = {
    "asphalt": "아스팔트",
    "paved": "포장",
    "concrete": "콘크리트",
    "paving_stones": "블록",
    "sett": "돌포장",
    "unpaved": "비포장",
    "gravel": "자갈",
    "fine_gravel": "잔자갈",
    "dirt": "흙",
    "ground": "흙",
    "grass": "풀",
    "sand": "모래",
    "compacted": "다짐",
}

#: 값이 없음을 뜻하는 표시. 차선은 정수라 -1, 폭은 실수라 NaN 을 쓴다.
NO_LANES = -1


def _lanes(raw: str | None) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return NO_LANES


def _width(raw: str | None) -> float:
    if raw is None:
        return float("nan")
    match = _WIDTH.match(str(raw))
    return float(match.group(1)) if match else float("nan")


def main() -> None:
    elements = json.loads(path.ROADS_OSM.read_text(encoding="utf-8"))["elements"]
    darkness = np.load(path.ROAD_DARKNESS, allow_pickle=True)
    if len(elements) != len(darkness["way_class"]):
        raise SystemExit(
            f"도로 수가 어긋납니다: OSM {len(elements):,} ≠ "
            f"npz {len(darkness['way_class']):,}. 둘을 같은 시점에 다시 만드세요."
        )

    lanes = np.empty(len(elements), dtype=np.int8)
    width = np.empty(len(elements), dtype=np.float32)
    surface = np.empty(len(elements), dtype="<U16")
    oneway = np.zeros(len(elements), dtype=bool)

    for i, element in enumerate(elements):
        tags = element.get("tags") or {}
        lanes[i] = _lanes(tags.get("lanes"))
        width[i] = _width(tags.get("width"))
        surface[i] = str(tags.get("surface") or "")
        oneway[i] = str(tags.get("oneway") or "").lower() in ("yes", "1", "-1")

    np.savez_compressed(
        path.ROAD_TAGS,
        lanes=lanes,
        width=width,
        surface=surface,
        oneway=oneway,
        source=str(darkness["source"]),
    )

    total = len(elements)
    have_lanes = int((lanes != NO_LANES).sum())
    have_width = int((~np.isnan(width)).sum())
    have_surface = int((surface != "").sum())
    print(f"도로 {total:,}개 → {path.ROAD_TAGS.relative_to(path.ROOT)} "
          f"({path.ROAD_TAGS.stat().st_size / 1024:.0f} KB)")
    print(f"  차선 {have_lanes:,} ({100 * have_lanes / total:.1f}%) · "
          f"폭 {have_width:,} ({100 * have_width / total:.1f}%) · "
          f"노면 {have_surface:,} ({100 * have_surface / total:.1f}%) · "
          f"일방통행 {int(oneway.sum()):,}")
    print("  대부분 비어 있다 — 없는 값은 추정하지 않는다. "
          "화면은 '정보 없음'이라고 적는다.")


if __name__ == "__main__":
    main()
