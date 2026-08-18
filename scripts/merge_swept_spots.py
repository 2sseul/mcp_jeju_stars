"""자동 발굴 후보를 `data/jeju_spots.json` 에 편입한다 (P9).

`sweep_place_candidates.py` 가 만든 묶음을 데이터셋에 넣는다. 두 가지를 지킨다.

**출처를 구분한다.** 편입분에는 `discovery` 키를 단다. 이 항목들은 사람이 아직
보지 않았고, `plan.md` P9 이 '자동 발굴 결과를 그대로 내보내지 않고 로드뷰 데스크
검증을 통과한 것만 노출한다'고 정해 뒀다 — 그 구분이 실제로 쓰이므로 남긴다.

**같은 곳이면 버리지 않고 사실을 합친다.** '족은노꼬메오름 주차장'은 노꼬메오름의
주차 좌표이고(P9 의 주차/관측 좌표 분리), '서귀포자연휴양림 야영장'은 그 휴양림에
화장실이 있다는 근거다. 중복이라고 버리면 그 사실이 사라진다.

여러 번 돌려도 같은 결과다 — 이름·좌표로 이미 있는 곳을 알아보고 합치기만 한다.

    uv run python -m scripts.merge_swept_spots           # 기본 컷
    uv run python -m scripts.merge_swept_spots 0.50      # 컷 조정
"""

from __future__ import annotations

import json
import sys

from scripts.sweep_place_candidates import OUT as CANDIDATES
from scripts.sweep_place_candidates import is_junk
from server import path

#: 어둡기 컷. 큐레이션 최하위인 저지오름(0.481)까지를 후보로 보는 선이다.
#: 이보다 위는 포구·해변이 대부분이라 실익이 급격히 떨어진다.
DEFAULT_CUT = 0.45

#: 같은 곳으로 볼 거리. 휴양림처럼 넓은 시설은 대표점이 이만큼 떨어져 있다.
SAME_PLACE_KM = 0.6

_KM_PER_DEG = 111.19492664455873
_COS_LAT = 0.836

#: `region` 5구분 — 기존 항목이 쓰는 값에 맞춘다.
_NORTH_LON = (126.35, 126.65)


def region_of(lat: float, lon: float) -> str:
    if lat >= 33.48 and _NORTH_LON[0] <= lon <= _NORTH_LON[1]:
        return "북"
    if lon >= 126.70:
        return "동"
    if lon <= 126.35:
        return "서"
    if lat <= 33.32:
        return "남"
    return "중산간"


_TYPES = (("야영", "야영장"), ("캠핑", "야영장"), ("휴양림", "숲"), ("오름", "오름"),
          ("악", "오름"), ("봉", "오름"), ("전망대", "전망"), ("목장", "목장"),
          ("해수욕장", "해안"), ("해변", "해안"), ("포구", "해안"), ("항", "해안"),
          ("등대", "해안"), ("저수지", "저수지"), ("곶자왈", "숲"), ("수목원", "숲"),
          ("숲", "숲"), ("둘레길", "숲"), ("공원", "공원"), ("주차장", "주차장"))


def type_of(name: str, category: str) -> str:
    text = f"{name} {category}"
    for word, kind in _TYPES:
        if word in text:
            return kind
    return "기타"


def find_same(spots: list[dict], row: dict) -> dict | None:
    """이미 데이터셋에 있는 같은 곳. 좌표 근접 또는 이름 포함 관계로 본다.

    거리만 보면 넓은 시설의 대표점이 멀리 잡힌 경우를 놓치고, 이름만 보면
    좌표가 다른 동명이소를 합쳐 버린다 — 그래서 둘 다 본다.
    """
    for spot in spots:
        dy = (row["lat"] - spot["lat"]) * _KM_PER_DEG
        dx = (row["lon"] - spot["lon"]) * _KM_PER_DEG * _COS_LAT
        if (dy * dy + dx * dx) ** 0.5 < SAME_PLACE_KM:
            return spot
        if row["name"] in spot["name_ko"] or spot["name_ko"] in row["name"]:
            return spot
    return None


def absorb(spot: dict, row: dict) -> list[str]:
    """이미 있는 곳에 새로 안 사실만 채운다. 기존 값은 덮지 않는다."""
    gained = []
    if "parking_point" in row and "parking" not in spot:
        # `parking` 은 자리 목록이다(들머리가 갈리면 대는 자리도 갈린다). 전수 수집이
        # 아는 것은 최근접 한 곳뿐이라 한 칸짜리 목록으로 넣는다 — 나머지는 로드뷰
        # 검증에서 `edit_spots.py` 가 더한다.
        spot["parking"] = [row["parking_point"]]
        gained.append("주차좌표")
    # 화장실은 붙이지 않는다. 전수 수집이 아는 것은 '있다'뿐이고 `toilet` 은 자리
    # 목록이라 좌표 없는 참을 담을 자리가 없다 — 키를 비워 두면 로드뷰 검증에서
    # 사람이 좌표째 채운다("없는 키가 곧 미확인").
    if row.get("campsite") and "campsite" not in spot:
        spot["campsite"] = True
        gained.append("야영장")
    if row.get("url") and row["url"] not in spot.setdefault("sources", []):
        spot["sources"].append(row["url"])
    if not spot["sources"]:
        del spot["sources"]
    return gained


def to_spot(row: dict) -> dict:
    kind = row["category"].split(" > ")[-1] or "미분류"
    spot = {
        "name_ko": row["name"],
        "lat": row["lat"], "lon": row["lon"],
        "coord_confidence": "high",
        "region": region_of(row["lat"], row["lon"]),
        "type": type_of(row["name"], row["category"]),
        "why": f"카카오맵 전수 수집에서 어둡기·주차·도로 접근을 모두 통과한 지점 "
               f"(분류: {kind})",
        "notes": f"어둡기 종합 {row['score']:.3f} 실측. 최근접 주차 "
                 f"{row['parking_m']}m · 주행 가능 도로 {row['road_m']}m. "
                 f"{row['address']}",
        "discovery": "kakao_sweep",
    }
    if "parking_point" in row:
        spot["parking"] = [row["parking_point"]]
    if row.get("campsite"):
        spot["campsite"] = True
    if row.get("url"):
        spot["sources"] = [row["url"]]
    return spot


def main() -> None:
    cut = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CUT
    if not CANDIDATES.exists():
        raise SystemExit(
            f"{CANDIDATES} 가 없습니다.\n"
            "  → uv run python -m scripts.sweep_place_candidates 를 먼저 돌리세요."
        )
    rows = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    data = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    spots = data["spots"]
    before = len(spots)

    added, absorbed, dropped = [], [], 0
    for row in sorted(rows, key=lambda r: r["score"]):
        if row["score"] > cut:
            break
        if is_junk(row):
            dropped += 1
            continue
        same = find_same(spots, row)
        if same is None:
            spot = to_spot(row)
            spots.append(spot)
            added.append((row["score"], spot))
            continue
        gained = absorb(same, row)
        if gained:
            absorbed.append(f"{row['name']}→{same['name_ko']}(+{'·'.join(gained)})")

    data["meta"]["title"] = f"제주 다크스카이 관측지 큐레이션 목록 ({len(spots)}곳)"
    data["meta"]["discovery"] = (
        "`discovery` 키가 있는 항목은 `scripts/sweep_place_candidates.py` 의 "
        "자동 발굴분이다 — 카카오맵 로컬 API 전수 수집에서 어둡기(core.darkness) ∩ "
        "주차 근접 ∩ 주행 가능 도로 근접을 통과하고 근접 묶음으로 합친 뒤 "
        f"score ≤ {cut} 로 자른 것. **사람이 아직 보지 않았다** — plan.md P9 의 "
        "로드뷰 데스크 검증을 통과하기 전에는 추천에 노출하지 않는다. "
        "키가 없는 항목은 웹서치·관광포털 큐레이션분이다."
    )
    path.SPOTS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"편입 {len(added)}곳 · 사실 합침 {len(absorbed)}건 · 분류 제외 {dropped}건")
    print(f"  {before} → {len(spots)}곳")
    for line in absorbed:
        print(f"    {line}")
    print(f"\n{'점수':>6s} 표식 {'이름':24s} {'지역':4s} 유형")
    for score, spot in added:
        mark = ("P" if "parking" in spot else " ") \
             + ("C" if "campsite" in spot else " ")
        print(f"{score:6.3f} {mark}  {spot['name_ko'][:24]:24s} "
              f"{spot['region']:4s} {spot['type']}")

    swept = sum("discovery" in s for s in spots)
    print(f"\n총 {len(spots)}곳 · 자동발굴 {swept} · 큐레이션 {len(spots) - swept}")
    for key in ("parking", "campsite", "cautions", "sources"):
        print(f"  {key:11s} {sum(key in s for s in spots):3d}곳")


if __name__ == "__main__":
    main()
