# 제주 밤하늘 관측 MCP — 컨테이너 이미지
#
#   docker compose up -d --build      → http://127.0.0.1:11000/
#
# 코드(app.py·modules)와 데이터(data)는 이미지에 굽지 않고 compose 가 볼륨으로 물린다.
# 그래서 이 파일이 하는 일은 의존성 설치뿐이고, `docker run` 만으로는 뜨지 않는다.
#
# 베이스는 3.13 이다. 로컬 개발(uv, requires-python >=3.13)과 같은 인터프리터로
# 맞춰 둔 것 — 테스트를 통과한 그 파이썬에서 서버도 돌게 한다.
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Volumes: ./app.py:/app/app.py, ./modules:/app/modules, ./data:/app/data,
#          ./outputs:/app/outputs, ./.cache:/app/.cache
#
# data 는 `modules/path.py` 가 가리키는 자리 그대로다. 표고 격자(data/elevation)는
# 라이선스(CC BY-NC-SA)상 재배포하지 않지만, 도보 시간·경사는 배치가 미리 재어
# jeju_spots.json 에 박아 두므로 서버가 격자를 읽을 일이 없다.
#
# outputs 는 경로 지도(`/maps/{name}`)가 떨어지는 자리라 **쓰기 가능**해야 한다.
# .cache 는 Open-Meteo 응답 캐시 자리다(없어도 뜨지만 매번 외부 호출이 다시 나간다).

EXPOSE 11000

# 겉 주소(`MAP_BASE_URL`)는 바인딩 주소와 다르다 — 0.0.0.0 은 브라우저가 열 수 있는
# 주소가 아니다. ngrok 으로 노출하면 그 공개 URL 로 덮어 준다.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=11000 \
    MAP_BASE_URL=http://127.0.0.1:11000

# Default command (overridden by docker-compose)
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "11000"]
