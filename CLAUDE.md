# 제주 밤하늘 관측 MCP

관측지 추천 · 별이 보이는지 판정 · 접근성 조회. 외부 LLM이 툴콜로 호출.
fastmcp v2 + LangGraph / uv / Python 3.13 / 온프레미스.

`server/core` 순수함수(astro·judge·tonight·darkness·routing·spots) · `clients` 네트워크 ·
`engine/graph.py` 조립 · `tools.py` 도구 본체(순수 함수) · `app.py` 진입점(등록·전송) ·
`scripts` 배치 · `data` 정적(.py 없음)

도구 3개는 **질문 목적**으로 나눈다 — `recommend_spots`(어디로) · `evaluate_place`(여기 별 보여?)
· `spot_details`(거기 어때?). 입력 형태(좌표/지명)로 가르지 않는다.

## Do Not
- 임계값 임의 변경 — 전부 근거값 (`docs/decisions.md`)
- 경로를 `path.py` 밖에서 계산 · `Path(__file__)` 사용
- `sys.path` 조작 · de421.bsp 자동 다운로드 의존
- `core/`에 네트워크·LLM 호출
- `tools.py`에 `@mcp.tool` — 등록은 `app.py`만 (판정 함수는 평범한 함수로 남긴다)
- Open-Meteo KMA 계열 모델 (`models=kma_*`) — 전 변수·전 지점 null (`decisions.md` §2.30)
- 거리를 직선거리로 재기 — 한라산이 가운데라 뒤집힌다. `core/routing.py` 를 쓴다
- `_JUNCTION_S` 를 근거 없이 바꾸기 — `scripts/check_route_calibration.py` 로 재보정한다

## Done
`uv run ruff check .` F821 0개 · `uv run pytest` ·
경로/import 변경 시 파이프라인 실제 실행 (import 통과 ≠ 동작)

상세 → `docs/` (architecture · decisions · plan · status · conventions)
데이터 출처는 `docs/architecture.md` §1
PR은 `/pr` 커맨드. 규칙은 `.claude/commands/pr.md`