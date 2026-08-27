# 제주 밤하늘 관측 MCP

관측지 추천 · 별이 보이는지 판정 · 접근성 조회. 외부 LLM이 툴콜로 호출.
fastmcp v2 + LangGraph / uv / Python 3.13 / 온프레미스.

`server/core` 순수함수(astro·ephem·judge·weather·moon·constellation·horizon·tonight·darkness·routing·spots·mapview) ·
`clients` 네트워크 ·
`engine/graph.py` 조립 · `tools.py` 도구 본체 · `maps.py` 지도 파일·주소 ·
`app.py` 진입점(등록·전송) ·
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
- 확인 안 된 도보 경로를 지도에 긋기 — 지도는 글보다 강하게 읽힌다 (`decisions.md` §2.31)
- `_JUNCTION_S` 를 근거 없이 바꾸기 — `scripts/check_route_calibration.py` 로 재보정한다
- 별자리·기온·바람·습도·강수확률로 등급 바꾸기 — 참고 정보다 (`decisions.md` §2.40·§2.42).
  **강수 예보(WMO ≥51)만 예외** — 차폐 축의 두 번째 신호로 '불가' cap (§2.41)
- 하늘 상태(맑음/비)를 `weather.py` 가 문장으로 말하기 — 해석표만 거기 두고 말은 `judge` 가 한다
- 별자리 목록을 개수로 자르기 — 1등성(V≤1.5)으로 거른다. "상위 3개"는 근거가 없다 (§2.42)
- 별 개수("오늘 밤 별 N개") 되살리기 — 폐기했다 (§2.14). 이름과 방향으로 답한다
- 지형 지평선을 단정으로 말하기 — 격자는 맨땅이라 방풍림·건물이 빠져 있다 (§2.43)

## Done
`uv run ruff check .` F821 0개 · `uv run pytest` ·
경로/import 변경 시 파이프라인 실제 실행 (import 통과 ≠ 동작)

상세 → `docs/` (architecture · decisions · plan · status · conventions)
데이터 출처는 `docs/architecture.md` §1
PR은 `/pr` 커맨드. 규칙은 `.claude/commands/pr.md`