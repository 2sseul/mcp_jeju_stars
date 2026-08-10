"""관측지 좌표 대조 — 그 좌표가 정말 그 장소인가 (배치, 읽기 전용).

`data/jeju_spots.json` 의 좌표는 출처가 섞여 있다. 자동 발굴분(`discovery`)은
카카오맵 장소 좌표를 그대로 받아 소수 15자리까지 있지만, 웹서치 큐레이션분은
**주소를 보고 사람이 찍은 추정치**라 소수 4자리(≈10m 격자)에서 끊긴다. 실제로
`meta.coordinate_note` 는 용눈이오름·다랑쉬오름이 위키 좌표 중복 오류였다고
적어 두고 있다.

좌표가 몇백 m 어긋나면 무슨 일이 생기나 — **판정이 조용히 바뀐다**. 어둡기 세
신호 중 가로등은 반경 100m·1km 로 세고(`core.lamps`), 화장실은 200m 로 본다.
오름 정상 대신 주차장이나 도로변을 가리키고 있으면 "가로등 0개"가 "23m 앞에
있음"이 된다. 값이 이상해 보이지 않으므로 **눈으로는 안 잡힌다**.

그래서 이름을 카카오맵에 다시 물어 좌표를 맞춰 본다. 이 스크립트는 **읽기만
한다** — 무엇을 고칠지는 사람이 정한다(`scripts/edit_spots.py` 의 작업 목록이 된다).

무엇을 믿을 수 없나
--------------------------------------------------------------------------
검색은 이름만 보므로 같은 이름의 카페·식당이 먼저 걸리기도 한다. 그래서 판정하지
않고 **맞춘 장소의 이름·분류·주소를 그대로 함께 찍는다** — 300m 어긋난 것이
좌표 오류인지 검색 오류인지는 그 줄을 봐야 갈린다.

실행 — `fetch_kakao_places.py` 와 같은 키·도메인 등록을 쓴다:

    uv run python -m scripts.check_spot_coords            # 전부
    uv run python -m scripts.check_spot_coords 300        # 300m 넘게 어긋난 것만
"""

from __future__ import annotations

import json
import math
import sys
import time

from scripts.fetch_kakao_places import _BASE, _PAUSE_S, _RETRIES, open_session
from server import path
from server.core import lamps

#: 이 거리를 넘으면 화면에 띄운다(m). 오름·해변은 넓어서 몇백 m 는 같은 장소일 수
#: 있다 — 판정 반경(가로등 100m)보다 크게 잡아 **정말 다른 자리**만 남긴다.
DEFAULT_FLAG_M = 300.0

#: 검색을 가둘 사각형 — 카카오 `rect` 는 (서, 남, 동, 북) 경도·위도 순이다.
#: 제주 밖 동명이인(예: 육지의 같은 이름 공원)을 애초에 빼려는 것이다.
_RECT = "126.10,33.10,127.00,33.60"


def _distance_m(lat: float, lon: float, lat2: float, lon2: float) -> float:
    dy = (lat2 - lat) * lamps.KM_PER_DEG
    dx = (lon2 - lon) * lamps.KM_PER_DEG * math.cos(math.radians(lat))
    return math.hypot(dx, dy) * 1000.0


def query_of(name: str) -> str:
    """검색어 — 괄호 안 보충 설명은 뗀다.

    '우도(우도봉 일대)'처럼 어디를 말하는지 사람에게 적어 둔 것은 검색어로는
    잡음이다. 괄호를 뗀 '우도'가 카카오가 아는 이름이다.
    """
    head, sep, _ = name.partition("(")
    return (head if sep else name).strip()


def search(session, name: str) -> list[dict]:
    """이름으로 제주 안 장소를 찾는다. 정확도 순 상위 몇 개."""
    query = query_of(name)
    for attempt in range(_RETRIES):
        response = session.get(
            f"{_BASE}/keyword.json",
            params={"query": query, "rect": _RECT, "size": 5, "sort": "accuracy"},
            timeout=10,
        )
        if response.status_code == 200:
            time.sleep(_PAUSE_S)
            return response.json().get("documents") or []
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(_PAUSE_S * (2 ** attempt) + 0.5)
            continue
        raise SystemExit(f"카카오 API {response.status_code}: {response.text[:200]}")
    raise SystemExit(f"카카오 API 재시도 {_RETRIES}회 실패 ({query})")


def pick(name: str, documents: list[dict]) -> dict | None:
    """검색 결과 중 이름이 가장 잘 맞는 것.

    정확도 1위를 그냥 쓰지 않는다 — '금오름'을 물으면 '금오름 카페'가 먼저 오기도
    한다. 이름이 **똑같은 것 → 그 이름으로 시작하는 것 → 1위** 순으로 고른다.
    """
    query = query_of(name)
    for document in documents:
        if document.get("place_name", "").strip() == query:
            return document
    for document in documents:
        if document.get("place_name", "").strip().startswith(query):
            return document
    return documents[0] if documents else None


def main() -> None:
    flag_m = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FLAG_M
    spots = json.loads(path.SPOTS.read_text(encoding="utf-8"))["spots"]
    session, key_name = open_session()
    print(f"관측지 {len(spots):,}곳 · 키: {key_name} · 기준 {flag_m:g}m 초과")

    rows, missing = [], []
    for i, spot in enumerate(spots, start=1):
        found = pick(spot["name_ko"], search(session, spot["name_ko"]))
        if found is None:
            missing.append(spot)
            continue
        rows.append(
            {
                "name": spot["name_ko"],
                "confidence": spot.get("coord_confidence", "?"),
                "auto": "discovery" in spot,
                "lat": spot["lat"],
                "lon": spot["lon"],
                "distance": _distance_m(
                    spot["lat"], spot["lon"], float(found["y"]), float(found["x"])
                ),
                "matched": found.get("place_name", ""),
                "category": found.get("category_name", ""),
                "address": (found.get("road_address_name")
                            or found.get("address_name", "")),
                "hitLat": float(found["y"]),
                "hitLon": float(found["x"]),
            }
        )
        if i % 25 == 0:
            print(f"  {i:,}/{len(spots):,}", flush=True)

    rows.sort(key=lambda r: -r["distance"])
    flagged = [r for r in rows if r["distance"] > flag_m]

    print(f"\n검색된 {len(rows):,}곳 중 {len(flagged):,}곳이 "
          f"{flag_m:g}m 넘게 어긋난다\n")
    for r in flagged:
        tag = "자동" if r["auto"] else r["confidence"]
        print(f"{r['distance']:8.0f}m  {r['name']}  [{tag}]")
        print(f"          파일 {r['lat']:.6f}, {r['lon']:.6f}")
        print(f"          검색 {r['hitLat']:.6f}, {r['hitLon']:.6f}"
              f"  {r['matched']} · {r['category']}")
        print(f"          {r['address']}")

    if missing:
        print(f"\n카카오맵에서 찾지 못한 {len(missing):,}곳:")
        for spot in missing:
            print(f"  {spot['name_ko']} ({spot.get('coord_confidence', '?')})")

    close = len(rows) - len(flagged)
    print(f"\n{flag_m:g}m 안 {close:,}곳 · 초과 {len(flagged):,}곳 · "
          f"못 찾음 {len(missing):,}곳")
    print("이 스크립트는 파일을 고치지 않는다 — "
          "`uv run python -m scripts.edit_spots` 로 지도에서 확인하고 옮긴다.")


if __name__ == "__main__":
    main()
