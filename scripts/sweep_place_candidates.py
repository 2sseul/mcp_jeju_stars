"""이름 있는 야외 장소를 전수로 긁어 관측지 후보를 만든다 (P9 자동 발굴).

왜 이 방식인가
--------------------------------------------------------------------------
후보를 웹검색으로 모으면 30~40곳에서 포화한다 — 뒤로 갈수록 같은 이름
(1100고지·마방목지·새별오름)이 반복되고, 정작 가장 어두운 곳은 후기가 없어
검색에 걸리지 않는다. 반면 오름은 제주에 300개 넘게 있고 전부 이름·좌표·주소가
있다. **블로그가 안 써도 실재하고 지도에 등록된 장소**라, 도로 격자에서 좌표만
뽑는 것과 달리 그대로 관광객에게 안내할 수 있다.

세 단계로 거른다
--------------------------------------------------------------------------
1. **수집** — 카카오 로컬 키워드 검색을 제주 전역 사분할로 전수 순회
   (`fetch_kakao_places.collect` 재사용). 12~20개 키워드로 1,500건 안팎.
2. **접근** — 어둡기만으로 자르면 백록담·사라오름 같은 **한라산 심부**가 상위를
   차지한다. 최암부는 대개 사람이 못 가는 곳이라는 뜻이다. 그래서 주차 지점
   근접(공영 1,557 + 카카오)과 주행 가능 도로 근접을 **먼저** 조인한다
   (`plan.md` P9: 필터를 먼저 조인한 뒤 어둡기 순으로 자른다).
   `track`(농로·임도)·`service`(사유 진입로)는 도로로 치지 않는다 — 관광객을
   밤에 농로로 보내면 안 된다.
3. **묶기** — 한 시설이 여러 점으로 등록돼 있다(휴양림 화장실 2·4·5·6, 야영장
   취사장·축구장). 그대로 두면 검토자가 같은 곳을 열 번 판단한다. 400m 안을
   한 묶음으로 보고 **장소 자체를 가리키는 이름**을 대표로 삼는다. 부속 항목은
   버리지 않고 그 묶음의 주차 좌표·화장실 근거로 붙인다.

자르는 기준은 **대표점 자신의 점수**다. 묶음 최솟값으로 자르면 실제로 안내할
좌표가 기준보다 밝은 채로 통과한다(신양섭지해수욕장: 묶음 0.377 · 대표점 0.514).

산출물은 `outputs/` 라 커밋하지 않는다 — 언제든 다시 만든다.

    uv run python -m scripts.sweep_place_candidates
    uv run python -m scripts.sweep_place_candidates 0.45   # 어둡기 컷 조정
"""

from __future__ import annotations

import json
import sys

import numpy as np

from scripts.fetch_kakao_places import Query, collect, open_session
from server import path
from server.core import darkness, parking, places

# --- 상수 --------------------------------------------------------------------

#: 순회 범위. `fetch_kakao_places` 와 같은 네모.
BBOX = (33.10, 126.10, 33.60, 127.00)

#: 좌표 유효 범위. `core.lamps`·`core.parking` 과 같은 경계 — 추자면은 빠진다.
_LAT_RANGE = (33.0, 33.7)
_LON_RANGE = (126.0, 127.1)

#: 긁을 키워드. 밤에 차를 대고 하늘을 볼 수 있는 자리가 나올 만한 것들이다.
#: 카테고리 코드가 없어 전부 키워드 검색이라 군더더기가 섞인다 — 거르는 것은
#: 아래 `_JUNK` 와 사람 검토가 한다.
KEYWORDS = (
    "오름", "전망대", "자연휴양림", "해수욕장", "포구", "목장", "야영장",
    "숲길", "곶자왈", "등대", "저수지", "삼거리", "쉼터", "정자", "방파제",
    "수목원", "천문대", "유적지", "공원", "휴게소",
)

#: 관측지가 될 수 없는 것. 사유 농장(농장·농원)은 사유지 배제에 걸리고,
#: 화장실·관리사무소 같은 부속 항목은 대표가 아니라 묶음의 근거로만 쓴다.
_JUNK = (
    # 숙박·상업·시설
    "펜션", "충전소", "기념비", "카페", "식당", "호텔", "리조트", "민박", "게스트",
    "풀빌라", "아파트", "마트", "주유소", "정비", "병원", "학교", "교회", "어린이집",
    "마을회관", "묘지", "추모", "희생자", "학살", "부동산", "아울렛", "박물관",
    # 음식점 — '쉼터'·'휴게소' 키워드에 상호로 걸려 들어온다
    "한식", "중국요리", "일식", "분식", "치킨", "회", "해물", "생선", "국수",
    "슈퍼마켓", "편의점", "매점",
    # 사유 생산시설 — 사유지 배제(plan.md P9)
    "농장", "농원", "양식업", "낙농업", "축사",
    # 부속 항목 — 대표가 아니라 묶음의 근거로만 쓴다
    "안내소", "관리사무소", "화장실", "전기차", "놀이터",
    # 한라산국립공원은 야간 입산이 통제된다. 어리목·영실·관음사 일대가 어둡기
    # 상위를 차지하지만 밤에 들어갈 수 없어 후보가 되지 못한다.
    "국립공원",
)

#: 대표 이름으로 삼기 좋은 말 / 부속 항목을 가리키는 말.
_PLACE_WORDS = ("오름", "악", "봉", "휴양림", "야영장", "캠핑장", "목장", "전망대",
                "해수욕장", "해변", "포구", "등대", "저수지", "숲길", "곶자왈", "공원")
_SUB_WORDS = ("화장실", "취사장", "관리사무소", "매점", "축구장", "놀이마당", "대피소",
              "입구", "출구", "주차장", "비", "탑", "당", "영지", "휴게소")

#: 접근 기준. 주차 지점이 이보다 멀면 '차를 어디 세우나'가 답이 안 되고,
#: 주행 가능 도로가 이보다 멀면 초행 야간 운전으로 닿을 수 없다.
PARKING_M = 500
ROAD_M = 300

#: 같은 곳으로 볼 거리. 시설 하나가 여러 점으로 등록된 것을 묶는다.
CLUSTER_KM = 0.4

#: 기본 어둡기 컷. `core.darkness` 의 등급 상한 경계(0.35 이하 제한 없음 /
#: 0.60 이하 '양호')와 큐레이션 최하위(저지오름 0.481) 사이에 둔다.
DEFAULT_CUT = 0.40

#: 위도 1도의 거리(km) — `core.lamps` 와 같은 값. cos 는 제주 중위도(33.4°).
_KM_PER_DEG = 111.19492664455873
_COS_LAT = 0.836

#: 도로로 치지 않는 등급. track 은 농로·임도, service 는 사유 진입로다.
_NOT_DRIVABLE = ("track", "service", "path", "footway", "steps")

OUT = path.OUTPUTS / "place_candidates.json"


# --- 1. 수집 ------------------------------------------------------------------

def sweep(session) -> dict[str, dict]:
    """키워드별 전수 순회. 카카오 장소 id 로 중복을 없앤다."""
    found_all: dict[str, dict] = {}
    for keyword in KEYWORDS:
        found: dict[str, dict] = {}
        truncated = collect(session, Query(keyword=keyword), BBOX, found)
        for doc_id, doc in found.items():
            found_all.setdefault(doc_id, doc | {"kw": keyword})
        tail = f"  (잘림 {len(truncated)})" if truncated else ""
        print(f"  {keyword:8s} {len(found):5d}건{tail}")
    return found_all


def score_all(docs: dict[str, dict]) -> list[dict]:
    """제주 범위 안 장소에 어둡기를 매긴다. 격자 밖(해상)은 뺀다."""
    rows = []
    for doc in docs.values():
        lat, lon = float(doc["y"]), float(doc["x"])
        if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]):
            continue
        if not (_LON_RANGE[0] <= lon <= _LON_RANGE[1]):
            continue
        site = darkness.assess_site(lat, lon)
        if site.score is None:
            continue
        rows.append({
            "id": doc["id"], "name": doc["place_name"], "kw": doc["kw"],
            "lat": lat, "lon": lon,
            "score": round(site.score, 3),
            "sqm": round(site.darkness.sqm, 2),
            "lamps_1km": site.lamps.far,
            "category": doc.get("category_name", ""),
            "address": doc.get("road_address_name") or doc.get("address_name", ""),
            "url": doc.get("place_url", ""),
        })
    return rows


# --- 2. 접근 ------------------------------------------------------------------

def _nearest_m(lat, lon, plat, plon) -> np.ndarray:
    """각 후보에서 점 집합까지의 최근접 거리(m). 청크로 나눠 계산한다."""
    out = np.full(len(lat), np.inf)
    plat, plon = np.asarray(plat), np.asarray(plon)
    for i in range(0, len(plat), 4000):
        chunk_lat, chunk_lon = plat[None, i:i + 4000], plon[None, i:i + 4000]
        dy = (lat[:, None] - chunk_lat) * _KM_PER_DEG
        dx = (lon[:, None] - chunk_lon) * _KM_PER_DEG * _COS_LAT
        out = np.minimum(out, np.sqrt(dy * dy + dx * dx).min(axis=1))
    return out * 1000


def attach_access(rows: list[dict]) -> list[dict]:
    """주차·도로 최근접 거리를 붙이고 기준을 통과한 것만 남긴다."""
    lat = np.array([r["lat"] for r in rows])
    lon = np.array([r["lon"] for r in rows])

    lots = parking.lots()
    kakao_lots = [p for p in places.places() if p.source == "parking"]
    park_m = _nearest_m(
        lat, lon,
        [p.lat for p in lots] + [p.lat for p in kakao_lots],
        [p.lon for p in lots] + [p.lon for p in kakao_lots],
    )
    print(f"  주차 지점 {len(lots) + len(kakao_lots)}곳"
          f" (공영 {len(lots)} + 카카오 {len(kakao_lots)})")

    road = np.load(path.ROAD_DARKNESS, allow_pickle=True)
    drivable = ~np.isin(road["way_class"][road["way"]], _NOT_DRIVABLE)
    road_m = _nearest_m(
        lat, lon,
        (road["alat"][drivable] + road["blat"][drivable]) / 2,
        (road["alon"][drivable] + road["blon"][drivable]) / 2,
    )
    print(f"  주행 가능 도로 세그먼트 {int(drivable.sum())}개 / {len(drivable)}개")

    keep = []
    for row, pm, rm in zip(rows, park_m, road_m):
        row["parking_m"], row["road_m"] = round(float(pm)), round(float(rm))
        if row["parking_m"] <= PARKING_M and row["road_m"] <= ROAD_M:
            keep.append(row)
    return keep


# --- 3. 묶기 ------------------------------------------------------------------

def _rank(row: dict) -> tuple:
    """작을수록 대표에 가깝다 — 장소 자체 > 부속시설, 짧은 이름 > 긴 이름."""
    name = row["name"]
    return (any(w in name for w in _SUB_WORDS),
            not any(w in name for w in _PLACE_WORDS),
            len(name), row["score"])


def cluster(rows: list[dict]) -> list[dict]:
    """근접 묶음마다 대표 하나. 부속 항목은 주차 좌표·화장실 근거로 붙인다."""
    groups: list[list[dict]] = []
    for row in sorted(rows, key=lambda r: r["score"]):
        for group in groups:
            head = group[0]
            dy = (row["lat"] - head["lat"]) * _KM_PER_DEG
            dx = (row["lon"] - head["lon"]) * _KM_PER_DEG * _COS_LAT
            if (dy * dy + dx * dx) ** 0.5 < CLUSTER_KM:
                group.append(row)
                break
        else:
            groups.append([row])

    out = []
    for group in groups:
        head = min(group, key=_rank)
        lots = [g for g in group if "주차장" in g["name"]]
        camps = [g for g in group if "야영장" in g["name"] or "캠핑장" in g["name"]]
        row = dict(head, members=len(group),
                   member_names=[g["name"] for g in group][:12])
        if lots:
            best = min(lots, key=lambda g: g["score"])
            row["parking_point"] = {"name": best["name"],
                                    "lat": best["lat"], "lon": best["lon"]}
        if any("화장실" in g["name"] for g in group):
            row["toilet_on_site"] = True
        if camps:
            row["campsite"] = True
        out.append(row)
    return sorted(out, key=lambda r: r["score"])


def is_junk(row: dict) -> bool:
    """관측지가 될 수 없는 분류인가."""
    return any(word in f"{row['name']} {row['category']}" for word in _JUNK)


# --- 실행 ---------------------------------------------------------------------

def main() -> None:
    cut = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CUT
    session, key_name = open_session()
    print(f"키: {key_name} · 어둡기 컷 {cut}\n[1] 수집")

    docs = sweep(session)
    rows = score_all(docs)
    print(f"  중복 제거 {len(docs)}건 → 제주 범위·격자 안 {len(rows)}건\n[2] 접근")

    reachable = attach_access(rows)
    print(f"  주차 {PARKING_M}m · 도로 {ROAD_M}m 통과 {len(reachable)}건\n[3] 묶기")

    groups = cluster(reachable)
    usable = [g for g in groups if not is_junk(g)]
    print(f"  {len(reachable)}건 → {len(groups)}묶음 → 분류 정리 후 {len(usable)}묶음")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(usable, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")

    for step in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50):
        n = sum(g["score"] <= step for g in usable)
        print(f"    score ≤ {step:.2f}: {n:4d}묶음")

    picked = [g for g in usable if g["score"] <= cut]
    print(f"\n--- 컷 {cut} 통과 {len(picked)}묶음 ---")
    print(f"{'점수':>6s} {'주차m':>5s} {'가로등':>5s} 표식 {'이름':24s} 분류")
    for g in picked:
        mark = ("P" if "parking_point" in g else " ") \
             + ("T" if g.get("toilet_on_site") else " ") \
             + ("C" if g.get("campsite") else " ")
        kind = g["category"].split(" > ")[-1] if g["category"] else g["kw"]
        print(f"{g['score']:6.3f} {g['parking_m']:5d} {g['lamps_1km']:5d} {mark}  "
              f"{g['name'][:24]:24s} {kind[:16]}")
    print(f"\n전체 {len(usable)}묶음 → {OUT}")
    print("표식: P=주차좌표 T=현장화장실 C=야영장")


if __name__ == "__main__":
    main()
