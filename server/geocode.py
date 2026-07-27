"""주소·지명 → 좌표 변환(지오코딩) provider.

Photon(Komoot, OSM 기반, 오픈소스·키 불필요)로 구현한다. Nominatim 대비 퍼지
매칭이 강해 "1100고지" 같은 비정형 지명을 잘 잡는다. 그래도 정확 매칭이 안 되는
경우("한라산 1100고지")를 위해 검색어 변형(접두 지역어 제거·토큰 조합) fallback 을
둔다. 결과는 제주 범위 안인지 검증한다.

프로덕션에선 Photon 을 Docker 로 self-host(한국 OSM extract)하면 완전 오프라인·
무외부의존이 된다. 개발 중엔 공개 엔드포인트를 쓴다.

Photon 도 못 찾는 경우는 이 서버가 처리하지 않는다 — Host LLM 이 웹검색 MCP 등으로
좌표를 구해 evaluate_spot(lat, lon) 을 호출하는 오케스트레이션에 맡긴다(MCP 표준,
서버 간 결합 회피).

교체 시 `geocode(query) -> GeocodeResult | None` 시그니처만 지키면 호출부 불변.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

_URL = "https://photon.komoot.io/api/"
_UA = "mcp-jeju-star/0.1 (Jeju stargazing MCP)"

# 제주 bbox(minLon,minLat,maxLon,maxLat) 와 편향 중심
_LAT_MIN, _LAT_MAX = 33.19, 33.57
_LON_MIN, _LON_MAX = 126.14, 126.98
_BBOX = f"{_LON_MIN},{_LAT_MIN},{_LON_MAX},{_LAT_MAX}"
_BIAS_LAT, _BIAS_LON = 33.36, 126.53

# 변형 검색에서 떼어낼 접두 지역어
_PREFIXES = ("한라산 ", "제주특별자치도 ", "제주도 ", "제주시 ", "서귀포시 ", "제주 ")

# 단독으로는 관측지가 아니라 넓은 행정구역·산 전체를 가리키는 일반 지역어.
# 변형 fallback 이 이런 단어로 축약되면(예: '제주 없는장소' → '제주') Photon 이
# 제주 도심 같은 엉뚱한 일반 위치를 반환하고, 그걸 원래 장소로 확정해 버린다.
# 그래서 이 단어들은 변형 후보에서 제외한다(원문 질의 자체가 이 단어면 못 찾은 것으로 둔다).
_GENERIC = frozenset({p.strip() for p in _PREFIXES} | {"제주도", "서귀포", "한라산"})


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    display_name: str
    matched_query: str = ""  # 실제로 매칭된 검색어(원문과 다를 수 있음)


def _variants(query: str) -> list[str]:
    """정확 매칭 실패에 대비한 검색어 변형(우선순위 순, 중복 제거).

    단독 지역어(_GENERIC)로 축약된 변형은 넣지 않는다 — 그런 후보는 원래 장소가
    아니라 제주 일대의 일반 위치를 반환해 오확정을 부른다(리뷰 반영).
    """
    out: list[str] = []

    def add(x: str) -> None:
        x = x.strip()
        if x and x not in _GENERIC and x not in out:
            out.append(x)

    q = query.strip()
    add(q)
    for pre in _PREFIXES:
        if q.startswith(pre):
            add(q[len(pre):])
    toks = q.split()
    if len(toks) >= 2:
        add(" ".join(toks[1:]))   # 첫 토큰 제거 (예: '한라산' 떼기)
        add(" ".join(toks[:-1]))  # 끝 토큰 제거
        add(toks[-1])
        add(toks[0])
    return out[:5]


def _in_jeju(lat: float, lon: float) -> bool:
    return _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX


def _display(props: dict) -> str:
    name = props.get("name") or props.get("street") or ""
    area = props.get("city") or props.get("county") or props.get("district") or props.get("state") or ""
    return f"{name} [{area}]" if area else name


def _query(text: str, use_bbox: bool, timeout: float) -> tuple[float, float, str] | None:
    params = {
        "q": text,
        "limit": 1,
        "lang": "default",  # 로컬 언어(한국어) 이름
        "lat": _BIAS_LAT,
        "lon": _BIAS_LON,
    }
    if use_bbox:
        params["bbox"] = _BBOX
    url = _URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    feats = data.get("features") or []
    if not feats:
        return None
    f = feats[0]
    lon, lat = f["geometry"]["coordinates"][:2]
    return float(lat), float(lon), _display(f.get("properties", {}))


def geocode(query: str, timeout: float = 12.0) -> GeocodeResult | None:
    """주소·지명을 제주 우선으로 좌표 변환한다.

    1) 원문·변형을 제주 bbox 로 한정해 순서대로 시도,
    2) 모두 실패하면 bbox 없이(편향만) 재시도.
    제주 범위 밖 결과는 버린다. 못 찾으면 None (→ Host 가 웹검색 등으로 폴백).
    """
    variants = _variants(query)
    for use_bbox in (True, False):
        for text in variants:
            hit = _query(text, use_bbox, timeout)
            if hit and _in_jeju(hit[0], hit[1]):
                return GeocodeResult(hit[0], hit[1], hit[2], matched_query=text)
    return None
