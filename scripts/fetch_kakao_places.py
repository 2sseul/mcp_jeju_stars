"""카카오 로컬 API 로 제주 장소를 긁어 CSV 로 남긴다 (배치, 1회성).

`data/car_parking` 의 공공데이터는 **공영주차장만** 담고 있다. 관측지 후보로 쓰려면
공원·휴게소·전망대처럼 밤에 차를 대고 하늘을 볼 수 있는 자리가 더 필요한데, 그건
카카오맵에서 검색해야 나온다. 이 스크립트가 그 검색을 사람 대신 전수로 돌린다.

**받은 결과는 CSV 로만 남긴다.** 엔진은 실행 중에 카카오를 부르지 않는다 — 판정
경로의 egress 를 늘리지 않는다는 규율(`decisions.md` §2.10)이라, 네트워크는 이
배치에서 끝나고 이후로는 정적 파일만 읽는다. 그래서 `server/clients/` 가 아니라
`scripts/` 에 있다.

전수로 긁는 방법 — 45건 벽을 사분할로 넘는다
--------------------------------------------------------------------------
카카오 로컬 검색은 한 질의에서 **45건**만 준다. `page` 가 1~45 라 675건처럼 읽히지만
실제로 넘겨주는 것은 `meta.pageable_count`(최대 45)까지고, size=15 로 물으면 3페이지
째에 `is_end` 가 선다 — 검색된 총수(`total_count`)가 514여도 그렇다. 제주를 원 하나로
물으면 주차장만 수천 건이라 45건에서 잘린다. 그래서 제주를 네모로 잘라 각 네모를
감싸는 원으로 묻고, **`total_count` 가 45를 넘으면 그 네모를 넷으로 쪼개** 다시 묻는다.
조밀한 도심만 깊이 들어가고 한산한 중산간은 한 번에 끝난다.

원 반경은 API 상한이 20km 라, 처음 몇 단계는 결과와 무관하게 무조건 쪼갠다.
겹치는 원이 같은 장소를 여러 번 주므로 **place id 로 중복을 제거**한다.

한 대상에 질의가 여럿일 수 있다 — 주차장이 그렇다. 카테고리 코드 PK6 로만 물으면
관광지·문화시설 코드로 등록된 "○○주차장"이 빠지고(카카오맵 웹 검색 2,345건 대비
639건), 이름으로만 물으면 이름에 '주차장'이 없는 PK6 가 빠진다. 둘 다 물어 place
id 로 합친 것을 한 CSV 로 남긴다.

끝까지 쪼갰는데도 675를 넘으면 그 칸은 잘린 채로 남는다 — 그 사실을 **로그로
찍는다**. 조용히 자르면 '전수 수집'으로 읽히기 때문이다.

실행 — 키보다 **도메인 등록**이 관문이다
--------------------------------------------------------------------------
카카오는 호출자를 밝히는 `KA` 헤더를 요구하고, 접근 통제는 앱에 등록된 **Web
도메인**이 한다. 그래서 키가 유효해도 그 앱에 `http://localhost:8765` 가 등록돼
있지 않으면 거부된다. `.env` 의 REST 키·JavaScript 키를 차례로 시험해 되는 쪽을
쓰고, 어느 쪽이 통과했는지 찍는다.

    uv run python -m scripts.fetch_kakao_places              # 전부
    uv run python -m scripts.fetch_kakao_places park rest    # 골라서

결과 → `data/kakao_places/{키}.csv` (UTF-8 BOM — 엑셀에서 바로 열린다)

출처 표기: 카카오맵 (Kakao Corp.). 재배포·상업적 이용은 카카오 서비스 약관을 따른다.
"""

from __future__ import annotations

import csv
import math
import sys
import time
from dataclasses import dataclass

import requests

from scripts import env
from server import path

# --- 상수 --------------------------------------------------------------------

_BASE = "https://dapi.kakao.com/v2/local/search"

#: 쓸 수 있는 키. 앞에서부터 시도한다 — 되는 쪽을 골라 쓰고 어느 쪽을 썼는지 찍는다.
_KEY_VARS = ("KAKAO_REST_API_KEY", "KAKAO_JAVASCRIPT_API_KEY")

#: 카카오에 밝히는 호출 출처. **등록된 Web 도메인과 정확히 같아야 한다.**
#: 검토 도구(`review_parking.py`)가 쓰는 주소와 같은 값이라 한 번만 등록하면 된다.
_ORIGIN = "http://localhost:8765"

#: 호출자 식별 헤더. 이게 없으면 키가 맞아도 401 이다
#: ("KA Header is required but neither os nor origin field is given").
#: `os` 는 카카오가 아는 값이어야 해서 python 을 적으면 거부당한다 — 그래서
#: **도메인 등록으로 접근을 통제하는 web 호출**로 밝히고 origin 을 함께 보낸다.
_KA_HEADER = f"sdk/1.0.0 os/javascript origin/{_ORIGIN}"

#: 한 질의로 받아낼 수 있는 상한 — **45건**(`meta.pageable_count` 상한). 넘으면
#: 네모를 쪼갠다. `page` 파라미터가 45까지라 675건으로 읽기 쉬운데, 실제로는
#: size=15 기준 3페이지에서 `is_end` 가 선다(위 모듈 설명 참조).
PAGE_SIZE = 15
FETCH_CAP = 45
MAX_PAGE = FETCH_CAP // PAGE_SIZE

#: 원 반경 상한(m). API 사양. 이보다 큰 네모는 결과와 무관하게 쪼갠다.
MAX_RADIUS_M = 20_000

#: 사분할 최대 깊이. 반경 상한 때문에 실제 질의는 깊이 2(약 14km 대 21km 네모)에서
#: 시작하니, 10단계면 한 칸이 약 110m 대 160m 다 — 그 안에 주차장이 45곳 넘게 등록된
#: 자리는 제주에 없다. 더 깊이 가야 하는 칸이 나오면 아래 '잘림' 로그가 알려준다.
MAX_DEPTH = 10

#: 위도 1도의 거리(km) — `core.lamps` 와 같은 값(평균 지구 반경 6371.0088 km).
KM_PER_DEG = 111.19492664455873

#: 검색 범위. 제주 공식 행정구역(`decisions.md` §1.6)에 여유를 준 값 —
#: 원이 네모보다 크므로 어차피 밖도 걸린다. 저장 단계에서 다시 거른다.
_BBOX = (33.10, 126.10, 33.60, 127.00)   # (남, 서, 북, 동)

#: 저장 좌표 유효 범위. `core.lamps`·`core.parking` 과 같은 경계라
#: 세 데이터가 같은 지도에서 어긋나지 않는다. 추자면(≈33.95°N)은 여기서 빠진다.
_LAT_RANGE = (33.0, 33.7)
_LON_RANGE = (126.0, 127.1)

#: 요청 간 간격(초)·재시도. 운영값 — 개인 키의 초당 한도를 건드리지 않을 만큼만.
_PAUSE_S = 0.06
_RETRIES = 5

_COLUMNS = (
    "id", "place_name", "category_name", "category_group_code",
    "address_name", "road_address_name", "phone", "place_url", "lat", "lon",
)


@dataclass(frozen=True)
class Query:
    """카카오에 던지는 질의 하나.

    카테고리 코드가 있으면 코드로 묻는다(분류가 카카오 쪽에서 확정돼 정확하다).
    코드가 없는 것은 키워드로 묻는다 — 대신 이름에 그 말이 들어간 엉뚱한 곳도
    섞이므로, 걸러내는 것은 사람이 검토할 때 한다.
    """

    category: str = ""
    keyword: str = ""

    def __str__(self) -> str:
        return self.category or self.keyword


@dataclass(frozen=True)
class Target:
    """긁을 대상 하나 — 질의 여럿을 합쳐 CSV 한 장으로 남긴다."""

    key: str
    label: str
    queries: tuple[Query, ...]


TARGETS = (
    # 주차장은 코드와 이름 어느 쪽에도 전부가 담기지 않는다. PK6 로만 물으면 관광지·
    # 문화시설 코드로 등록된 "○○주차장"이 빠지고, 이름으로만 물으면 이름에 '주차장'이
    # 없는 PK6 가 빠진다. 둘 다 물어 id 로 합친다.
    Target("parking", "주차장", (Query(category="PK6"), Query(keyword="주차장"))),
    Target("park", "공원", (Query(keyword="공원"),)),
    Target("rest_area", "휴게소", (Query(keyword="휴게소"),)),
    # 관측지에서 필요한 가게는 **밤에 열려 있는 곳**이라 편의점이 사실상 전부다.
    # 카테고리 코드가 있어 분류가 카카오 쪽에서 확정된다(키워드 검색의 군더더기 없음).
    Target("store", "편의점", (Query(category="CS2"),)),
)


# --- API ---------------------------------------------------------------------

#: 지금까지 보낸 요청 수. 45건 상한을 사분할로 넘느라 수천 번 부르는 동안 화면이
#: 아무 말도 안 하면 멈춘 것과 구분되지 않아, 이걸로 살아 있음을 알린다.
_calls = 0
_PROGRESS_EVERY = 500


def _request(session: requests.Session, query: Query, lat: float, lon: float,
             radius: int, page: int) -> dict:
    """한 페이지. 429·5xx 는 지수 백오프로 다시 시도한다."""
    global _calls
    _calls += 1
    if _calls % _PROGRESS_EVERY == 0:
        print(f"    … {_calls:,} 요청", flush=True)

    if query.category:
        url = f"{_BASE}/category.json"
        params = {"category_group_code": query.category}
    else:
        url = f"{_BASE}/keyword.json"
        params = {"query": query.keyword}
    params |= {
        "x": f"{lon:.6f}", "y": f"{lat:.6f}",
        "radius": str(radius), "page": str(page), "size": str(PAGE_SIZE),
        "sort": "distance",
    }

    for attempt in range(_RETRIES):
        response = session.get(url, params=params, timeout=10)
        if response.status_code == 200:
            time.sleep(_PAUSE_S)
            return response.json()
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(_PAUSE_S * (2 ** attempt) + 0.5)
            continue
        raise SystemExit(
            f"카카오 API {response.status_code}: {response.text[:200]}\n"
            "  키가 REST API 키인지, 사용량 한도를 넘지 않았는지 확인하세요."
        )
    raise SystemExit(f"카카오 API 재시도 {_RETRIES}회 실패 ({query})")


def _circle(bbox: tuple[float, float, float, float]) -> tuple[float, float, int]:
    """네모를 감싸는 원 (중심 위도, 중심 경도, 반경 m). 모서리까지 덮는다."""
    south, west, north, east = bbox
    lat = (south + north) / 2
    lon = (west + east) / 2
    half_ns = (north - south) / 2 * KM_PER_DEG
    half_ew = (east - west) / 2 * KM_PER_DEG * math.cos(math.radians(lat))
    return lat, lon, int(math.hypot(half_ns, half_ew) * 1000) + 1


def _quarters(bbox: tuple[float, float, float, float]) -> list[tuple]:
    south, west, north, east = bbox
    mid_lat, mid_lon = (south + north) / 2, (west + east) / 2
    return [
        (south, west, mid_lat, mid_lon), (south, mid_lon, mid_lat, east),
        (mid_lat, west, north, mid_lon), (mid_lat, mid_lon, north, east),
    ]


def collect(session: requests.Session, query: Query, bbox: tuple, found: dict,
            depth: int = 0, truncated: list | None = None) -> list:
    """네모 하나를 긁는다. 상한에 걸리면 넷으로 쪼개 재귀한다."""
    if truncated is None:
        truncated = []
    lat, lon, radius = _circle(bbox)

    # 반경 상한을 넘는 네모는 물어볼 것도 없이 쪼갠다.
    if radius > MAX_RADIUS_M:
        for quarter in _quarters(bbox):
            collect(session, query, quarter, found, depth + 1, truncated)
        return truncated

    first = _request(session, query, lat, lon, radius, 1)
    total = int(first["meta"]["total_count"])
    if total == 0:
        return truncated
    if total > FETCH_CAP:
        if depth < MAX_DEPTH:
            for quarter in _quarters(bbox):
                collect(session, query, quarter, found, depth + 1, truncated)
            return truncated
        truncated.append((bbox, total))     # 더 못 쪼갠다 — 잘린 채로 기록만 남긴다

    page, payload = 1, first
    while True:
        for doc in payload["documents"]:
            found.setdefault(doc["id"], doc)
        if payload["meta"]["is_end"] or page >= MAX_PAGE:
            break
        page += 1
        payload = _request(session, query, lat, lon, radius, page)
    return truncated


# --- 저장 ---------------------------------------------------------------------

def write_csv(target: Target, docs: list[dict]) -> tuple[int, int]:
    """CSV 로 쓴다. (저장 건수, 범위 밖으로 버린 건수)."""
    rows, dropped = [], 0
    for doc in docs:
        try:
            lat, lon = float(doc["y"]), float(doc["x"])
        except (KeyError, TypeError, ValueError):
            dropped += 1
            continue
        if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]):
            dropped += 1
            continue
        if not (_LON_RANGE[0] <= lon <= _LON_RANGE[1]):
            dropped += 1
            continue
        rows.append(
            {
                "id": doc["id"],
                "place_name": doc.get("place_name", ""),
                "category_name": doc.get("category_name", ""),
                "category_group_code": doc.get("category_group_code", ""),
                "address_name": doc.get("address_name", ""),
                "road_address_name": doc.get("road_address_name", ""),
                "phone": doc.get("phone", ""),
                "place_url": doc.get("place_url", ""),
                "lat": f"{lat:.7f}",
                "lon": f"{lon:.7f}",
            }
        )
    rows.sort(key=lambda r: (r["place_name"], r["id"]))

    out = path.KAKAO_PLACES / f"{target.key}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    # 엑셀이 UTF-8 을 알아보게 BOM 을 붙인다(공공데이터 원본 파일들과 같은 규약).
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), dropped


def open_session() -> tuple[requests.Session, str]:
    """쓸 수 있는 키를 찾아 세션을 연다. (세션, 쓰인 환경변수 이름).

    키마다 소속 앱이 다를 수 있고, 접근 통제는 **앱에 등록된 Web 도메인**이 한다.
    그래서 키가 유효해도 도메인이 안 맞으면 거부된다 — 어느 쪽이 통과했는지 밝혀
    두지 않으면 다음에 같은 자리에서 또 막힌다.
    """
    probe = {
        "category_group_code": "PK6", "x": "126.55", "y": "33.35",
        "radius": "1000", "size": "1",
    }
    problems = []
    for name in _KEY_VARS:
        key = env.read(name)
        if not key:
            problems.append(f"  {name}: 없음")
            continue
        session = requests.Session()
        session.headers["Authorization"] = f"KakaoAK {key}"
        session.headers["KA"] = _KA_HEADER
        response = session.get(f"{_BASE}/category.json", params=probe, timeout=10)
        if response.status_code == 200:
            return session, name
        problems.append(f"  {name}: {response.status_code} {response.text[:120]}")

    raise SystemExit(
        "카카오 로컬 API 를 쓸 수 있는 키가 없습니다.\n"
        + "\n".join(problems)
        + f"\n  → 카카오 콘솔 [플랫폼 → Web] 에 {_ORIGIN} 을 등록한 앱의 키를 쓰세요."
    )


def main() -> None:
    session, key_name = open_session()
    print(f"키: {key_name} · origin: {_ORIGIN}")

    wanted = sys.argv[1:]
    targets = [t for t in TARGETS if not wanted or t.key in wanted]
    if not targets:
        raise SystemExit(
            "그런 대상이 없습니다. 고를 수 있는 것: "
            + ", ".join(f"{t.key}({t.label})" for t in TARGETS)
        )

    for target in targets:
        print(f"[{target.label}] 수집 중…", flush=True)
        found: dict[str, dict] = {}
        truncated: list = []
        for query in target.queries:
            before = len(found)
            collect(session, query, _BBOX, found, truncated=truncated)
            print(f"  {query} → 누적 {len(found):,}곳 (+{len(found) - before:,})",
                  flush=True)
        saved, dropped = write_csv(target, list(found.values()))

        out = path.KAKAO_PLACES / f"{target.key}.csv"
        print(f"  {out}  →  {saved:,}곳" + (f" (범위 밖 {dropped:,}곳 제외)"
                                            if dropped else ""))
        for bbox, total in truncated:
            print(
                f"  ⚠ 잘림: {bbox} 안에 {total:,}건이 있는데 {FETCH_CAP}건까지만 "
                "받았습니다(사분할 한계). MAX_DEPTH 를 올리세요."
            )


if __name__ == "__main__":
    main()
