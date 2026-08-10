"""중산간 주차장을 `data/jeju_spots.json` 에 편입한다 (P9).

왜 주차장만 따로 긁는가
--------------------------------------------------------------------------
`sweep_place_candidates.py` 는 **이름 있는 야외 장소**(오름·전망대·휴양림…)를 긁고
그 옆에 주차가 있는지를 본다. 그래서 이름이 장소를 가리키지 않는 자리 —
"동광육거리주차장", "메밀밭주차장" 처럼 **주차장 자체가 목적지**인 곳은 걸리지
않는다. 관광객이 밤에 실제로 서 있는 자리는 그런 데다.

여기서는 축을 뒤집는다. 카카오맵 주차장 검색분(`data/kakao_places/parking.csv`,
1,912곳)을 **전부** 놓고 해발높이로만 자른다.

왜 어둡기가 아니라 해발높이로 자르는가
--------------------------------------------------------------------------
어둡기로 자르면 지금 어두운 곳만 남는데, 이 목록은 **사람이 손으로 채울 후보 풀**
이지 추천 결과가 아니다. 해발 200m 위(제주도가 쓰는 중산간 경계)는 그 자체로
"시가지가 아니고 차로 닿는 자리"라는 뜻이라, 어둡기가 애매한 곳도 남겨 두고 사람이
판단하게 한다. 어둡기 점수는 `notes` 에 실측값으로 적어 그 판단의 재료로 준다.

해발높이는 저장소에 DEM 이 없어 Open-Meteo 로 받는다(`fetch_elevation.py` 와 같은
출처). 1,912곳 분은 `outputs/` 에 캐시하므로 두 번째 실행부터는 부르지 않는다.

같은 곳이면 합친다
--------------------------------------------------------------------------
`merge_swept_spots.py` 와 같은 규칙이다 — 이미 있는 관측지 근처(600m)이거나 이름이
겹치면 새로 만들지 않고, 그 관측지에 **주차 좌표**로 붙인다. '백약이오름 주차장'은
새 관측지가 아니라 백약이오름의 주차 좌표다. 새로 만든 것끼리도 같은 규칙으로
합쳐진다 — 그러지 않으면 '제주대학교 주차장2~13' 이 열두 곳으로 들어온다.

여러 번 돌려도 같은 결과다.

    uv run python -m scripts.merge_upland_parking          # 해발 200m 이상
    uv run python -m scripts.merge_upland_parking 300      # 경계 조정
    → 이어서 uv run python -m scripts.fetch_elevation      # elevation_m·slope_deg
"""

from __future__ import annotations

import json
import sys
import time

from scripts.fetch_elevation import fetch
from scripts.merge_swept_spots import SAME_PLACE_KM, absorb, region_of, type_of
from server import path
from server.core import darkness, places

#: 중산간 경계(m). 제주특별자치도가 관리보전지역·중산간 정책에서 쓰는 해발 200m 다.
#: 위쪽 경계는 두지 않는다 — 600m 를 넘는 자리(관음사·1100고지 권역)도 차로 닿으면
#: 후보이고, 야간 통제 여부는 사람이 판단할 몫이다.
UPLAND_M = 200.0

#: 한 요청에 담을 좌표 수. Open-Meteo Elevation 의 상한이다.
_PER_REQUEST = 100

#: 분당 요청 제한(429)에 걸렸을 때 기다리는 시간(초).
_RETRY_WAIT = 62.0
_RETRIES = 6

#: 해발높이 캐시. 원본 CSV 를 다시 긁기 전에는 값이 변하지 않고, 언제든 다시
#: 받을 수 있으므로 `data/` 가 아니라 산출물로 둔다.
ELEVATION_CACHE = path.OUTPUTS / "parking_elevation.json"

_KM_PER_DEG = 111.19492664455873
_COS_LAT = 0.836

#: 관측지 좌표와 이만큼 안이면 같은 점으로 본다 — `edit_spots.py` 의 주차장 중복
#: 제거와 같은 눈금. 이 거리에서는 주차 좌표를 따로 적어도 관측지 좌표를 한 번 더
#: 적는 것이라 알려 주는 것이 없다.
SAME_POINT_M = 30.0

#: 이름에서 걷어내면 '어느 곳인가'만 남는 말들. 긴 것부터 지운다.
_PARKING_WORDS = ("공영주차장", "야외주차장", "지하주차장", "환승주차장", "대형주차장",
                  "전기차충전소", "주차장", "주차", "대형", "무료", "야외", "공영")

#: 행정 단위 꼬리. 이름이 장소를 안 가리킬 때 주소에서 이만큼을 빌려 온다.
_ADMIN_TAIL = ("시", "군", "읍", "면", "동", "리")


def identity(name: str) -> str:
    """이름에서 주차 관련 말을 뺀 나머지 — 그 자리가 **어느 곳인지** 가리키는 부분.

    '백약이오름 주차장' → '백약이오름' / '야외주차장' → '' 이다. 빈 문자열이면
    이름만으로는 어느 곳인지 알 수 없다는 뜻이라, 이름 대조에 쓰면 안 된다.
    """
    for word in _PARKING_WORDS:
        name = name.replace(word, " ")
    return "".join(name.split())


def find_same(spots: list[dict], row: dict) -> dict | None:
    """이미 데이터셋에 있는 같은 곳. 좌표 근접, 또는 관측지 이름이 주차장 이름
    안에 들어 있는 경우다 — '백약이오름 주차장'은 백약이오름의 주차 좌표다.

    이름 대조에는 두 가지 제한이 붙는다. `merge_swept_spots.find_same` 과 달리
    **반대 방향(주차장 이름이 관측지 이름 안에 들어 있는 경우)은 보지 않는다** —
    여기 오는 이름은 전부 '…주차장'이라 그 방향은 '주차장'·'야외주차장' 같은
    이름이 '어리목입구주차장'에 걸려 13km 떨어진 곳을 같은 곳으로 만든다.
    남은 방향도 관측지 이름이 `identity` 를 가질 때만 본다 — 그러지 않으면 이름이
    '주차장'인 관측지가 한 번 들어온 뒤로 뒤따르는 '…주차장'을 전부 삼킨다.
    """
    for spot in spots:
        dy = (row["lat"] - spot["lat"]) * _KM_PER_DEG
        dx = (row["lon"] - spot["lon"]) * _KM_PER_DEG * _COS_LAT
        if (dy * dy + dx * dx) ** 0.5 < SAME_PLACE_KM:
            return spot
        if len(identity(spot["name_ko"])) >= 2 and spot["name_ko"] in row["name"]:
            return spot
    return None


def name_of(row: dict) -> str:
    """관측지 이름. 원본 이름이 장소를 안 가리키면 주소의 행정 단위를 덧붙인다 —
    '주차장' 이라고만 적힌 항목이 목록에 여럿 있으면 사람이 고를 수가 없다.
    """
    if len(identity(row["name"])) >= 2:
        return row["name"]
    where = [part for part in row["address"].split()[1:]
             if part.endswith(_ADMIN_TAIL)]
    return f"{row['name']}({' '.join(where)})" if where else row["name"]


def elevations(lots: list[places.Place]) -> dict[str, float]:
    """주차장 id → 해발높이(m). 캐시에 없는 것만 받아 채운다."""
    ELEVATION_CACHE.parent.mkdir(exist_ok=True)
    cache: dict[str, float] = (
        json.loads(ELEVATION_CACHE.read_text(encoding="utf-8"))
        if ELEVATION_CACHE.exists() else {}
    )
    todo = [lot for lot in lots if lot.id not in cache]
    if todo:
        print(f"  해발높이 받는 중 {len(todo):,}곳 (캐시 {len(cache):,})")
    for start in range(0, len(todo), _PER_REQUEST):
        chunk = todo[start:start + _PER_REQUEST]
        for attempt in range(_RETRIES):
            try:
                heights = fetch([(lot.lat, lot.lon) for lot in chunk])
                break
            except SystemExit as exc:
                if "429" not in str(exc) or attempt == _RETRIES - 1:
                    raise
                print(f"    분당 제한 — {_RETRY_WAIT:.0f}초 대기", flush=True)
                time.sleep(_RETRY_WAIT)
        cache.update({lot.id: h for lot, h in zip(chunk, heights)})
        ELEVATION_CACHE.write_text(json.dumps(cache), encoding="utf-8")
        print(f"    {min(start + _PER_REQUEST, len(todo)):,}/{len(todo):,}", flush=True)
    return cache


def to_row(lot: places.Place, elevation: float) -> dict | None:
    """주차장 하나 → 편입용 행. 어둡기 격자 밖(해상)이면 None."""
    site = darkness.assess_site(lot.lat, lot.lon)
    if site.score is None:
        return None
    return {
        "name": lot.name, "lat": lot.lat, "lon": lot.lon,
        "elevation": elevation,
        "score": round(site.score, 3),
        "category": lot.category, "address": lot.address, "url": lot.url,
        # 이미 있는 관측지에 합쳐질 때 이 주차장이 곧 그 관측지의 주차 좌표다.
        "parking_point": {"name": lot.name, "lat": lot.lat, "lon": lot.lon},
    }


def to_spot(row: dict) -> dict:
    """새 관측지 하나. 좌표가 곧 주차 지점이라 `parking` 키를 따로 두지 않는다."""
    kind = row["category"].split(" > ")[-1] or "미분류"
    spot = {
        "name_ko": name_of(row),
        "lat": row["lat"], "lon": row["lon"],
        "coord_confidence": "high",
        "region": region_of(row["lat"], row["lon"]),
        "type": type_of(row["name"], row["category"]),
        "why": f"카카오맵 주차장 전수 수집에서 해발 {UPLAND_M:.0f}m 이상(중산간)에 "
               f"있어 뽑힌 자리. 좌표가 곧 주차 지점이다 (분류: {kind})",
        "notes": f"어둡기 종합 {row['score']:.3f} 실측 · 해발 {row['elevation']:.0f}m. "
                 f"{row['address']}",
        "discovery": "kakao_parking",
    }
    if row["url"]:
        spot["sources"] = [row["url"]]
    return spot


def main() -> None:
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else UPLAND_M
    lots = [p for p in places.places() if p.source == "parking"]
    print(f"카카오맵 주차장 {len(lots):,}곳 · 중산간 경계 해발 {limit:.0f}m")

    height = elevations(lots)
    upland = [lot for lot in lots if height[lot.id] >= limit]
    print(f"  해발 {limit:.0f}m 이상 {len(upland):,}곳")

    rows = [row for row in (to_row(lot, height[lot.id]) for lot in upland) if row]
    rows.sort(key=lambda r: r["score"])
    print(f"  어둡기 격자 안 {len(rows):,}곳")

    doc = json.loads(path.SPOTS.read_text(encoding="utf-8"))
    spots = doc["spots"]
    before = len(spots)

    added, absorbed, merged = [], [], 0
    for row in rows:
        same = find_same(spots, row)
        if same is None:
            spot = to_spot(row)
            spots.append(spot)
            added.append((row, spot))
            continue
        merged += 1
        dy = (row["lat"] - same["lat"]) * _KM_PER_DEG
        dx = (row["lon"] - same["lon"]) * _KM_PER_DEG * _COS_LAT
        if (dy * dy + dx * dx) ** 0.5 * 1000 < SAME_POINT_M:
            row = {k: v for k, v in row.items() if k != "parking_point"}
        gained = absorb(same, row)
        if gained:
            absorbed.append(f"{row['name']} → {same['name_ko']} (+{'·'.join(gained)})")

    doc["meta"]["title"] = f"제주 다크스카이 관측지 큐레이션 목록 ({len(spots)}곳)"
    # 제목과 같은 수를 두 군데 적어 두고 한쪽만 고치면 어느 쪽이 맞는지 알 수 없다.
    doc["meta"]["count"] = len(spots)
    doc["meta"]["discovery"] = doc["meta"]["discovery"].rstrip() + (
        " `discovery`가 `kakao_parking` 인 항목은 `scripts/merge_upland_parking.py` "
        f"가 카카오맵 주차장 전수 수집에서 해발 {limit:.0f}m 이상(중산간)만 골라 "
        "넣은 것이다 — 어둡기로 자르지 않았으므로 밝은 자리가 섞여 있고, notes 의 "
        "실측 점수를 보고 판단한다. 좌표가 곧 주차 지점이라 `parking` 키가 없다."
    )
    path.SPOTS.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n편입 {len(added)}곳 · 기존 관측지와 합침 {merged}건"
          f"(그중 사실 보강 {len(absorbed)}건)")
    print(f"  {before} → {len(spots)}곳")
    for line in absorbed:
        print(f"    {line}")

    print(f"\n{'점수':>6s} {'해발':>6s} {'이름':30s} {'지역':6s} 유형")
    for row, spot in added:
        print(f"{row['score']:6.3f} {row['elevation']:5.0f}m "
              f"{spot['name_ko'][:30]:30s} {spot['region']:6s} {spot['type']}")

    swept = sum(s.get("discovery") == "kakao_sweep" for s in spots)
    parked = sum(s.get("discovery") == "kakao_parking" for s in spots)
    print(f"\n총 {len(spots)}곳 · 자동발굴 {swept + parked}"
          f"(장소 {swept} + 주차장 {parked}) · 큐레이션 {len(spots) - swept - parked}")
    print("다음: uv run python -m scripts.fetch_elevation "
          "(새 항목의 elevation_m·slope_deg 를 채운다)")


if __name__ == "__main__":
    main()
