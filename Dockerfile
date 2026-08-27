# 제주 밤하늘 관측 MCP — 컨테이너 이미지
#
# 2단계로 나눈다: 빌더에서 uv 로 .venv 를 만들고, 런타임에는 그 .venv 와
# 서버 코드·데이터만 옮긴다(uv·빌드 캐시·컴파일러가 이미지에 남지 않는다).
#
#   docker build -t jeju-star .
#   docker run --rm -p 8000:8000 jeju-star     → http://127.0.0.1:8000/mcp

# --- 빌더 ---------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 의존성만 먼저 설치한다 — 코드가 바뀌어도 이 레이어는 캐시에서 재사용된다.
# --frozen: uv.lock 을 그대로 쓴다(빌드 중에 락을 갱신하지 않는다 = 재현 가능).
# --no-dev: pytest·ruff 는 이미지에 넣지 않는다. scripts 그룹(tifffile 등)은
#           기본 그룹이 아니라 애초에 들어오지 않는다 — 배치 전용이다.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 프로젝트 자체 설치. README 는 pyproject 의 readme 필드가 가리키므로 빌드에 필요하다.
COPY README.md ./
COPY server ./server
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- 런타임 -------------------------------------------------------------------
FROM python:3.13-slim-bookworm

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MAP_BASE_URL=http://127.0.0.1:8000

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY server ./server

# 서버가 **실제로 읽는** 데이터만 넣는다(`server/path.py` 기준, 약 32MB).
# 저장소의 data/ 는 449MB 지만 대부분은 scripts 전용이다 — 토지대장·표고 격자·
# 도로망 원본(30MB JSON)은 배치가 쓰고 판정 경로는 건드리지 않는다.
#   ephem            → core/astro.py       (박명·천체력 DE421)
#   darkness         → core/darkness.py    (SQM 격자)
#   light_pollution  → core/nightlight.py  (VIIRS 야간광 격자)
#   streetlight      → core/lamps.py       (가로등)
#   jeju_spots.json  → core/spots.py       (검증된 관측지 63곳)
#   road_graph.npz   → core/routing.py     (주행시간 — 도로 그래프 CSR)
#   car_parking      → core/parking.py     (공영주차장 — 없으면 import 에서 죽는다)
#   kakao_places     → core/places.py      (오름·해변 주차장. 공영이 안 담는 것들)
#   toilet           → core/toilet.py      (공중화장실)
#
# **표고 격자(data/elevation)는 넣지 않는다.** 라이선스(CC BY-NC-SA)상 재배포하지
# 않고, 도보 시간·경사는 배치가 미리 재어 jeju_spots.json 에 박아 두므로 서버가
# 값을 읽을 일이 없다(`core/elevation.py` 가 격자 없이도 import 된다).
# core 모듈을 새로 붙이면 여기도 같이 늘려야 한다. 빠뜨리면 모듈이 import 시점에
# FileNotFoundError 로 죽으므로 컨테이너가 뜨자마자 드러난다.
COPY data/ephem/de421.bsp ./data/ephem/
COPY data/darkness/jeju_sb_grid.npz ./data/darkness/
COPY data/light_pollution/jeju_viirs_grid.npz ./data/light_pollution/
COPY data/streetlight ./data/streetlight
COPY data/jeju_spots.json ./data/
COPY data/road/jeju_road_graph.npz ./data/road/
COPY data/car_parking ./data/car_parking
COPY data/kakao_places ./data/kakao_places
COPY data/toilet ./data/toilet

# 예보 캐시(requests-cache) 자리. `server/path.py` 의 CACHE_DIR 과 같은 자리다.
#
# **볼륨으로 잡는 편이 좋다** — 컨테이너를 지우면 캐시도 사라지고, 그만큼 Open-Meteo
# 호출이 다시 나간다(관측지 63곳 하룻밤 기준 37회). 잡지 않아도 서버는 뜨고 돌지만
# 재시작마다 캐시가 비어 있다.
#
#   docker run -p 8000:8000 -v jeju-star-cache:/app/.cache jeju-star
#
# 경로 지도(`/maps/...`)도 같은 포트로 나간다. 겉 주소는 `MAP_BASE_URL` 이 정하는데,
# 바인딩 주소(0.0.0.0)는 브라우저가 열 수 있는 주소가 아니라 따로 둔다. 다른 기기에서
# 열어야 하면 `-e MAP_BASE_URL=http://<호스트>:8000` 으로 덮는다.
#
# VOLUME 을 선언해 두면 -v 를 잊어도 익명 볼륨이 붙어 컨테이너 수명 동안은 남는다.
#
# **소유권을 먼저 넘기고 VOLUME 을 선언한다.** Docker 는 VOLUME 선언 뒤에 그 경로에
# 가한 변경을 버리고, 실행 시 볼륨을 **선언 시점의 이미지 내용**으로 초기화한다.
# chown 이 뒤에 오면 볼륨이 root 소유로 만들어져 비루트 프로세스가 쓰지 못하고,
# 캐시가 조용히 죽어 매 호출이 그대로 나간다 — 볼륨을 넣은 목적과 정반대가 된다.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /app/.cache \
 && chown -R app:app /app
VOLUME ["/app/.cache"]

# 비루트로 돌린다.
USER app

EXPOSE 8000

# /mcp 는 MCP 헤더 없이 부르면 4xx 라 상태코드로 살아있음을 못 가린다.
# 포트가 열렸는지만 본다.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import os,socket; socket.create_connection(('127.0.0.1', int(os.environ['MCP_PORT'])), 2).close()"

CMD ["python", "app.py", "--host", "0.0.0.0"]
