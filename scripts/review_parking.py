"""공영주차장 후보 검토 도구 — 사람이 한 곳씩 보고 데이터셋에 넣는다.

후보 풀(P9)은 자동 발굴만으로 서지 않는다. 어둡기·주차·도로접근이 다 맞아도 실제로
가 보면 사유지 진입로거나 야간 폐쇄거나 시야가 막혀 있다. 그래서 **로드뷰 데스크
전수 검증**이 계획에 들어가 있고(`plan.md` P9), 이 스크립트가 그 작업대다.

이 도구가 하는 일
--------------------------------------------------------------------------
카카오 지도 위에 두 층을 겹쳐 놓고, 점을 눌러 한 곳씩 판단해 **즉시 파일에 적는다**.

    공영주차장  `core.parking`  1,557곳 — 밤에 차를 세울 수 있는 자리
    가로등      `core.lamps`   89,297개 — 그 주변에 조명이 들어오는가

점을 고르면 그 자리의 **어둡기 종합**(`core.darkness.assess_site` — 종합 점수·Falchi
등급·SQM·은하수·야간광·가로등)과 **위경도**, 그리고 카카오 **로드뷰**가 함께 뜬다.
지표는 "여기가 얼마나 어두운 곳인가"를, 로드뷰는 지표로 안 잡히는 것(진입로·시야·
조명·주변)을 맡는다. [저장]·[제외]는 누르는 즉시
`data/candidates/parking_review.jsonl` 에 반영되므로, 창을 닫아도 이어서 하면 된다.

**목록에 없는 자리는 지도 아무 데나 우클릭**하면 된다 — 그 좌표의 어둡기를 그때 재서
같은 화면으로 열고(`/api/site`), 저장하면 `data/candidates/spot_pins.jsonl` 에 핀으로
남는다. 관측지 후보가 공영주차장 안에만 있지는 않기 때문이다(오름 초입·해안 갓길·
농로 끝). 지도에서 주차장은 원, 핀은 마름모다.

저장한 곳(주차장 판단 + 핀)은 오른쪽 목록에 최근 순으로 함께 쌓이고, 줄을 누르면 그
자리로 지도를 옮겨 다시 연다.

저장되는 것과 저장되지 않는 것
--------------------------------------------------------------------------
남기는 것은 **사람이 만든 정보**뿐이다 — 판단(saved/rejected)·이름·메모·시각, 그리고
그것이 어느 지점에 붙는지 알아볼 좌표. 가로등 개수·거리·어둡기 점수 같은 파생 지표는
넣지 않는다. `core` 에서 언제든 다시 계산되는 값을 복사해 두면 원본이 갱신될 때 둘이
어긋나고, 그때 어느 쪽이 맞는지 알 수 없게 된다(화면에 보이는 지표는 서버가 띄울 때
·우클릭할 때 매번 다시 잰 것이다).

파일을 둘로 나눈 것은 키와 뜻이 다르기 때문이다.

    parking_review.jsonl  원본 주차장에 붙는 판단 — 키는 **주차장관리번호**
    spot_pins.jsonl       원본에 없는, 사람이 고른 좌표 — 키는 **좌표 6자리**

지도 위 색
--------------------------------------------------------------------------
점의 **채움색**은 반경 1km 가로등 개수(사분위), **테두리**는 검토 상태다.

최근접 거리로 칠하지 않는 이유는 그 축이 갈리지 않기 때문이다. 1,557곳 전부 가로등이
딸려 있다 — 최근접 거리 중앙값 18m, 99%가 100m 안, 500m 밖은 **0곳**이다. 공영이라
조명이 의무에 가깝다. 그래서 "주차장에 서면 어둡다"는 성립하지 않고, 갈리는 것은
**시가지 한복판인가 외딴 곳인가** 뿐이다. 1km 개수는 18~2,569개로 흩어져 그 구분을
실제로 해낸다(섭지코지 69 · 송악산 85 ↔ 도심 2,000+). 단계 경계는 문헌값이 아니라
이 1,557곳 분포의 사분위이므로, 원본이 갱신되면 함께 움직인다.

실행
--------------------------------------------------------------------------
카카오 JavaScript 앱키가 필요하다 — 저장소 루트 `.env` 의 `KAKAO_JAVASCRIPT_API_KEY`
(환경변수로 넘겨도 된다). 카카오는 **등록된 도메인**에서만 SDK 를 내주므로, 콘솔의
[내 애플리케이션 → 플랫폼 → Web] 에 `http://localhost:8765` 를 등록해 두어야 한다.
로드뷰도 같은 키를 쓴다.

    uv run python -m scripts.review_parking
    → http://localhost:8765
"""

from __future__ import annotations

import base64
import json
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

from scripts import env
from scripts.fetch_kakao_places import TARGETS
from server import path
from server.core import darkness, lamps, nightlight, parking, places

KST = timezone(timedelta(hours=9))

#: 검토 상태. 파일에 없으면 '미확인' — 상태를 세 개 적지 않고 없음으로 표현한다.
DECISIONS = ("saved", "rejected")

#: 카카오 JavaScript 앱키를 담은 환경변수 이름.
_KEY_VAR = "KAKAO_JAVASCRIPT_API_KEY"

_PORT = 8765

# --- 색 ----------------------------------------------------------------------
# 채움 4단계는 **반경 1km 가로등 개수**의 순서형 램프다. 어두운 지도 표면 위에서
# 읽으므로 역방향 — 개수가 적을수록(관측에 유리할수록) 밝은 단계.
_PARK_STEPS = ("#2f6b55", "#4fb98a", "#9fe8c8", "#ffffff")

#: 가로등 점 색 — `build_light_map.py` 와 같은 주황. 두 지도에서 같은 데이터가
#: 다른 색으로 나오면 발표 중에 다른 것으로 읽힌다.
_LAMP_COLOR = "#d95926"

#: 검토 상태 색. 저장은 초록, 제외는 빨강, 아직 저장 안 한 핀은 노랑.
_SAVE_COLOR = "#4fb98a"
_REJECT_COLOR = "#d9534f"
_DRAFT_COLOR = "#ffd479"

#: 좌표 전송 배율 — 십진 6자리(≈0.1m)면 지도 표시에 충분하고 Int32 에 들어간다.
_COORD_SCALE = 1_000_000


# --- 데이터셋 ------------------------------------------------------------------

class Store:
    """검토 결과 JSONL. 누를 때마다 통째로 다시 쓴다(1,557행이라 그래도 된다).

    임시 파일에 쓴 뒤 바꿔치기해서, 중간에 끊겨도 반쪽짜리 파일이 남지 않게 한다.
    """

    def __init__(self, file):
        self._file = file
        self._rows: dict[str, dict] = {}
        if file.exists():
            for line in file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._rows[row["code"]] = row

    def all(self) -> dict[str, dict]:
        return self._rows

    def put(self, code: str, decision: str | None, memo: str, lot) -> str | None:
        """판단을 기록하고 기록 시각을 돌려준다. decision 이 None 이면 판단을 지운다.

        시각을 돌려주는 것은 화면의 저장 목록이 **최근 저장한 것부터** 서기 때문이다 —
        방금 누른 곳이 목록 어디에 들어가는지 브라우저가 알아야 한다.
        """
        if decision is None:
            self._rows.pop(code, None)
            self._flush()
            return None

        at = datetime.now(KST).isoformat(timespec="seconds")
        self._rows[code] = {
            "code": code,
            "name": lot.name,
            "lat": lot.lat,
            "lon": lot.lon,
            "decision": decision,
            "memo": memo,
            "reviewed_at": at,
        }
        self._flush()
        return at

    def _flush(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "".join(
                json.dumps(self._rows[code], ensure_ascii=False) + "\n"
                for code in sorted(self._rows)
            ),
            encoding="utf-8",
        )
        tmp.replace(self._file)


def pin_key(lat: float, lon: float) -> str:
    """핀의 키 — 좌표 소수 6자리(≈0.1m). 같은 자리를 두 번 찍으면 덮어쓴다."""
    return f"{lat:.6f},{lon:.6f}"


class PinStore:
    """지도에서 우클릭으로 찍어 둔 지점 JSONL. `Store` 와 같은 방식으로 즉시 쓴다.

    주차장 검토(`Store`)와 파일을 나누는 이유는 키와 뜻이 다르기 때문이다 — 저쪽은
    원본 주차장에 붙는 판단(주차장관리번호), 이쪽은 원본에 없는 **사람이 고른 좌표**다.
    한 파일에 섞으면 나중에 어느 행이 무엇이었는지 좌표로 되짚어야 한다.

    어둡기 지표는 여기에도 적지 않는다 — `core` 에서 언제든 다시 계산된다.
    """

    def __init__(self, file):
        self._file = file
        self._rows: dict[str, dict] = {}
        if file.exists():
            for line in file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._rows[row["key"]] = row

    def all(self) -> dict[str, dict]:
        return self._rows

    def put(self, lat: float, lon: float, name: str, memo: str) -> dict:
        key = pin_key(lat, lon)
        row = {
            "key": key,
            "name": name,
            "lat": lat,
            "lon": lon,
            "memo": memo,
            "saved_at": datetime.now(KST).isoformat(timespec="seconds"),
        }
        self._rows[key] = row
        self._flush()
        return row

    def remove(self, key: str) -> bool:
        if self._rows.pop(key, None) is None:
            return False
        self._flush()
        return True

    def _flush(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "".join(
                json.dumps(self._rows[key], ensure_ascii=False) + "\n"
                for key in sorted(self._rows)
            ),
            encoding="utf-8",
        )
        tmp.replace(self._file)


# --- 후보 목록 -----------------------------------------------------------------

def site_fields(lat: float, lon: float) -> dict:
    """한 지점의 어둡기 종합(`core.darkness.assess_site`)을 화면이 쓰는 이름으로.

    주차장 점과 우클릭 핀이 **같은 키 이름**을 받게 해서, 화면 쪽이 둘을 한 함수로
    그린다. 격자 밖(해상 등)이면 어둡기 값들이 None 이다.
    """
    site = darkness.assess_site(lat, lon)
    lamp, dark, night = site.lamps, site.darkness, site.nightlight
    return {
        "nearestM": lamp.nearest_m,
        "lampNear": lamp.near,
        "lampMid": lamp.mid,
        "lampFar": lamp.far,
        "score": site.score,
        "cap": site.cap,
        "sqm": dark.sqm if dark else None,
        "falchi": dark.falchi_grade if dark else None,
        "falchiLabel": dark.falchi_label if dark else None,
        "bortle": dark.bortle if dark else None,
        "milkyWay": dark.milky_way if dark else None,
        "viirsNear": night.near_max if night else None,
    }


def pin_payload(row: dict) -> dict:
    """저장된 핀 한 줄 + 그 자리의 어둡기. 지표는 파일이 아니라 여기서 매번 붙인다.

    시각 키를 `at` 으로 바꿔 내보낸다 — 화면의 저장 목록이 주차장 판단과 핀을 한 줄로
    세우므로 정렬 키 이름이 둘 사이에서 같아야 한다.
    """
    return {
        "key": row["key"],
        "name": row["name"],
        "lat": row["lat"],
        "lon": row["lon"],
        "memo": row["memo"],
        "at": row["saved_at"],
        **site_fields(row["lat"], row["lon"]),
    }


def parking_rows() -> list[dict]:
    """공영주차장 1,557곳 + 그 지점의 어둡기 종합(`core.darkness.assess_site`).

    세 신호(SQM·VIIRS·가로등)를 한 번에 받는다 — 로드뷰로 눈을 확인하기 전에
    "여기가 얼마나 어두운 곳인가"가 먼저 나와야 판단이 선다.

    `bucket` 은 여기서 채우지 않는다 — 사분위 경계가 목록 전체에서 나온다.
    """
    return [
        {
            "source": "parking",
            "code": lot.code,
            "name": lot.name,
            "lat": lot.lat,
            "lon": lot.lon,
            "kind": lot.kind,
            "slots": lot.slots,
            "fee": lot.fee,
            "address": lot.address,
            **site_fields(lot.lat, lot.lon),
        }
        for lot in parking.lots()
    ]


def place_rows() -> list[dict]:
    """카카오맵 검색 장소 + 같은 어둡기 종합. 주차장 행과 **같은 키 이름**을 쓴다.

    코드에 `kakao:` 를 붙이는 것은 판단 파일 한 곳에 두 출처가 섞이기 때문이다 —
    주차장관리번호(`405-2-…`)와 카카오 장소 id 는 형식이 겹치지 않지만, 나중에
    그 줄이 어디서 온 후보였는지 파일만 보고 알 수 있어야 한다.
    """
    return [
        {
            "source": f"kakao_{place.source}",
            "code": f"kakao:{place.id}",
            "name": place.name,
            "lat": place.lat,
            "lon": place.lon,
            "category": place.category,
            "address": place.address,
            "url": place.url,
            **site_fields(place.lat, place.lon),
        }
        for place in places.places()
    ]


def candidate_rows() -> list[dict]:
    """검토 대상 전체 — 공영주차장 + 카카오 장소.

    한 목록으로 합치는 이유는 **판단 경로를 하나로 두기 위해서**다. 저장·제외·메모·
    목록·진행률이 전부 `code` 하나로 돌아가므로, 출처가 늘어도 화면과 서버가
    갈라지지 않는다. 갈리는 것은 점의 모양과 상세 칸뿐이다.
    """
    return parking_rows() + place_rows()


def assign_buckets(rows: list[dict]) -> list[dict]:
    """1km 가로등 개수의 사분위로 4단계를 매기고 범례를 만든다.

    0 = 개수가 가장 많은 25%(도심) … 3 = 가장 적은 25%(관측에 유리).

    사분위는 **검토 대상 전체**(주차장 + 카카오 장소)에서 잡는다. 출처마다 따로
    잡으면 같은 색이 출처에 따라 다른 밝기를 뜻하게 되어 지도에서 비교가 안 된다.
    """
    counts = np.array([row["lampFar"] for row in rows], dtype=np.float64)
    q25, q50, q75 = (float(v) for v in np.percentile(counts, [25, 50, 75]))

    for row in rows:
        far = row["lampFar"]
        row["bucket"] = 0 if far > q75 else 1 if far > q50 else 2 if far > q25 else 3

    sizes = [0, 0, 0, 0]
    for row in rows:
        sizes[row["bucket"]] += 1
    labels = (
        (f"{q75:,.0f}개 초과", "시가지 한복판"),
        (f"{q50:,.0f}~{q75:,.0f}개", ""),
        (f"{q25:,.0f}~{q50:,.0f}개", ""),
        (f"{q25:,.0f}개 이하", "주변이 어둡다 — 관측에 유리"),
    )
    return [
        {
            "swatch": _PARK_STEPS[i],
            "label": label,
            "note": f"{sizes[i]:,}곳" + (f" · {note}" if note else ""),
        }
        for i, (label, note) in enumerate(labels)
    ]


def _b64_int32(values: np.ndarray) -> str:
    """리틀엔디언 Int32 배열 → base64. JS 쪽 Int32Array 가 그대로 읽는다."""
    return base64.b64encode(values.astype("<i4").tobytes()).decode("ascii")


def lamp_layer() -> dict:
    """가로등 89,297개 좌표. 마커로 찍으면 DOM 이 못 버텨 캔버스로 넘긴다."""
    lat, lon = lamps.points()
    return {
        "name": f"가로등·보안등 {lamps.COUNT:,}개",
        "color": _LAMP_COLOR,
        "lat": _b64_int32(np.rint(lat * _COORD_SCALE)),
        "lon": _b64_int32(np.rint(lon * _COORD_SCALE)),
    }


# --- HTML ---------------------------------------------------------------------

_HTML = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>제주 공영주차장 후보 검토</title>
<style>
  :root {
    --panel: rgba(20, 20, 19, 0.92);
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --ink-muted: #898781;
    --hairline: rgba(255, 255, 255, 0.12);
    --save: #4fb98a;
    --reject: #d9534f;
  }
  html, body { margin: 0; height: 100%; background: #0d0d0d; overflow: hidden; }
  body {
    font: 13px/1.5 system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  }
  #wrap { position: absolute; inset: 0; }
  /* z-index 0 은 지도를 **스태킹 컨텍스트로 가둔다** — 카카오가 내부에 쓰는 z-index 가
     바깥으로 새어 나와 캔버스를 덮지 않게. */
  #map { position: absolute; inset: 0; z-index: 0; background: #0d0d0d; }
  /* 점 레이어는 캔버스 한 장에 직접 찍는다 — 클릭은 지도 쪽에서 받아 좌표로 맞춘다.
     canvas 는 **대체 요소**라 inset:0 만으로는 늘어나지 않고 고유 크기(300x150)로
     좌측 상단에 눌러앉는다. width/height 를 명시해야 화면을 덮는다. */
  #dots {
    position: absolute; inset: 0; width: 100%; height: 100%;
    z-index: 1; pointer-events: none;
  }

  .panel {
    position: absolute; z-index: 10;
    background: var(--panel); color: var(--ink);
    border: 1px solid var(--hairline); border-radius: 10px;
    padding: 12px 14px;
    backdrop-filter: blur(6px);
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
  }

  .review {
    top: 12px; left: 12px; width: 320px;
    max-height: calc(100vh - 24px); overflow-y: auto;
  }
  .review .bar {
    display: flex; align-items: baseline; gap: 8px; font-size: 11px;
    color: var(--ink-muted); margin-bottom: 8px;
  }
  .review .bar b { color: var(--ink); font-size: 13px; }
  .review .track {
    flex: 1; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.12);
    overflow: hidden;
  }
  .review .track i { display: block; height: 100%; background: var(--save); }
  .review h3 { margin: 0 0 2px; font-size: 15px; }
  .review .sub { color: var(--ink-muted); font-size: 11px; margin-bottom: 9px; }
  .review dl {
    margin: 0 0 10px; display: grid; grid-template-columns: auto 1fr; gap: 2px 12px;
    font-size: 12px;
  }
  .review dt { color: var(--ink-muted); }
  .review dd { margin: 0; font-variant-numeric: tabular-nums; }
  #rv {
    height: 168px; border-radius: 7px; overflow: hidden; margin-bottom: 9px;
    background: #16161a;
  }
  #rv.none { display: grid; place-items: center; color: var(--ink-muted);
             font-size: 12px; }
  .review textarea, .review input.nm {
    width: 100%; box-sizing: border-box; resize: vertical; min-height: 46px;
    background: rgba(255,255,255,0.06); color: var(--ink); font: inherit;
    font-size: 12px; border: 1px solid var(--hairline); border-radius: 7px;
    padding: 6px 8px;
  }
  .review input.nm { min-height: 0; margin-bottom: 6px; }
  .review .acts { display: flex; gap: 6px; margin-top: 9px; }
  .review .acts button {
    flex: 1; font: inherit; font-size: 12px; font-weight: 600; padding: 7px 0;
    cursor: pointer; border-radius: 7px; border: 1px solid var(--hairline);
    background: transparent; color: var(--ink-2);
  }
  .review .acts button.save.on { background: var(--save); border-color: var(--save);
                                 color: #07231a; }
  .review .acts button.reject.on { background: var(--reject);
                                   border-color: var(--reject); color: #fff; }
  .review .acts button.clear { flex: 0 0 auto; padding: 7px 10px; }
  .review .hint { margin-top: 8px; font-size: 11px; color: var(--ink-muted); }
  .review .empty { color: var(--ink-muted); font-size: 12px; padding: 6px 0 2px; }
  .review a.link { font-size: 12px; color: #9ec5f4; }
  .review .cap { color: var(--ink-muted); }
  .review dd.coord { display: flex; align-items: baseline; gap: 6px; }
  .review dd.coord button {
    font: inherit; font-size: 11px; padding: 1px 6px; cursor: pointer;
    background: transparent; color: var(--ink-muted);
    border: 1px solid var(--hairline); border-radius: 5px;
  }

  /* 오른쪽 세로줄 — 조작·저장 목록·범례가 위에서 아래로 선다. 가운데(목록)만
     늘어나고 그 안에서 스크롤된다. */
  .rail {
    position: absolute; top: 12px; right: 12px; bottom: 12px; z-index: 10;
    width: 262px; display: flex; flex-direction: column; gap: 10px;
  }
  .rail .panel { position: static; width: auto; }

  .saved {
    flex: 1 1 auto; min-height: 120px; display: flex; flex-direction: column;
    overflow: hidden; padding-bottom: 8px;
  }
  .saved .head {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 7px;
  }
  .saved .head h2 { margin: 0; }
  .saved .head .n { font-size: 12px; color: var(--save); font-weight: 600; }
  .saved .list {
    flex: 1 1 auto; overflow-y: auto; margin-right: -6px; padding-right: 4px;
    scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.22) transparent;
  }
  .saved .item {
    display: block; width: 100%; text-align: left; font: inherit; cursor: pointer;
    background: rgba(255,255,255,0.05); color: var(--ink);
    border: 1px solid transparent; border-left: 2px solid var(--save);
    border-radius: 6px; padding: 6px 8px; margin-bottom: 5px;
  }
  .saved .item.on { background: rgba(79,185,138,0.18); border-color: var(--save); }
  .saved .item .nm {
    display: block; font-size: 12px; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis;
  }
  .saved .item .mt {
    display: block; font-size: 11px; color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
  }
  .saved .item .memo {
    display: block; font-size: 11px; color: var(--ink-2); margin-top: 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .saved .none { font-size: 12px; color: var(--ink-muted); line-height: 1.6; }
  .controls h2 {
    margin: 0 0 7px; font-size: 11px; font-weight: 600; color: var(--ink-muted);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .controls h2 + h2 { margin-top: 12px; }
  .controls label {
    display: flex; align-items: center; gap: 7px; font-size: 12px;
    color: var(--ink-2); margin: 4px 0; cursor: pointer;
  }
  .controls input { accent-color: #6da7ec; margin: 0; }
  .controls .seg { display: flex; gap: 6px; }
  .controls .seg button {
    flex: 1; font: inherit; font-size: 12px; padding: 4px 0; cursor: pointer;
    background: transparent; color: var(--ink-2);
    border: 1px solid var(--hairline); border-radius: 6px;
  }
  .controls .seg button.on { background: #256abf; color: #fff; border-color: #256abf; }

  .legend h2 { margin: 0 0 8px; font-size: 12px; font-weight: 600; }
  .legend .row {
    display: flex; align-items: flex-start; gap: 8px; margin: 5px 0;
    font-size: 12px; cursor: pointer; user-select: none;
  }
  .legend .row.off { opacity: 0.32; }
  .legend .sw {
    flex: 0 0 auto; width: 11px; height: 11px; border-radius: 50%;
    margin: 4px 2px 0; border: 1px solid rgba(0, 0, 0, 0.55);
  }
  .legend .sw.ring { background: transparent !important; border-width: 2px; }
  /* 지도의 마름모(핀)를 범례에서도 마름모로 — 모양이 곧 구분이다. */
  .legend .sw.pin { border-radius: 2px; transform: rotate(45deg); }
  .legend .sw.box { border-radius: 1px; }
  .legend .lbl { color: var(--ink-2); }
  .legend .note { color: var(--ink-muted); font-size: 11px; }
  .legend .foot {
    margin-top: 10px; padding-top: 9px; border-top: 1px solid var(--hairline);
    font-size: 11px; color: var(--ink-muted);
  }
  .sources {
    position: absolute; left: 12px; bottom: 12px; z-index: 5;
    max-width: 44ch; font-size: 10px; line-height: 1.5; color: var(--ink-muted);
  }
  .fail {
    position: absolute; inset: 0; display: grid; place-items: center;
    color: var(--ink-2); font-size: 13px; text-align: center; padding: 24px;
  }
</style>
<div id="wrap">
  <div id="map"></div>
  <canvas id="dots"></canvas>
</div>
<!--__PANELS__-->
<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey=/*__KEY__*/&autoload=false"></script>
<script>
const DATA = /*__DATA__*/;
/* code → {decision, memo, at} — 서버가 실어 보낸 현재 상태 */
const REVIEW = /*__REVIEW__*/;
/* key → 저장된 우클릭 핀(좌표·이름·메모 + 그 자리의 어둡기) */
const PINS = /*__PINS__*/;

/* 은하수 가시성 표기 — `core.darkness` 의 세 상태를 그대로 옮긴 것. */
const MILKY = { visible: '보임', degraded: '흐릿함', lost: '보기 어려움' };

/* base64 → Int32Array (numpy 가 리틀엔디언으로 실어 보낸다). */
function decodeInt32(b64) {
  const bin = atob(b64), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Int32Array(bytes.buffer);
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}

if (typeof kakao === 'undefined' || !kakao.maps) {
  document.getElementById('wrap').innerHTML =
    '<div class="fail">카카오 지도 SDK 를 불러오지 못했습니다.<br>'
    + 'JavaScript 앱키와 <b>플랫폼 → Web 사이트 도메인</b> 등록을 확인하세요.<br>'
    + '이 페이지 주소(http://localhost:8765)가 등록돼 있어야 합니다.</div>';
} else {
  kakao.maps.load(init);
}

function init() {
  const b0 = DATA.view.bounds;
  const map = new kakao.maps.Map(document.getElementById('map'), {
    center: new kakao.maps.LatLng((b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2),
    level: 11
  });
  /* 오른쪽은 세로줄(.rail)이 위아래로 다 쓴다 — 확대 버튼은 아래 가운데로 뺀다. */
  map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.BOTTOM);
  /* 창 크기에 맞춰 제주 전체가 들어오게 맞춘다 — 줌 단계를 눈대중으로 박지 않는다. */
  map.setBounds(new kakao.maps.LatLngBounds(
    new kakao.maps.LatLng(b0[0], b0[1]), new kakao.maps.LatLng(b0[2], b0[3])));

  const canvas = document.getElementById('dots');
  const ctx = canvas.getContext('2d');
  const lampLat = decodeInt32(DATA.lamps.lat);
  const lampLon = decodeInt32(DATA.lamps.lon);
  const S = DATA.coordScale;

  /* 레이어 스위치는 후보의 source 값을 그대로 키로 쓴다 — 출처가 늘어도
     체크박스에 data-layer 만 붙이면 여기 손댈 것이 없다. */
  const show = { lamps: true };
  DATA.sources.forEach(function (s) { show[s.key] = true; });
  const bucketOn = [true, true, true, true];
  let onlyTodo = false;
  let selected = -1;          /* 열려 있는 주차장 인덱스 */
  let pin = null;             /* 열려 있는 우클릭 핀(저장 전이면 key 가 null) */
  let screen = [];            /* 화면에 있는 주차장의 픽셀 좌표 캐시 */
  let pinScreen = [];         /* 핀도 같은 방식으로 눌러 고른다 */
  let anchor = null, anchorPt = null;   /* 드래그 중 캔버스를 끌고 다닐 기준점 */

  const byCode = {};
  DATA.parking.forEach(function (p, i) { byCode[p.code] = i; });

  /* 저장된 핀 + 아직 저장 안 한 것 하나. 지도에도 목록에도 이 순서로 나온다. */
  function pinList() {
    const list = Object.keys(PINS).map(function (k) { return PINS[k]; });
    if (pin && !pin.key) list.push(pin);
    return list;
  }

  /* --- 투영 -----------------------------------------------------------------
     카카오 기본 지도는 웹 메르카토르가 아니라 TM 계열이라 위경도→화면이 곧바로
     선형이 아니다. 그렇다고 점 8만 9천 개를 낱개로 projection API 에 넣으면 팬·줌
     끝날 때마다 그만큼 호출이 나간다. 그래서 **현재 화면에서만 성립하는 아핀**을
     세 점으로 세우고, 다른 점들로 오차를 재서 1.5px 을 넘으면 낱개 투영으로
     되돌린다 — 빠른 길을 쓰되 맞는지 매번 확인한다. */
  function calibrate() {
    const proj = map.getProjection();
    const b = map.getBounds(), sw = b.getSouthWest(), ne = b.getNorthEast();
    const at = function (la, lo) {
      const p = proj.containerPointFromCoords(new kakao.maps.LatLng(la, lo));
      return [p.x, p.y];
    };
    const fit = [[sw.getLat(), sw.getLng()], [ne.getLat(), sw.getLng()],
                 [sw.getLat(), ne.getLng()]];
    const pts = fit.map(function (c) { return at(c[0], c[1]); });

    /* x = a·lon + b·lat + c 를 세 점으로 정확히 푼다(크라메르). y 도 같은 행렬. */
    const m = fit.map(function (c) { return [c[1], c[0], 1]; });
    const det3 = function (r) {
      return r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
           - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
           + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]);
    };
    const D = det3(m);
    if (Math.abs(D) < 1e-12) return { affine: null, proj: proj };
    const solve = function (k) {
      const out = [];
      for (let col = 0; col < 3; col++) {
        const r = m.map(function (row, i) {
          const cp = row.slice(); cp[col] = pts[i][k]; return cp;
        });
        out.push(det3(r) / D);
      }
      return out;
    };
    const gx = solve(0), gy = solve(1);

    /* 검산 — 화면 중심과 네 변의 중점. 하나라도 어긋나면 아핀을 버린다. */
    const midLat = (sw.getLat() + ne.getLat()) / 2;
    const midLon = (sw.getLng() + ne.getLng()) / 2;
    const check = [[midLat, midLon], [midLat, sw.getLng()], [midLat, ne.getLng()],
                   [ne.getLat(), ne.getLng()], [sw.getLat(), midLon]];
    for (let i = 0; i < check.length; i++) {
      const la = check[i][0], lo = check[i][1], t = at(la, lo);
      const x = gx[0] * lo + gx[1] * la + gx[2];
      const y = gy[0] * lo + gy[1] * la + gy[2];
      if (Math.hypot(x - t[0], y - t[1]) > 1.5) return { affine: null, proj: proj };
    }
    return { affine: { gx: gx, gy: gy }, proj: proj };
  }

  function projector() {
    const cal = calibrate();
    if (cal.affine) {
      const gx = cal.affine.gx, gy = cal.affine.gy;
      return function (la, lo, out) {
        out[0] = gx[0] * lo + gx[1] * la + gx[2];
        out[1] = gy[0] * lo + gy[1] * la + gy[2];
      };
    }
    const proj = cal.proj;
    return function (la, lo, out) {
      const p = proj.containerPointFromCoords(new kakao.maps.LatLng(la, lo));
      out[0] = p.x; out[1] = p.y;
    };
  }

  /* --- 그리기 --------------------------------------------------------------- */
  function visible(p) {
    if (!show[p.source]) return false;
    if (!bucketOn[p.bucket]) return false;
    return !(onlyTodo && REVIEW[p.code]);
  }

  /* 공영주차장은 원, 카카오 검색 장소는 사각형. 채움색(가로등 개수)은 둘이 같은
     눈금이라, 모양만 다르게 해서 **어디서 온 후보인지**를 색과 따로 읽게 한다.
     (우클릭 핀은 마름모 — 세 모양이 서로 겹치지 않는다.) */
  function dot(x, y, r, square) {
    ctx.beginPath();
    if (square) ctx.rect(x - r, y - r, r * 2, r * 2);
    else ctx.arc(x, y, r, 0, 6.283185307179586);
  }

  function sourceLabel(key) {
    for (let i = 0; i < DATA.sources.length; i++) {
      if (DATA.sources[i].key === key) return DATA.sources[i].label;
    }
    return key;
  }

  function draw() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.transform = '';
    canvas.style.visibility = 'visible';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const b = map.getBounds(), sw = b.getSouthWest(), ne = b.getNorthEast();
    const padLat = (ne.getLat() - sw.getLat()) * 0.06;
    const padLon = (ne.getLng() - sw.getLng()) * 0.06;
    const latMin = sw.getLat() - padLat, latMax = ne.getLat() + padLat;
    const lonMin = sw.getLng() - padLon, lonMax = ne.getLng() + padLon;

    const project = projector();
    const out = [0, 0];
    const level = map.getLevel();

    if (show.lamps) {
      /* 줌이 낮으면 점이 서로 덮어써 밀도가 뭉개진다 — 작게·반투명하게 찍어 겹칠수록
         진해지게 두고, 확대하면 개체로 또렷해지게 키운다. */
      const r = level <= 3 ? 4.5 : level <= 4 ? 3.2 : level <= 5 ? 2.6
              : level <= 6 ? 2.0 : level <= 8 ? 1.5 : 1.0;
      ctx.globalAlpha = level <= 5 ? 0.85 : level <= 8 ? 0.68 : 0.5;
      ctx.fillStyle = DATA.lamps.color;
      ctx.beginPath();
      for (let i = 0; i < lampLat.length; i++) {
        const la = lampLat[i] / S, lo = lampLon[i] / S;
        if (la < latMin || la > latMax || lo < lonMin || lo > lonMax) continue;
        project(la, lo, out);
        ctx.moveTo(out[0] + r, out[1]);
        ctx.arc(out[0], out[1], r, 0, 6.283185307179586);
      }
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    screen = [];
    for (let i = 0; i < DATA.parking.length; i++) {
      const p = DATA.parking[i];
      if (!visible(p)) continue;
      if (p.lat < latMin || p.lat > latMax || p.lon < lonMin || p.lon > lonMax) {
        continue;
      }
      project(p.lat, p.lon, out);
      screen.push({ i: i, x: out[0], y: out[1] });

      const mark = REVIEW[p.code];
      const square = p.source !== 'parking';
      /* 판단이 끝난 점은 뒤로 물린다 — 남은 일이 눈에 먼저 들어와야 한다. */
      ctx.globalAlpha = mark ? 0.5 : 1;
      dot(out[0], out[1], square ? 4.4 : 5, square);
      ctx.fillStyle = DATA.steps[p.bucket];
      ctx.fill();
      ctx.lineWidth = mark ? 2.2 : 1.4;
      const sc = DATA.stateColor;
      ctx.strokeStyle = mark
        ? (mark.decision === 'saved' ? sc.saved : sc.rejected)
        : 'rgba(8, 8, 8, 0.85)';
      ctx.stroke();
      ctx.globalAlpha = 1;

      if (i === selected) {
        ctx.beginPath();
        ctx.arc(out[0], out[1], 10, 0, 6.283185307179586);
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }

    /* 핀은 마름모로 찍는다 — 원(주차장)과 한눈에 갈려야 사람이 찍은 자리인 줄 안다.
       필터(범례·아직 안 본 곳만)는 주차장 축이라 핀에는 걸지 않는다. */
    pinScreen = [];
    pinList().forEach(function (p) {
      if (p.lat < latMin || p.lat > latMax || p.lon < lonMin || p.lon > lonMax) {
        return;
      }
      project(p.lat, p.lon, out);
      pinScreen.push({ p: p, x: out[0], y: out[1] });
      ctx.beginPath();
      ctx.moveTo(out[0], out[1] - 7);
      ctx.lineTo(out[0] + 6, out[1]);
      ctx.lineTo(out[0], out[1] + 7);
      ctx.lineTo(out[0] - 6, out[1]);
      ctx.closePath();
      ctx.fillStyle = p.key ? DATA.stateColor.saved : DATA.stateColor.draft;
      ctx.fill();
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = 'rgba(8, 8, 8, 0.85)';
      ctx.stroke();
      if (p === pin) {
        ctx.beginPath();
        ctx.arc(out[0], out[1], 12, 0, 6.283185307179586);
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    });

    /* 드래그 중에는 다시 그리지 않고 캔버스를 통째로 밀어 맞춘다. */
    anchor = map.getCenter();
    anchorPt = map.getProjection().containerPointFromCoords(anchor);
  }

  kakao.maps.event.addListener(map, 'idle', draw);
  kakao.maps.event.addListener(map, 'drag', function () {
    if (!anchor) return;
    const p = map.getProjection().containerPointFromCoords(anchor);
    canvas.style.transform =
      'translate(' + (p.x - anchorPt.x) + 'px,' + (p.y - anchorPt.y) + 'px)';
  });
  /* 줌 중에는 좌표가 통째로 바뀌어 밀어서 맞출 수 없다 — 감췄다 idle 에 되살린다 */
  kakao.maps.event.addListener(map, 'zoom_start', function () {
    canvas.style.visibility = 'hidden';
  });
  window.addEventListener('resize', draw);

  /* --- 선택 ----------------------------------------------------------------
     왼쪽 버튼은 찍혀 있는 점(주차장·저장한 핀)을 고르고, **오른쪽 버튼은 아무 데나**
     — 목록에 없는 자리의 어둡기를 그 자리에서 잰다. 관측지 후보가 주차장 안에만
     있지는 않기 때문이다. */
  kakao.maps.event.addListener(map, 'click', function (e) {
    const project = projector(), out = [0, 0];
    project(e.latLng.getLat(), e.latLng.getLng(), out);

    let hit = null, hitD = 14;
    for (let k = 0; k < pinScreen.length; k++) {
      const d = Math.hypot(pinScreen[k].x - out[0], pinScreen[k].y - out[1]);
      if (d < hitD) { hitD = d; hit = pinScreen[k].p; }
    }
    if (hit) { openPin(hit); return; }

    let best = -1, bestD = 14;
    for (let k = 0; k < screen.length; k++) {
      const d = Math.hypot(screen[k].x - out[0], screen[k].y - out[1]);
      if (d < bestD) { bestD = d; best = screen[k].i; }
    }
    select(best);
  });

  kakao.maps.event.addListener(map, 'rightclick', function (e) {
    const la = e.latLng.getLat(), lo = e.latLng.getLng();
    const project = projector(), out = [0, 0];
    project(la, lo, out);
    /* 이미 찍어 둔 핀 위에서 우클릭하면 새로 만들지 않고 그것을 연다. */
    for (let k = 0; k < pinScreen.length; k++) {
      const d = Math.hypot(pinScreen[k].x - out[0], pinScreen[k].y - out[1]);
      if (d < 14) { openPin(pinScreen[k].p); return; }
    }
    measure({ key: null, name: '', lat: la, lon: lo, memo: '', at: null });
  });
  /* 지도 위에서는 브라우저 메뉴 대신 이 패널이 열려야 한다. */
  document.getElementById('wrap').addEventListener('contextmenu', function (e) {
    e.preventDefault();
  });

  const box = document.getElementById('review');
  let roadview = null, rvClient = null;

  /* 어둡기 지표 줄 — 주차장 점과 우클릭 핀이 같은 키 이름을 받으므로 함수 하나로 쓴다.
     값이 `undefined` 면 아직 서버에서 오지 않은 것이고, `null` 이면 격자 밖이다. */
  function infoRows(o) {
    const num = function (v, digits, unit) {
      if (v === undefined) return '<span class="cap">재는 중…</span>';
      if (v === null) return '—';
      return v.toFixed(digits) + (unit || '');
    };
    return [
      ['광공해 종합', o.score === undefined
        ? '<span class="cap">재는 중…</span>'
        : o.score === null
          ? '<span class="cap">격자 밖 — 판정 없음</span>'
          : o.score.toFixed(3) + ' <span class="cap">· ' + esc(o.cap) + '</span>'],
      ['광공해 등급', o.falchi
        ? 'Falchi ' + o.falchi + ' <span class="cap">· Bortle ' + o.bortle
          + '</span><br><span class="cap">' + esc(o.falchiLabel) + '</span>'
        : (o.falchi === undefined ? '<span class="cap">재는 중…</span>' : '—')],
      ['하늘 밝기', num(o.sqm, 2, ' SQM')],
      ['은하수', o.milkyWay === undefined
        ? '<span class="cap">재는 중…</span>' : (MILKY[o.milkyWay] || '—')],
      ['최근접 가로등', o.nearestM === undefined
        ? '<span class="cap">재는 중…</span>'
        : (o.nearestM === null ? '1km 안에 없음' : o.nearestM.toFixed(0) + ' m')],
      ['가로등 100m/500m/1km', o.lampFar === undefined
        ? '<span class="cap">재는 중…</span>'
        : o.lampNear + ' / ' + o.lampMid + ' / ' + o.lampFar + '개'],
      ['야간광 1km 최대', num(o.viirsNear, 2)]
    ];
  }

  function dl(rows, lat, lon) {
    return '<dl>' + rows.map(function (r) {
        return '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>';
      }).join('')
      + '<dt>좌표</dt><dd class="coord"><span>'
      + lat.toFixed(6) + ', ' + lon.toFixed(6) + '</span>'
      + '<button id="copy" title="위경도 복사">복사</button></dd></dl>';
  }

  /* 좌표는 손으로 옮겨 적게 두지 않는다 — 로드뷰·다른 지도에 그대로 붙인다. */
  function bindCopy(lat, lon) {
    const btn = document.getElementById('copy');
    if (!btn) return;
    btn.onclick = function () {
      navigator.clipboard.writeText(lat.toFixed(6) + ', ' + lon.toFixed(6))
        .then(function () {
          btn.textContent = '복사됨';
          setTimeout(function () { btn.textContent = '복사'; }, 1200);
        })
        .catch(function () { btn.textContent = '복사 실패'; });
    };
  }

  function kakaoLink(name, lat, lon) {
    return '<a class="link" target="_blank" rel="noopener" href="'
      + 'https://map.kakao.com/link/map/' + encodeURIComponent(name) + ','
      + lat + ',' + lon + '">카카오맵에서 보기 →</a>';
  }

  function select(i) {
    selected = i;
    pin = null;
    draw();
    if (i < 0) {
      box.innerHTML = DATA.emptyHtml;
      renderProgress();
      renderSaved();
      return;
    }
    const p = DATA.parking[i];
    const mark = REVIEW[p.code] || { decision: null, memo: '' };
    /* 공영주차장은 원본이 면수·요금을 주고, 카카오 장소는 분류를 준다. 없는 칸을
       빈칸으로 남기지 않고 출처가 실제로 아는 것만 싣는다. */
    const head = p.source === 'parking'
      ? ['유형', p.kind + ' · ' + p.slots.toLocaleString() + '면 · ' + p.fee]
      : ['분류', p.category || '—'];
    const rows = [head].concat(infoRows(p));

    box.innerHTML = '<div class="bar" id="bar"></div>'
      + '<h3>' + esc(p.name) + '</h3>'
      + '<div class="sub">' + esc(p.address || '주소 없음')
      + ' · ' + esc(sourceLabel(p.source)) + '</div>'
      + '<div id="rv"></div>'
      + dl(rows, p.lat, p.lon)
      + '<textarea id="memo" placeholder="메모 — 진입로·야간개방·시야 등">'
      + esc(mark.memo || '') + '</textarea>'
      + '<div class="acts">'
      + '<button class="save' + (mark.decision === 'saved' ? ' on' : '') + '">'
      + '저장 <span style="opacity:.6">S</span></button>'
      + '<button class="reject' + (mark.decision === 'rejected' ? ' on' : '') + '">'
      + '제외 <span style="opacity:.6">X</span></button>'
      + '<button class="clear" title="판단 취소">↺</button></div>'
      + '<div class="hint">메모는 저장/제외를 누를 때 함께 기록된다 · '
      + kakaoLink(p.name, p.lat, p.lon)
      + (p.url ? ' · <a class="link" target="_blank" rel="noopener" href="'
                 + esc(p.url) + '">카카오맵 상세 →</a>' : '')
      + '</div>';

    box.querySelector('.save').onclick = function () { commit(p, 'saved'); };
    box.querySelector('.reject').onclick = function () { commit(p, 'rejected'); };
    box.querySelector('.clear').onclick = function () { commit(p, null); };
    bindCopy(p.lat, p.lon);
    renderProgress();
    renderSaved();
    showRoadview(p);
  }

  /* --- 우클릭 핀 ------------------------------------------------------------ */

  /* 지표 없이 먼저 열고, 서버가 잰 값이 오면 같은 자리를 다시 그린다 — 로드뷰가
     뜨는 동안 빈 화면을 보고 있지 않게. */
  function measure(p) {
    openPin(p);
    fetch('/api/site?lat=' + p.lat + '&lon=' + p.lon)
      .then(function (r) { return r.json(); })
      .then(function (site) {
        Object.assign(p, site);
        if (pin !== p) { draw(); return; }
        /* 재는 사이에 적어 둔 이름·메모는 다시 그릴 때 지우지 않는다. */
        const nameEl = document.getElementById('pinName');
        const memoEl = document.getElementById('memo');
        if (nameEl) p.name = nameEl.value;
        if (memoEl) p.memo = memoEl.value;
        openPin(p);
      })
      .catch(function (err) { alert('어둡기 조회 실패: ' + err); });
  }

  function openPin(p) {
    pin = p;
    selected = -1;
    draw();
    const title = p.name || '이 지점';
    box.innerHTML = '<div class="bar" id="bar"></div>'
      + '<h3>' + esc(title) + '</h3>'
      + '<div class="sub">지도에서 찍은 지점'
      + (p.key ? ' · 저장됨' : ' · 아직 저장 안 함') + '</div>'
      + '<div id="rv"></div>'
      + dl(infoRows(p), p.lat, p.lon)
      + '<input id="pinName" class="nm" placeholder="이름 — 비우면 좌표로 남는다" '
      + 'value="' + esc(p.name || '') + '">'
      + '<textarea id="memo" placeholder="메모 — 왜 이 자리인지">'
      + esc(p.memo || '') + '</textarea>'
      + '<div class="acts">'
      + '<button class="save' + (p.key ? ' on' : '') + '">'
      + (p.key ? '저장 갱신' : '이 자리 저장') + '</button>'
      + (p.key ? '<button class="clear" title="핀 삭제">삭제</button>' : '')
      + '</div>'
      + '<div class="hint">우클릭한 자리는 주차장 목록과 따로 적힌다 · '
      + kakaoLink(title, p.lat, p.lon) + '</div>';

    box.querySelector('.save').onclick = function () { savePin(p); };
    const del = box.querySelector('.clear');
    if (del) del.onclick = function () { removePin(p); };
    bindCopy(p.lat, p.lon);
    renderProgress();
    renderSaved();
    showRoadview(p);
  }

  function savePin(p) {
    p.name = document.getElementById('pinName').value.trim();
    p.memo = document.getElementById('memo').value;
    fetch('/api/pin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat: p.lat, lon: p.lon, name: p.name, memo: p.memo })
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (!res.ok) { alert('저장 실패: ' + res.error); return; }
      PINS[res.pin.key] = res.pin;
      openPin(PINS[res.pin.key]);
    }).catch(function (err) { alert('저장 실패: ' + err); });
  }

  function removePin(p) {
    fetch('/api/pin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: p.key, remove: true })
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (!res.ok) { alert('삭제 실패: ' + res.error); return; }
      delete PINS[p.key];
      /* 지운 뒤에도 화면은 그대로 둔다 — 값은 그대로 읽히고, 다시 저장할 수 있다. */
      p.key = null;
      p.at = null;
      openPin(p);
    }).catch(function (err) { alert('삭제 실패: ' + err); });
  }

  /* --- 저장 목록 ------------------------------------------------------------
     저장한 주차장과 우클릭 핀을 한 줄에 세운다 — **최근 저장한 것부터**. 줄을 누르면
     그 자리로 지도를 옮기고 같은 화면을 연다. 저장해 둔 곳을 다시 찾아 들어가는 길이
     지도를 헤매는 것밖에 없으면 목록이 목록 구실을 못한다. */
  function savedItems() {
    const items = [];
    Object.keys(REVIEW).forEach(function (c) {
      if (REVIEW[c].decision !== 'saved' || byCode[c] === undefined) return;
      const p = DATA.parking[byCode[c]];
      items.push({
        kind: 'lot', id: c, at: REVIEW[c].at || '', name: p.name,
        memo: REVIEW[c].memo, site: p, on: byCode[c] === selected
      });
    });
    Object.keys(PINS).forEach(function (k) {
      const p = PINS[k];
      items.push({
        kind: 'pin', id: k, at: p.at || '',
        name: p.name || p.lat.toFixed(5) + ', ' + p.lon.toFixed(5),
        memo: p.memo, site: p, on: p === pin
      });
    });
    items.sort(function (a, b) { return b.at.localeCompare(a.at); });
    return items;
  }

  function renderSaved() {
    const list = document.getElementById('savedList');
    const items = savedItems();
    document.getElementById('savedN').textContent = items.length;

    if (!items.length) {
      list.innerHTML = '<div class="none">아직 저장한 곳이 없다.<br>'
        + '주차장 점은 <b>저장(S)</b>, 그 밖의 자리는 <b>우클릭</b> 뒤 '
        + '<b>이 자리 저장</b>.</div>';
      return;
    }
    list.innerHTML = items.map(function (it) {
      const s = it.site;
      const meta = (it.kind === 'pin' ? '핀 · ' : '')
        + (s.falchi ? 'Falchi ' + s.falchi + ' · ' : '')
        + (s.score !== null && s.score !== undefined
            ? s.score.toFixed(3) + ' · ' : '')
        + '1km 가로등 ' + (s.lampFar === undefined ? '—' : s.lampFar) + '개';
      return '<button class="item ' + it.kind + (it.on ? ' on' : '')
        + '" data-kind="' + it.kind + '" data-id="' + esc(it.id) + '">'
        + '<span class="nm">' + esc(it.name) + '</span>'
        + '<span class="mt">' + meta + '</span>'
        + (it.memo ? '<span class="memo">' + esc(it.memo) + '</span>' : '')
        + '</button>';
    }).join('');
    list.querySelectorAll('.item').forEach(function (el) {
      el.onclick = function () {
        const isPin = el.dataset.kind === 'pin';
        const p = isPin ? PINS[el.dataset.id] : DATA.parking[byCode[el.dataset.id]];
        map.panTo(new kakao.maps.LatLng(p.lat, p.lon));
        if (isPin) openPin(p); else select(byCode[el.dataset.id]);
      };
    });
  }

  function showRoadview(p) {
    const el = document.getElementById('rv');
    if (!rvClient) rvClient = new kakao.maps.RoadviewClient();
    const pos = new kakao.maps.LatLng(p.lat, p.lon);
    /* 반경 100m 안에 파노라마가 없으면 로드뷰가 없는 곳이다(농로·사유지 진입로).
       그 자체가 검토에 쓰이는 정보라 빈칸으로 두지 않고 그렇다고 적는다. */
    rvClient.getNearestPanoId(pos, 100, function (panoId) {
      if (panoId === null) {
        el.classList.add('none');
        el.textContent = '100m 안에 로드뷰 없음';
        roadview = null;
        return;
      }
      el.classList.remove('none');
      el.textContent = '';
      roadview = new kakao.maps.Roadview(el);
      roadview.setPanoId(panoId, pos);
    });
  }

  function commit(p, decision) {
    const memoEl = document.getElementById('memo');
    const memo = memoEl ? memoEl.value : '';
    fetch('/api/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: p.code, decision: decision, memo: memo })
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (!res.ok) { alert('저장 실패: ' + res.error); return; }
      if (decision === null) delete REVIEW[p.code];
      else REVIEW[p.code] = { decision: decision, memo: memo, at: res.at };
      select(selected);
    }).catch(function (err) { alert('저장 실패: ' + err); });
  }

  function renderProgress() {
    const bar = document.getElementById('bar');
    if (!bar) return;
    let saved = 0, rejected = 0;
    for (const code in REVIEW) {
      if (REVIEW[code].decision === 'saved') saved++; else rejected++;
    }
    const total = DATA.parking.length, done = saved + rejected;
    bar.innerHTML = '<b>' + saved + '</b> 저장 · ' + rejected + ' 제외'
      + '<span class="track"><i style="width:'
      + (100 * done / total).toFixed(1) + '%"></i></span>'
      + done + ' / ' + total;
  }

  /* 목록을 훑는 일이라 손이 자판에 있다 — 두 판단만 단축키로 뺀다. */
  document.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
    if (e.key === 'Escape') { select(-1); return; }
    if (selected < 0) return;
    const p = DATA.parking[selected];
    if (e.key === 's' || e.key === 'S') commit(p, 'saved');
    else if (e.key === 'x' || e.key === 'X') commit(p, 'rejected');
  });

  /* --- 조작 ---------------------------------------------------------------- */
  document.querySelectorAll('.controls input[data-layer]').forEach(function (el) {
    el.onchange = function () { show[el.dataset.layer] = el.checked; draw(); };
  });
  document.getElementById('onlyTodo').onchange = function () {
    onlyTodo = this.checked;
    draw();
  };
  const types = {
    roadmap: kakao.maps.MapTypeId.ROADMAP,
    hybrid: kakao.maps.MapTypeId.HYBRID
  };
  document.querySelectorAll('.controls .seg button').forEach(function (btn) {
    btn.onclick = function () {
      document.querySelectorAll('.controls .seg button').forEach(function (b) {
        b.classList.toggle('on', b === btn);
      });
      map.setMapTypeId(types[btn.dataset.type]);
    };
  });
  /* 범례 줄을 눌러 그 단계만 끄고 켠다 — 필터를 따로 만들 것 없이 범례가 곧 필터다. */
  document.querySelectorAll('.legend .row[data-bucket]').forEach(function (row) {
    row.onclick = function () {
      const i = +row.dataset.bucket;
      bucketOn[i] = !bucketOn[i];
      row.classList.toggle('off', !bucketOn[i]);
      draw();
    };
  });

  select(-1);
  draw();
}
</script>
"""

_PANELS = """
<div class="panel review" id="review"></div>
<div class="rail">
  <div class="panel controls">
    <h2>레이어</h2>
    {layers}
    <label><input type="checkbox" data-layer="lamps" checked> {lamp_name}</label>
    <h2>검토</h2>
    <label><input type="checkbox" id="onlyTodo"> 아직 안 본 곳만</label>
    <h2>배경</h2>
    <div class="seg">
      <button data-type="roadmap" class="on">일반</button>
      <button data-type="hybrid">스카이뷰</button>
    </div>
  </div>
  <div class="panel saved">
    <div class="head">
      <h2>저장한 곳</h2><span class="n" id="savedN">0</span>
    </div>
    <div class="list" id="savedList"></div>
  </div>
  <div class="panel legend">
    <h2>채움 — 반경 1km 가로등 개수</h2>
    {rows}
    <h2 style="margin-top:11px">테두리 — 검토 상태</h2>
    <div class="row"><span class="sw ring" style="border-color:{save}"></span>
      <span class="lbl">저장</span></div>
    <div class="row"><span class="sw ring" style="border-color:{reject}"></span>
      <span class="lbl">제외</span></div>
    <h2 style="margin-top:11px">모양 — 후보 출처</h2>
    <div class="row"><span class="sw" style="background:#c3c2b7"></span>
      <span class="lbl">공영주차장 (공공데이터)</span></div>
    <div class="row"><span class="sw box" style="background:#c3c2b7"></span>
      <span class="lbl">카카오맵 검색 장소</span></div>
    <h2 style="margin-top:11px">마름모 — 우클릭으로 찍은 지점</h2>
    <div class="row"><span class="sw pin" style="background:{save}"></span>
      <span class="lbl">저장한 핀</span></div>
    <div class="row"><span class="sw pin" style="background:{draft}"></span>
      <span class="lbl">아직 저장 안 함</span></div>
    <div class="foot">{foot}</div>
  </div>
</div>
<div class="sources">{sources}</div>
"""

_EMPTY = (
    '<div class="bar" id="bar"></div>'
    '<div class="empty">주차장 점을 누르면 그 자리의 광공해·좌표가 로드뷰와 함께 '
    '열린다. 저장(S)·제외(X)는 누르는 즉시 파일에 적힌다.<br><br>'
    '목록에 없는 자리는 지도 아무 데나 <b>우클릭</b> — 거기서도 어둡기를 재고 '
    '저장할 수 있다. 저장한 곳은 오른쪽 목록에 쌓인다.</div>'
)


def page(key: str, payload: dict, panels: str, review: dict, pins: dict) -> str:
    """페이로드·앱키를 HTML 골격에 주입한다(중괄호 충돌이 없도록 치환만 쓴다)."""
    marks = {
        code: {
            "decision": row["decision"],
            "memo": row["memo"],
            "at": row["reviewed_at"],
        }
        for code, row in review.items()
    }
    return (
        _HTML
        .replace("<!--__PANELS__-->", panels)
        .replace("/*__KEY__*/", key)
        .replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False))
        .replace("/*__REVIEW__*/", json.dumps(marks, ensure_ascii=False))
        .replace("/*__PINS__*/", json.dumps(pins, ensure_ascii=False))
    )


def source_list() -> list[dict]:
    """후보 출처 목록 — 레이어 토글·상세 칸이 이걸로 이름을 찾는다.

    카카오 쪽 이름은 `fetch_kakao_places.TARGETS`(검색어 정의)에서 그대로 가져온다.
    검색어와 화면 이름이 갈라지면 "공원 레이어에 왜 저게 있지"를 설명할 수 없다.
    """
    counts = places.counts()
    out = [{"key": "parking", "label": "공영주차장", "n": parking.COUNT}]
    out += [
        {
            "key": f"kakao_{target.key}",
            "label": f"카카오 {target.label}",
            "n": counts.get(target.key, 0),
        }
        for target in TARGETS
        if counts.get(target.key, 0)
    ]
    return out


def build_page(key: str, store: Store, pins: PinStore) -> str:
    """지도 페이지 한 장. 서버가 뜰 때 한 번 만들고 이후로는 그대로 낸다."""
    rows = candidate_rows()
    legend = assign_buckets(rows)
    sources = source_list()
    lat, lon = lamps.points()
    payload = {
        # 첫 화면은 가로등 분포의 외곽선에 맞춘다 — 제주 본섬 전체가 그 안에 든다.
        "view": {
            "bounds": [
                float(lat.min()), float(lon.min()),
                float(lat.max()), float(lon.max()),
            ]
        },
        "coordScale": _COORD_SCALE,
        "steps": list(_PARK_STEPS),
        "stateColor": {
            "saved": _SAVE_COLOR,
            "rejected": _REJECT_COLOR,
            "draft": _DRAFT_COLOR,
        },
        "emptyHtml": _EMPTY,
        "sources": sources,
        "parking": rows,
        "lamps": lamp_layer(),
    }
    panels = _PANELS.format(
        lamp_name=payload["lamps"]["name"],
        layers="\n    ".join(
            f'<label><input type="checkbox" data-layer="{s["key"]}" checked> '
            f'{s["label"]} <span class="n">{s["n"]:,}</span></label>'
            for s in sources
        ),
        save=_SAVE_COLOR,
        reject=_REJECT_COLOR,
        draft=_DRAFT_COLOR,
        rows="".join(
            f'<div class="row" data-bucket="{i}">'
            f'<span class="sw" style="background:{r["swatch"]}"></span>'
            f'<span><span class="lbl">{r["label"]}</span>'
            f'<br><span class="note">{r["note"]}</span></span></div>'
            for i, r in enumerate(legend)
        ),
        foot=(
            f"채움 경계는 후보 {len(rows):,}곳 분포의 사분위다(절대 기준 아님). "
            "줄을 눌러 단계를 끄고 켠다."
        ),
        sources="<br>".join(
            [parking.SOURCE, places.SOURCE, lamps.SOURCE,
             darkness.SOURCE, nightlight.SOURCE]
        ),
    )
    saved_pins = {
        key_: pin_payload(row) for key_, row in pins.all().items()
    }
    return page(key, payload, panels, store.all(), saved_pins)


# --- 서버 ---------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    """지도 한 장과 기록 둘(주차장 판단·우클릭 핀). 로컬 전용이라 그 이상 안 연다."""

    html: str
    store: Store
    pins: PinStore
    lots: dict

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    # do_GET·do_POST 이름은 BaseHTTPRequestHandler 규약이라 바꿀 수 없다.
    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(200, self.html.encode("utf-8"), "text/html; charset=utf-8")
        elif url.path == "/api/review":
            self._json(200, self.store.all())
        elif url.path == "/api/site":
            # 우클릭한 자리는 목록에 없다 — 그 좌표의 어둡기를 그때 잰다.
            query = parse_qs(url.query)
            try:
                lat = float(query["lat"][0])
                lon = float(query["lon"][0])
            except (KeyError, IndexError, ValueError):
                self._json(400, {"ok": False, "error": "lat·lon 이 필요합니다"})
                return
            self._json(200, site_fields(lat, lon))
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if self.path not in ("/api/review", "/api/pin"):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"ok": False, "error": "본문이 JSON 이 아닙니다"})
            return
        if self.path == "/api/pin":
            self._pin(req)
        else:
            self._review(req)

    def _review(self, req: dict) -> None:
        code = str(req.get("code", ""))
        decision = req.get("decision")
        lot = self.lots.get(code)
        if lot is None:
            self._json(400, {"ok": False, "error": f"모르는 후보 코드: {code}"})
            return
        if decision is not None and decision not in DECISIONS:
            self._json(400, {"ok": False, "error": f"모르는 판단: {decision}"})
            return

        at = self.store.put(code, decision, str(req.get("memo", "")).strip(), lot)
        self._json(200, {"ok": True, "at": at})

    def _pin(self, req: dict) -> None:
        if req.get("remove"):
            key = str(req.get("key", ""))
            if not self.pins.remove(key):
                self._json(400, {"ok": False, "error": f"없는 핀: {key}"})
                return
            self._json(200, {"ok": True})
            return

        try:
            lat = float(req["lat"])
            lon = float(req["lon"])
        except (KeyError, TypeError, ValueError):
            self._json(400, {"ok": False, "error": "lat·lon 이 필요합니다"})
            return

        row = self.pins.put(
            lat, lon, str(req.get("name", "")).strip(),
            str(req.get("memo", "")).strip(),
        )
        self._json(200, {"ok": True, "pin": pin_payload(row)})

    def log_message(self, fmt: str, *args) -> None:
        """기본 구현은 매 요청을 stderr 에 찍는다 — 판단 기록만 남기면 충분하다."""


class Server(ThreadingHTTPServer):
    """두 번째 실행이 조용히 같은 포트를 잡지 못하게 한다.

    `HTTPServer` 는 `SO_REUSEADDR` 를 켜 두는데, 윈도우에서는 그게 **이미 듣고 있는
    포트에도 붙을 수 있게** 만든다(리눅스와 다르다). 그러면 서버가 둘 떠서 요청이
    아무 쪽에나 가고, 코드를 고쳐도 옛 페이지가 나오는 일이 생긴다 — 고쳤는데 안
    고쳐진 것처럼 보이는, 가장 시간을 잡아먹는 종류의 오류다. 겹치면 그냥 실패한다.
    """

    allow_reuse_address = False


def main() -> None:
    key = env.require(
        _KEY_VAR,
        "카카오 콘솔 [앱 키 → JavaScript 키] · "
        f"[플랫폼 → Web] 에 http://localhost:{_PORT} 등록",
    )

    store = Store(path.PARKING_REVIEW)
    pins = PinStore(path.SPOT_PINS)
    Handler.store = store
    Handler.pins = pins
    # 판단을 받을 수 있는 후보 전부. `Store.put` 은 name·lat·lon 만 보므로
    # 두 종류(Parking·Place)를 한 사전에 그대로 담아도 된다.
    Handler.lots = {lot.code: lot for lot in parking.lots()}
    Handler.lots |= {f"kakao:{p.id}": p for p in places.places()}
    Handler.html = build_page(key, store, pins)

    try:
        server = Server(("127.0.0.1", _PORT), Handler)
    except OSError as exc:
        raise SystemExit(
            f"{_PORT} 포트를 이미 쓰고 있습니다 ({exc}).\n"
            "  먼저 뜬 서버가 **고치기 전 페이지**를 계속 내놓게 되므로 겹쳐 띄우지\n"
            "  않습니다. 그 창에서 Ctrl+C 로 끄고 다시 실행하세요."
        ) from exc

    done = len(store.all())
    saved = sum(1 for r in store.all().values() if r["decision"] == "saved")
    print(
        f"후보 {parking.COUNT + places.COUNT:,}곳"
        f" (공영주차장 {parking.COUNT:,} + 카카오 {places.COUNT:,})"
        f" · 가로등 {lamps.COUNT:,}개"
    )
    print(f"검토 {done:,}곳 완료 (저장 {saved:,} · 제외 {done - saved:,})")
    print(f"우클릭 핀 {len(pins.all()):,}곳")
    print(f"기록 → {path.PARKING_REVIEW}")
    print(f"     → {path.SPOT_PINS}")
    print(f"http://localhost:{_PORT}  (Ctrl+C 로 종료)")

    webbrowser.open(f"http://localhost:{_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료. 판단은 누를 때마다 이미 파일에 적혔습니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
