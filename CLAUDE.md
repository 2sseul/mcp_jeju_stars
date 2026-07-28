# 제주 밤하늘 관측 MCP

좌표·시각 → 별이 보이는지 판정. 외부 LLM이 툴콜로 호출.
FastMCP(공식 `mcp` SDK) + LangGraph / uv / Python 3.13 / 온프레미스.

`server/core` 순수함수(astro·judge·tonight·darkness) · `clients` 네트워크 ·
`engine/graph.py` 조립 · `scripts` 배치 · `data` 정적(.py 없음)

## Do Not
- 임계값 임의 변경 — 전부 근거값 (`docs/decisions.md`)
- 경로를 `path.py` 밖에서 계산 · `Path(__file__)` 사용
- `sys.path` 조작 · de421.bsp 자동 다운로드 의존
- `core/`에 네트워크·LLM 호출
- Open-Meteo KMA 계열 모델 (제주 좌표 NaN)

## Done
`uv run ruff check .` F821 0개 · `uv run pytest` ·
경로/import 변경 시 파이프라인 실제 실행 (import 통과 ≠ 동작)

상세 → `docs/` (architecture · decisions · plan · status · conventions)
데이터 출처는 `docs/architecture.md` §1
PR은 `/pr` 커맨드. 규칙은 `.claude/commands/pr.md`