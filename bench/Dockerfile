# 측정 하네스 컨테이너 — Host 애플리케이션 역할(MCP 클라이언트 + 에이전트 루프).
# LLM 도, 판정 로직도 여기 없다. 둘 다 다른 컨테이너에 있고 네트워크로만 부른다.
FROM python:3.13-slim

WORKDIR /bench
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    OLLAMA_URL=http://etri-jejuax-ollama:11434 \
    MCP_URL=http://etri-jejuax-jeju-star-mcp:11000/

CMD ["python", "run_bench.py"]
