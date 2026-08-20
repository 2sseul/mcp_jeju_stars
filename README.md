# 제주 밤하늘 관측 MCP — 배포 묶음

관측지 추천 · 별이 보이는지 판정 · 접근성 조회. 외부 LLM 이 툴콜로 호출한다.

이 폴더는 **돌리는 데 필요한 것만** 담은 배포용 묶음이다. 개발 저장소
(`mcp_jeju_star`)에서 서버가 실제로 읽는 파일만 추려 왔다 — 배치 스크립트·테스트·
문서·원본 래스터는 여기 없다(454MB → 34MB).

구조는 등록 게이트웨이 예제(`etri-jejuax-example-mcp`)를 그대로 따른다.

## 띄우기

```bash
docker compose up -d --build          # → http://127.0.0.1:11000/
docker compose logs -f ngrok          # 공개 URL (http://localhost:4040 에서도 보인다)
```

로컬에서 직접:

```bash
pip install -r requirements.txt
python app.py                         # → http://127.0.0.1:11000/
```

## 나가는 주소

| 경로 | 무엇 |
|---|---|
| `/` | **MCP 엔드포인트** (streamable HTTP). 게이트웨이에 등록하는 것이 이 주소다 |
| `/health` | 헬스체크 |
| `/maps/{name}` | 도구가 만든 경로 지도(정적 HTML). 응답의 `map_url` 이 가리킨다 |

## 도구 셋 — 질문의 목적으로 나뉜다

좌표냐 지명이냐는 입력 형태일 뿐이라 도구를 가르지 않는다.

| 도구 | 답하는 질문 |
|---|---|
| `recommend_spots` | "어디로 갈까" — 조건에 맞는 관측지를 검증된 62곳에서 고른다 |
| `evaluate_place` | "여기 별 보여?" — 지목한 장소 하나를 판정한다(미등록 장소도) |
| `spot_details` | "거기 어때?" — 주차·도보·야간 출입·반려동물·화장실 |

등록해 보는 예시는 `example.py`.

## 환경변수

`.env` 로 넣거나 컨테이너 환경변수로 준다 — **환경변수가 파일보다 우선**한다.

| 이름 | 없으면 |
|---|---|
| `NGROK_AUTHTOKEN` | ngrok 컨테이너가 못 뜬다 (서버 자체는 뜬다) |
| `MAP_BASE_URL` | `http://127.0.0.1:11000` — **공개 URL 이 정해지면 그 주소로 바꿔야** 지도 링크가 밖에서 열린다. 바인딩 주소 `0.0.0.0` 은 브라우저가 열 수 있는 주소가 아니다 |
| `MCP_PORT` | 11000 |
| `VWORLD_API_KEY` | 지도 배경이 Esri World Imagery 로 떨어진다(z18. VWorld 는 z19) |
| `KAKAO_REST_API_KEY` · `KMA_API_KEY` | 판정에 쓰지 않는다(배치 전용) |

> **`.env` 에는 실제 키가 들어 있다.** 이 폴더를 남에게 넘기거나 저장소에 올릴 때는
> `.env` 를 빼고 `.env.example` 만 보낸다. `.gitignore` 가 걸어 두었다.

판정에 쓰는 데이터는 전부 로컬 파일이거나 무인증 API 라, **키가 하나도 없어도 서버는
뜨고 도구는 답한다**.

## 폴더

```
app.py            진입점 — REST 앱을 MCP 서버로 바꾸고(streamable HTTP) 띄운다
modules/
  routes.py       FastAPI 라우트 3개 = MCP 도구 3개. 외부 LLM 이 읽는 계약이 여기 있다
  shared.py       앱 껍데기(CORS)
  tools.py        도구 본체 — MCP 를 모르는 순수 함수
  core/           순수 함수 — 네트워크 호출 금지
  clients/        외부 I/O (open_meteo · geocode · gk2a)
  engine/         LangGraph 조립 — astro → weather → darkness → judge
  path.py         모든 데이터 경로 상수
data/             정적 데이터 (.py 없음). 34MB 대부분이 천체력 de421.bsp(17M)와 가로등(9.1M)
outputs/maps/     경로 지도가 떨어지는 자리 — 쓰기 가능해야 한다
.cache/           Open-Meteo 예보 캐시 — 비면 재시작마다 외부 호출이 다시 나간다
```

## 저장소에서 다시 뽑을 때

코드를 고쳤으면 `app.py` 와 `modules/**/*.py` 만 덮어쓰면 된다. `data/` 는 배치를
다시 돌린 게 아니면 그대로 둔다.
