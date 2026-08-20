#!/bin/sh
# 6종 모델을 ollama 컨테이너로 내려받는다.
# 회선이 자주 끊겨 pull 이 0 B/s 로 멈추므로, 태그마다 최대 8회까지 다시 붙인다
# (ollama 는 부분 blob 을 이어받는다). 실패해도 다음 태그로 넘어간다.
set -u
C=etri-jejuax-ollama
TAGS="
gemma4:e2b-it-qat
llama3.1:8b
exaone3.5:7.8b
hf.co/mradermacher/kanana-2-3b-instruct-GGUF:Q4_K_M
hf.co/mykor/A.X-4.0-Light-gguf:Q4_K_M
"
for t in $TAGS; do
  echo "=== PULL $t ==="
  i=1
  while [ $i -le 8 ]; do
    if docker exec $C ollama pull "$t" >/dev/null 2>&1; then
      echo "=== OK $t (attempt $i) ==="
      break
    fi
    echo "--- retry $i for $t ---"
    i=$((i+1))
    sleep 5
  done
  [ $i -gt 8 ] && echo "=== FAIL $t ==="
done
echo "=== FINAL LIST ==="
docker exec $C ollama list
