"""공중화장실 CSV 에 위도·경도 컬럼을 채운다 (배치, 다시 돌려도 안전).

공공데이터포털 **전국 공중화장실 표준데이터**는 제주 것만 849행인데 좌표 컬럼이
없다 — 주소뿐이다. 그런데 관측지에서 쓸 질문은 "여기서 걸어갈 데가 있나"라서
반경 판정이 필요하고, 그건 좌표 없이는 못 한다. 그래서 주소를 좌표로 바꿔 **원본
CSV 에 컬럼으로 붙인다**(별도 파일로 빼지 않는다 — 화장실 한 곳의 정보가 두 파일에
나뉘면 다음 사람이 둘을 맞춰 봐야 한다).

받은 좌표는 CSV 로만 남는다. 엔진은 실행 중에 카카오를 부르지 않는다
(`decisions.md` §2.10) — 그래서 이 파일이 `server/clients/` 가 아니라 `scripts/` 다.

어떻게 찾나
--------------------------------------------------------------------------
카카오 **주소검색**(`/v2/local/search/address.json`)에 도로명주소 → 지번주소 순으로
묻는다. 표본 12곳 전수 적중이라 이 두 단계로 충분하다.

원본에는 `제주특별자치도 제주시516로2596 한라생태숲` 처럼 띄어쓰기가 빠지고 건물
이름이 붙은 행이 섞여 있다. 그런 행을 위해 **끝 토큰을 뗀 후보**를 하나 더 둔다 —
단, 뗀 뒤에도 끝이 번지꼴(`2596`·`2-15`)일 때만. 그러지 않으면 `… 제주시` 같은
껍데기가 남아 시청 좌표로 확정돼 버린다(`clients/geocode.py` 가 겪은 함정과 같다).

찾은 좌표는 제주 범위 안인지 확인하고 넣는다. 못 찾은 행은 **빈 칸으로 남긴다** —
아무 좌표나 채우면 반경 200m 판정이 조용히 틀린다. 다시 실행하면 빈 칸만 다시
물으므로, 원본이 갱신돼 행이 늘어도 새 행만 채운다.

실행 — `fetch_kakao_places.py` 와 같은 키·도메인 등록을 쓴다:

    uv run python -m scripts.geocode_toilets
    uv run python -m scripts.geocode_toilets --limit 20   # 조금만 시험해 볼 때
"""

from __future__ import annotations

import csv
import io
import re
import sys
import time

from scripts.fetch_kakao_places import _BASE, _PAUSE_S, _RETRIES, open_session
from server import path

#: 채울 컬럼. 주차장 표준데이터와 같은 이름이라 읽는 쪽이 헷갈리지 않는다.
LAT_COLUMN = "위도"
LON_COLUMN = "경도"

#: 주소가 실린 컬럼 — 묻는 순서다. 도로명이 지번보다 건물 앞에 정확히 떨어진다.
_ADDRESS_COLUMNS = ("소재지도로명주소", "소재지지번주소")

#: 좌표 유효 범위. `core.lamps`·`core.parking`·`core.places` 와 같은 경계.
_LAT_RANGE = (33.0, 33.7)
_LON_RANGE = (126.0, 127.1)

#: 번지꼴 — `2596` · `2-15` · `산 1-3` 의 끝부분. 끝 토큰을 떼도 되는지 판정한다.
_LOT_NUMBER = re.compile(r"\d+(-\d+)?(지선)?$")


def candidates(row: dict) -> list[str]:
    """이 행으로 물어볼 주소 후보 (우선순위 순, 중복 제거)."""
    out: list[str] = []

    def add(text: str) -> None:
        text = text.strip()
        if text and text not in out:
            out.append(text)

    for column in _ADDRESS_COLUMNS:
        address = (row.get(column) or "").strip()
        add(address)
        # 건물 이름이 붙어 있으면 떼고 한 번 더 — 뗀 뒤에도 번지로 끝날 때만.
        head, _, tail = address.rpartition(" ")
        if head and tail and not _LOT_NUMBER.search(tail) and _LOT_NUMBER.search(head):
            add(head)
    return out


def lookup(session, query: str) -> tuple[float, float] | None:
    """주소 하나 → (위도, 경도). 못 찾거나 제주 밖이면 None."""
    for attempt in range(_RETRIES):
        response = session.get(
            f"{_BASE}/address.json", params={"query": query, "size": 1}, timeout=10
        )
        if response.status_code == 200:
            time.sleep(_PAUSE_S)
            break
        if response.status_code in (429, 500, 502, 503, 504):
            time.sleep(_PAUSE_S * (2 ** attempt) + 0.5)
            continue
        raise SystemExit(
            f"카카오 API {response.status_code}: {response.text[:200]}\n"
            "  키와 [플랫폼 → Web] 도메인 등록을 확인하세요."
        )
    else:
        raise SystemExit(f"카카오 API 재시도 {_RETRIES}회 실패 ({query})")

    documents = response.json().get("documents") or []
    if not documents:
        return None
    try:
        lat, lon = float(documents[0]["y"]), float(documents[0]["x"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1]):
        return None
    if not (_LON_RANGE[0] <= lon <= _LON_RANGE[1]):
        return None
    return lat, lon


def has_coords(row: dict) -> bool:
    """이미 좌표가 채워져 있는가 — 다시 묻지 않을 행."""
    try:
        float(row.get(LAT_COLUMN) or "")
        float(row.get(LON_COLUMN) or "")
    except ValueError:
        return False
    return True


def main() -> None:
    limit = 0
    argv = sys.argv[1:]
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    text = path.TOILET.read_bytes().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    columns = list(reader.fieldnames or [])
    rows = list(reader)
    if not columns:
        raise SystemExit(f"{path.TOILET} 를 읽지 못했습니다(헤더 없음).")

    for column in (LAT_COLUMN, LON_COLUMN):
        if column not in columns:
            columns.append(column)

    todo = [row for row in rows if not has_coords(row)]
    done = len(rows) - len(todo)
    if limit:
        todo = todo[:limit]
    print(f"화장실 {len(rows):,}행 — 좌표 있음 {done:,} · 물어볼 행 {len(todo):,}")
    if not todo:
        print("채울 것이 없습니다.")
        return

    session, key_name = open_session()
    print(f"키: {key_name}")

    found = 0
    misses: list[str] = []
    for i, row in enumerate(todo, start=1):
        for query in candidates(row):
            hit = lookup(session, query)
            if hit is not None:
                row[LAT_COLUMN] = f"{hit[0]:.7f}"
                row[LON_COLUMN] = f"{hit[1]:.7f}"
                found += 1
                break
        else:
            misses.append(f"{row.get('화장실명', '')} · {' / '.join(candidates(row))}")
        if i % 100 == 0 or i == len(todo):
            print(f"  {i:,}/{len(todo):,} — 찾음 {found:,} · 못 찾음 {len(misses):,}",
                  flush=True)

    # 임시 파일에 쓴 뒤 바꿔치기 — 중간에 끊겨도 원본이 반쪽으로 남지 않는다.
    tmp = path.TOILET.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path.TOILET)

    total = sum(1 for row in rows if has_coords(row))
    print(f"\n{path.TOILET.relative_to(path.ROOT)} — 좌표 {total:,}/{len(rows):,}행")
    if misses:
        print(f"못 찾은 {len(misses):,}행 (빈 칸으로 남김):")
        for miss in misses[:20]:
            print(f"  {miss}")
        if len(misses) > 20:
            print(f"  … 그 밖 {len(misses) - 20:,}행")


if __name__ == "__main__":
    main()
