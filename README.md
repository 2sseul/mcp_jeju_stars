# 제주 밤하늘 관측 MCP

좌표·시각을 받아 **별이 보이는지** 판정하는 MCP 서버. 외부 LLM이 툴콜로 호출한다.

FastMCP(공식 `mcp` SDK) + LangGraph · uv · Python 3.13 · 온프레미스.

## 무엇을 답하나

두 가지 질의를 지원한다.

| 질의 | 방법 | 답 |
|---|---|---|
| "지금 별 보이나?" | `scope="moment"` | 한 시각의 관측 등급 (최적 / 양호 / 밝은 별 한정 / 불가 / 알 수 없음) |
| "오늘 밤 볼 수 있나?" | `scope="night"` | 밤 전체를 시간별로 판정해 **관측 가능 시간 수·등급 분포·연속 창** 집계 |

판정은 세 축으로 이뤄진다.

- **박명** (태양 고도) — JPL DE421 천체력. 로컬 파일이라 오프라인·재현 가능. 예보 지평은 없고, 천체력이 덮는 기간(≈1900~2053) 밖이면 '입력 오류'
- **구름** (총운량) — Open-Meteo 예보. 시간별 약 7일 지평, 밖이면 '알 수 없음'
- **어둡기** (광공해) — 세 신호를 종합해 **등급 상한**으로 쓴다. 정적이라 날짜 무관
  - 하늘밝기 (SQM·Falchi) — NASA Black Marble 기반 Sky Brightness 래스터
  - 근거리 광원 (VIIRS 야간광) — 래스터가 뭉개는 바로 옆 광원을 잡는다
  - 가로등·보안등 근접도 — 공공데이터 9만 개 지점

임계값은 **전부 문헌값**이다. 근거는 `docs/decisions.md` §1 에 출처와 함께 정리돼 있다.

> 밤 집계는 "3시간 이상이면 관측 가능한 밤" 같은 기준으로 **가능/불가를 매기지 않는다**.
> 시간 수를 그대로 돌려주고 충분한지는 호출자가 정한다 — 근거 수치를 함께 주어 호출자가
> 판정을 재구성하게 하는, 이 프로젝트의 일관된 방식이다.

## 도구

도구는 **입력 방식으로만** 둘로 나뉜다. "한 시각이냐 밤 전체냐"는 파라미터다.

```python
evaluate_spot(lat, lon, date=None, time=None, scope="moment")   # 좌표
evaluate_place(query, date=None, time=None, scope="moment")     # 지명 → 지오코딩 후 동일 코어
```

응답은 언제나 같은 모양이다 — `verdict` / `reasons` / `numbers` / `attribution` / `as_of` / `resolved`.
`numbers`는 구조화 수치를 문장과 분리해 **LLM이 숫자를 지어내지 못하게** 한다.

## 실행

```bash
uv sync
uv run python -m server.mcp_server     # → http://127.0.0.1:8000/mcp
```

서버는 키가 없어도 뜬다 — 판정에 쓰는 데이터가 전부 로컬 파일이거나 무인증 API 이기
때문이다. 키는 아래 **배치 스크립트**만 쓴다. 이름은 `.env.example` 에 있다
(카카오 지도·로드뷰·주소검색 · 기상청 API허브 GK2A).

## 검증

```bash
uv run ruff check .     # F821 은 0개여야 한다
uv run pytest
```

## 구조

```
server/core/      순수 함수 — 네트워크 호출 금지
  판정에 들어간다  astro · judge · tonight
                  darkness(3신호 종합) · nightlight(VIIRS) · lamps(가로등)
  아직 안 들어간다 elevation(FABDEM 표고) · trail(탐방로 등급) · road(도로 근접)
                  parking(공영주차장) · places(카카오맵) · toilet(공중화장실)
                  cloud(GK2A 구름 마스크 → 운량 — 엔진 미연결, P7)
server/clients/   외부 I/O (open_meteo · geocode · gk2a) — 예외를 밖으로 던지지 않는다
server/engine/    LangGraph 조립 — astro → weather → darkness → judge
scripts/          오프라인 배치 (래스터 전처리 · 후보 발굴 · 관측지 편집 도구)
data/             정적 데이터 (.py 없음)
```

아래쪽 묶음은 **관측지 데이터를 만드는 축**이다(P9~P11). 지금은 `evaluate_*` 응답을
바꾸지 않는다 — 어두운 곳을 화장실이나 경사 때문에 떨어뜨리지 않는다는 뜻이다.

## 관측지 데이터

`data/jeju_spots.json` — 후보 156곳. 큐레이션과 자동 발굴(`sweep_place_candidates.py` ·
`merge_upland_parking.py`)을 합친 것이고, 주차·화장실·도보 경로 같은 칸은 사람이 채운다.

```bash
uv run python -m scripts.edit_spots      # 관측지 칸 채우기 — 지도에서 보고 그 자리에서 쓴다
uv run python -m scripts.review_parking  # 후보로 넣을지 판단
uv run python -m scripts.build_spot_report
```

도보 경로(`walk_routes`)는 **사람이 위성·로드뷰를 보고 찍은 것이 유일한 출처**다 —
OSM 도로망에 `footway`·`path`·`steps` 가 한 조각도 없고 지도 서비스도 오름 탐방로를
주지 않는다. 지금 14곳에 들어가 있다. 찍은 경로에서 표고·경사·거리를 재고,
국립공원공단 탐방로 등급제 배점을 그대로 매긴다(소요시간 항목은 원문에 배점표가
없어 제외 — `Grade.partial` 이 그것을 들고 나간다).

표고 격자는 라이선스(CC BY-NC-SA)상 커밋하지 않는다. 편집 도구를 처음 쓸 때 한 번:

```bash
uv run --with tifffile --with imagecodecs python -m scripts.build_elevation_grid
```

## 문서

| 문서 | 내용 |
|---|---|
| `docs/architecture.md` | 어떤 데이터를 / 어떻게 쓰고 / 왜 그렇게 판정하는가 |
| `docs/decisions.md` | 임계값·상수의 출처, 뒤집힌 결정과 그 이유 |
| `docs/plan.md` | 단계별 완료 기준과 회귀 픽스처 |
| `docs/status.md` | 어디까지 왔고 다음은 무엇인가 |
| `docs/conventions.md` | 커밋·코드·테스트 규칙 |
| `common/star_research_verified.md` | 계산식·상수의 학술 검증 결과 (원본 3종 통합본) |

## 데이터 출처

판정에 쓰는 것

- 천체력 — JPL DE421 (via Skyfield)
- 기상 — Open-Meteo Forecast API
- 지오코딩 — Photon (Komoot, OpenStreetMap 기반)
- 광공해 (하늘밝기) — Jurij Stare, www.lightpollutionmap.info · NASA's Black Marble
  nighttime lights product(VNP46A4/VJ146A4) 기반 산출 레이어(sb_2025)
- 야간광 — NASA's Black Marble nighttime lights product (VNP46A4)
- 가로등·보안등 — 공공데이터포털 제주시(52,019) · 서귀포시(38,022), 이용허락범위 제한 없음

관측지 데이터에 쓰는 것

- 표고 — FABDEM V1-2 (Hawker et al. 2022, Environ. Res. Lett. · Univ. of Bristol / Fathom,
  CC BY-NC-SA 4.0). 기반은 Copernicus DEM GLO-30 (ESA / Airbus). **맨땅(DTM)이라** 숲길
  오름에서 수관 높이를 밟고 걷는 것으로 계산되지 않는다
- 도로망 — OpenStreetMap 기여자 (Overpass API), Open Database License (ODbL)
- 공영주차장 — 공공데이터포털 주차장정보 표준데이터, 제주시(1,544행) · 서귀포시(113행)
- 공중화장실 — 공공데이터포털 전국 공중화장실 표준데이터(제주 849행). 원본에 좌표가 없어
  카카오맵 주소검색으로 변환(796행 확인)
- 장소 검색 — 카카오맵 (Kakao Corp.) 로컬 API
- 탐방로 등급 — 국립공원공단 「탐방로 등급제 정보」(2018-10-01)
- 위성 구름·안개 — 기상청 API허브 천리안 2A(GK2A) 기상산출물 경량화 조회 (P7, 엔진 미연결)
