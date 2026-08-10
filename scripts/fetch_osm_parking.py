"""OSM `amenity=parking` 을 좌표 CSV 로 받는다 (배치, 다시 돌려도 안전).

왜 공영 표준데이터만으로 부족한가
--------------------------------------------------------------------------
`core/parking.py` 가 쓰는 공영주차장 표준데이터 1,557곳은 **지자체가 운영하는
주차장 대장**이다. 그런데 관측지 후보로 실제로 쓰이는 자리 — 오름 초입,
해변, 휴양림, 전망대 주차장 — 은 시설 부속이라 그 대장에 없다. 실제로 OSM
1,082곳 중 **641곳은 공영주차장 100m 안에 아무것도 없다**(용눈이오름·사려니
숲길·수월봉·산굼부리·절물휴양림·거린사슴전망대 등).

그래서 두 데이터는 겹치는 목록이 아니라 **서로 다른 축**이다. 공영 쪽은
"구획수·요금이 대장으로 확인되는 곳", OSM 쪽은 "사람이 지도에 그려 둔,
차를 실제로 세우는 곳". 합치지 않고 따로 싣는 이유가 이것이다.

무엇이 없는가 — 이 데이터의 한계
--------------------------------------------------------------------------
OSM 은 자원자가 채우는 지도라 태그가 성깁니다. 1,082곳 기준으로

    이름       80곳(+ `name:ko` 59곳)  ← 나머지 92%는 이름이 없다
    access     90곳                     ← 사유지·고객전용 여부를 대개 모른다
    fee        57곳
    lit         1곳                     ← **야간 조명 정보는 없다고 봐야 한다**

`lit` 이 사실상 비어 있으므로 이 파일로 "그 주차장이 밤에 밝은가"를 답할 수
없다. 그 질문은 `core/lamps.py`(가로등)와 어둡기 격자가 답할 몫이다.
`capacity`(20곳)·`surface`(21곳)도 같은 이유로 싣지 않는다 — 20/1,082 는
"대부분 모른다"는 뜻이라 컬럼으로 두면 빈 칸이 값처럼 읽힌다.

좌표
--------------------------------------------------------------------------
주차장은 대부분 **면(way)** 으로 그려져 있다(1,082곳 중 way 1,000 · node 79 ·
relation 3). 면에는 점 좌표가 없으므로 Overpass `out center` 가 주는 **경계
상자 중심**을 쓴다. 주차장 부지 안의 한 점이라 진입로와 최대 수십 m 어긋나는데,
이 데이터를 쓰는 질문("이 근처에 세울 데가 있나")은 그 오차로 뒤집히지 않는다.

수집 범위는 `core/parking.py`·`core/lamps.py` 와 같은 경계 33.0~33.7N /
126.0~127.1E 다 — 추자면은 여기서 빠진다. 같은 지도에 겹쳐 쓰는 축들이라
한쪽에만 있는 지점이 생기면 안 된다.

출처
--------------------------------------------------------------------------
OpenStreetMap contributors, ODbL. Overpass API 로 받는다 — 판정 경로가 아닌
배치에서만 부른다(`decisions.md` §2.10). ODbL 은 **귀속 표기를 요구한다** — 이
파일을 엔진에 물릴 때 `core/parking.py` `SOURCE` 처럼 축어 문자열을 함께 둬야
한다: "주차장(OSM): © OpenStreetMap contributors, ODbL".

어느 인스턴스가 답했나
--------------------------------------------------------------------------
공개 Overpass 는 자주 504 를 내고, 미러(kumi)는 복제가 몇 주씩 밀린 판을 준다.
같은 미러가 호출마다 다른 복제본에 걸리기도 한다 — 실측으로 7/02 판(1,011곳)과
6/12 판(923곳)이 번갈아 나왔다. 그대로 두면 **다시 받을수록 데이터가 낡는다.**

그래서 스냅샷 시각(`timestamp_osm_base`)을 보고 2주보다 낡은 판은
거부한다(`_MAX_AGE_DAYS`). 전부 낡았으면 파일을 건드리지 않고 멈춘다 — 더 나쁜 것으로
덮어쓰는 것이 못 받는 것보다 나쁘다.

실행:
    uv run python -m scripts.fetch_osm_parking
    uv run python -m scripts.fetch_osm_parking --allow-stale  # 낡은 판이라도
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timezone

import requests

from server import path

#: Overpass 엔드포인트. 앞의 것이 rate limit 에 걸리면 다음으로 넘어간다 —
#: 공개 인스턴스라 IP 단위 쿼터가 있고, 한 번 막히면 몇 분씩 열리지 않는다.
_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

#: 서비스 범위. `core/parking.py` `_LAT_RANGE`·`_LON_RANGE` 와 같은 값이다.
_BBOX = (33.0, 126.0, 33.7, 127.1)

#: `out center` 는 면의 경계상자 중심을 준다. 점(node)은 자기 좌표를 그대로 쓴다.
_QUERY = """[out:json][timeout:300];
nwr["amenity"="parking"]({},{},{},{});
out tags center;"""

#: 저장 규약 — UTF-8(BOM). `scripts/normalize_csv.py` 가 정한 것과 같다.
_ENCODING = "utf-8-sig"

#: Overpass 공개 인스턴스는 **User-Agent 를 요구한다** — requests 기본값으로 부르면
#: overpass-api.de 는 406, kumi 는 429 로 끊는다. 무료 자원을 쓰는 쪽이 누구인지
#: 밝히라는 뜻이라, 프로젝트 이름과 연락처를 적는다.
_HEADERS = {
    "User-Agent": "mcp-jeju-star/0.1 (Jeju night-sky observation MCP; "
                  "https://github.com/2sseul/mcp_jeju_star)",
}

#: 싣는 칸. 태그가 성겨서(위 docstring) **대부분 채워지거나, 비면 후보를 거르는
#: 뜻이 있는** 것만 남긴다. `capacity`·`surface`·`lit` 은 그래서 빠져 있다.
_FIELDS = ("osm_type", "osm_id", "name", "lat", "lon", "parking", "access", "fee")

_TIMEOUT = 300.0

#: 한 인스턴스를 포기하기까지의 시도 횟수. 504(게이트웨이 타임아웃)는 쿼터가
#: 아니라 그때의 부하라서, 몇 초 뒤 같은 곳이 그냥 답한다.
_TRIES = 3
_RETRY_WAIT = 20.0

#: 이보다 오래된 스냅샷은 받아들이지 않는다. 미러는 복제가 밀리면 몇 주씩
#: 뒤처지고 — 실제로 kumi 는 한 번은 7/02, 다음 호출엔 6/12 판을 줬다 —
#: 그걸 그대로 쓰면 **파일을 새로 받을수록 데이터가 낡는** 일이 벌어진다.
_MAX_AGE_DAYS = 14


def _age_days(base: str) -> float | None:
    """`timestamp_osm_base` 가 지금으로부터 며칠 전인지. 못 읽으면 None."""
    try:
        stamp = datetime.fromisoformat(base.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


def _ask(url: str, query: str) -> tuple[list[dict], str] | None:
    """인스턴스 하나를 (재시도 포함해) 부른다. (원소, 기준시각) 또는 None."""
    for attempt in range(1, _TRIES + 1):
        response = requests.post(
            url, data={"data": query}, headers=_HEADERS, timeout=_TIMEOUT
        )
        # Overpass 는 쿼터 초과·과부하를 **200 에 HTML 본문**으로 돌려주기도 한다.
        # 상태코드만 보면 빈 목록을 정상 응답으로 착각한다.
        try:
            payload = response.json()
            elements = payload["elements"]
        except (ValueError, KeyError):
            print(f"  [실패 {attempt}/{_TRIES}] {url} · {response.status_code}")
            if attempt < _TRIES:
                time.sleep(_RETRY_WAIT)
            continue
        return elements, payload.get("osm3s", {}).get("timestamp_osm_base", "")
    return None


def fetch(allow_stale: bool = False) -> list[dict]:
    """Overpass 에서 `amenity=parking` 원소를 받는다.

    **어느 인스턴스가 답했는지와 그 스냅샷 시각을 반드시 찍고, 낡은 판은 거른다.**
    미러는 본 인스턴스보다 한참 뒤처져 있을 수 있어서(한 달 차이로 주차장 71곳이
    갈렸다), 조용히 넘어가면 오래된 데이터를 최신으로 착각한다. 더 나쁜 것은
    다시 받을 때마다 다른 복제본에 걸려 **개수가 오르내리는** 것이다.
    """
    query = _QUERY.format(*_BBOX)
    stale: list[tuple[float, list[dict], str, str]] = []

    for url in _ENDPOINTS:
        answer = _ask(url, query)
        if answer is None:
            continue
        elements, base = answer
        age = _age_days(base)
        print(f"  {url} · {len(elements):,}곳 (OSM 기준 {base or '?'})")
        if age is not None and age > _MAX_AGE_DAYS:
            print(f"    {age:.0f}일 지난 판이라 건너뜁니다. 다음 인스턴스를 봅니다")
            stale.append((age, elements, base, url))
            continue
        return elements

    if not stale:
        raise SystemExit(
            "Overpass 응답을 받지 못했습니다. 잠시 뒤 다시 실행하세요 "
            "(https://overpass-api.de/api/status 로 쿼터를 볼 수 있습니다)."
        )

    age, elements, base, url = min(stale)
    if not allow_stale:
        raise SystemExit(
            f"쓸 만한 인스턴스가 {_MAX_AGE_DAYS}일 안쪽 판을 주지 않았습니다 "
            f"(가장 새 것이 {url} 의 {base}, {age:.0f}일 전).\n"
            "잠시 뒤 다시 실행하거나, 낡은 판이라도 받으려면 --allow-stale 을 붙이세요."
        )
    print(f"  [--allow-stale] {age:.0f}일 지난 {url} 판을 씁니다")
    return elements


def point(element: dict) -> tuple[float, float] | None:
    """원소의 대표 좌표. 면·관계는 `center`, 점은 자기 좌표. 없으면 None."""
    if element["type"] == "node":
        lat, lon = element.get("lat"), element.get("lon")
    else:
        centre = element.get("center") or {}
        lat, lon = centre.get("lat"), centre.get("lon")
    return (lat, lon) if lat is not None and lon is not None else None


def row(element: dict) -> dict | None:
    """원소 하나 → CSV 한 줄. 좌표가 없으면 None."""
    coords = point(element)
    if coords is None:
        return None
    tags = element.get("tags", {})
    return {
        "osm_type": element["type"],
        "osm_id": element["id"],
        # `name` 이 없고 `name:ko` 만 있는 곳이 있다 — 한국어 이름이 있는데
        # 이름 없음으로 떨어뜨리지 않는다.
        "name": tags.get("name") or tags.get("name:ko", ""),
        "lat": f"{coords[0]:.6f}",
        "lon": f"{coords[1]:.6f}",
        "parking": tags.get("parking", ""),
        "access": tags.get("access", ""),
        "fee": tags.get("fee", ""),
    }


def main() -> None:
    # 출력에는 em dash 를 쓰지 않는다 — 윈도우 콘솔(CP949)이 U+2014 를 못 찍어
    # 출력 자체가 죽는다(`scripts/normalize_csv.py` 가 파일 이름에서 겪은 것과 같다).
    print(f"OSM amenity=parking · {_BBOX[0]}~{_BBOX[2]}N / {_BBOX[1]}~{_BBOX[3]}E")
    elements = fetch(allow_stale="--allow-stale" in sys.argv[1:])

    rows = [r for r in map(row, elements) if r is not None]
    dropped = len(elements) - len(rows)
    if not rows:
        raise SystemExit("좌표가 있는 주차장이 하나도 없습니다 — 쿼리를 확인하세요.")

    # 임시 파일에 쓴 뒤 바꿔치기한다. 중간에 끊겨도 반쪽짜리 CSV 가 남지 않게.
    tmp = path.PARKING_OSM.with_suffix(".csv.tmp")
    with tmp.open("w", encoding=_ENCODING, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path.PARKING_OSM)

    named = sum(1 for r in rows if r["name"])
    kinds = {t: sum(1 for r in rows if r["osm_type"] == t)
             for t in ("way", "node", "relation")}
    print(f"\n{path.PARKING_OSM.relative_to(path.ROOT)} · {len(rows):,}곳")
    print(f"  면 {kinds['way']:,} · 점 {kinds['node']:,} · 관계 {kinds['relation']:,}"
          + (f" (좌표 없어 뺀 것 {dropped:,})" if dropped else ""))
    print(f"  이름 있는 곳 {named:,} ({named / len(rows) * 100:.0f}%) · "
          "나머지는 좌표만 있는 자리다")
    print("  면의 좌표는 경계상자 중심이다 (진입로와 수십 m 어긋난다).")


if __name__ == "__main__":
    main()
