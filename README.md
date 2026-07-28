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

- **박명** (태양 고도) — JPL DE421 천체력. 로컬 파일이라 오프라인·재현 가능, 미래 지평 없음
- **구름** (총운량) — Open-Meteo 예보. 시간별 약 7일 지평, 밖이면 '알 수 없음'
- **광공해** (SQM·Falchi) — NASA Black Marble 기반 Sky Brightness 래스터. 정적이라 날짜 무관

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

## 검증

```bash
uv run ruff check .     # F821 은 0개여야 한다
uv run pytest
```

## 구조

```
server/core/      순수 함수 (astro · judge · darkness · tonight) — 네트워크 호출 금지
server/clients/   외부 I/O (open_meteo · geocode) — 예외를 밖으로 던지지 않는다
server/engine/    LangGraph 조립
scripts/          오프라인 배치 (연 1회 래스터 전처리)
data/             정적 데이터 (.py 없음)
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

- 천체력 — JPL DE421 (via Skyfield)
- 기상 — Open-Meteo Forecast API
- 지오코딩 — Photon (Komoot, OpenStreetMap 기반)
- 광공해 — NASA Black Marble(VNP46A4/VJ146A4) 기반 lightpollutionmap.info 산출(sb_2025)
