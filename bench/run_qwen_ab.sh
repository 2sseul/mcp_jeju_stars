#!/bin/sh
# qwen3.5:4b 단독 — 도구 설명 판본 A/B.
#   baseline : 도구 없음 (절대 기준)
#   mcp v0   : 서버가 준 설명 그대로
#   mcp v1   : MAID 구조로 증강한 설명 (bench/tool_desc_v1.py)
# 세 arm 의 시스템 프롬프트는 같다 — 다른 것은 도구 유무와 도구 설명뿐이다.
set -eu
CO="docker compose -f bench/docker-compose.bench.yml run --rm -T bench"
$CO python -u run_bench.py --arm baseline --arm mcp --models qwen3.5:4b --reps 3 --variant v0 2>&1 \
  | grep -E "^\s+(baseline|mcp) |^###" || true
$CO python -u run_bench.py --arm mcp --models qwen3.5:4b --reps 3 --variant v1 2>&1 \
  | grep -E "^\s+(baseline|mcp) |^###" || true
echo "=== ALL DONE ==="
