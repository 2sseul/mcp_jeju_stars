#!/bin/sh
# 모델이 내려받아지는 대로 하나씩 본 측정을 돌린다(회선이 느려 전부 기다릴 수 없다).
# 측정은 전부 bench 컨테이너 안에서 — Host LLM·MCP 서버와 같은 네트워크에서 — 돈다.
#
# 이미 72행(24케이스 × 3회)이 찬 모델은 건너뛴다. 중간에 죽어도 다시 돌리면 이어진다.
set -u
CO="docker compose -f bench/docker-compose.bench.yml run --rm -T bench"
TAGS="
qwen3.5:4b|qwen3.5-4b
gemma4:e2b-it-qat|gemma4-e2b-it-qat
llama3.1:8b|llama3.1-8b
exaone3.5:7.8b|EXAONE-3.5-7.8B
hf.co/mradermacher/kanana-2-3b-instruct-GGUF:Q4_K_M|Kanana-2-3B-instruct
hf.co/mykor/A.X-4.0-Light-gguf:Q4_K_M|A.X-4.0-Light
"
for pair in $TAGS; do
  t=$(echo "$pair" | cut -d'|' -f1)
  lb=$(echo "$pair" | cut -d'|' -f2)
  f="bench/results/raw/$(echo "$lb" | tr -c 'A-Za-z0-9._-' '_')__mcp.jsonl"
  if [ -f "$f" ] && [ "$(wc -l < "$f")" -ge 72 ]; then
    echo "=== SKIP $t (이미 측정됨) ==="
    continue
  fi
  # 최대 3시간까지 내려받기를 기다린다. 그 안에 안 오면 건너뛴다.
  i=0
  while [ $i -lt 360 ]; do
    if docker exec etri-jejuax-ollama ollama list | grep -qF "$t"; then break; fi
    i=$((i+1)); sleep 30
  done
  if ! docker exec etri-jejuax-ollama ollama list | grep -qF "$t"; then
    echo "=== SKIP $t (아직 못 받음) ==="
    continue
  fi
  echo "=== MEASURE $t ==="
  $CO python -u run_bench.py --arm baseline --arm mcp --models "$t" --reps 3 2>&1 \
    | grep -E "^\s+(baseline|mcp) |^###|^\[skip\]" || true
  echo "=== DONE $t ==="
done
echo "=== ALL DONE ==="
