"""측정 실행기 — arm 별로 시행을 돌려 원자료(jsonl)를 남긴다.

    python run_bench.py --arm tool-floor            # 정답 + 도구 로직 시간
    python run_bench.py --arm baseline --arm mcp    # 본 측정 (6 모델)
    python run_bench.py --arm mcp --models qwen3.5:4b --reps 1   # 스모크

원자료 한 줄 = 한 시행. 채점 규칙을 나중에 고쳐도 다시 돌릴 필요 없이 재채점만
하면 되게, 최종 답변 원문과 도구 호출 인자를 그대로 남긴다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cases import CASES  # noqa: E402
from harness import (  # noqa: E402
    MCP_URL,
    Ollama,
    OllamaError,
    open_toolbox,
    run_case,
)

HERE = Path(__file__).parent
RESULTS = HERE / "results"
RAW = RESULTS / "raw"

# 화면 캡처의 6종. 표시 이름 → ollama 태그.
MODELS = {
    "Kanana-2-3B-instruct": "hf.co/mradermacher/kanana-2-3b-instruct-GGUF:Q4_K_M",
    "A.X-4.0-Light": "hf.co/mykor/A.X-4.0-Light-gguf:Q4_K_M",
    "EXAONE-3.5-7.8B": "exaone3.5:7.8b",
    "qwen3.5-4b": "qwen3.5:4b",
    "gemma4-e2b-it-qat": "gemma4:e2b-it-qat",
    "llama3.1-8b": "llama3.1:8b",
}


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


# ────────────────────────────────────────────────────────────────────────
# arm T — 정답 생성 + 도구 로직 시간
# ────────────────────────────────────────────────────────────────────────

async def tool_floor(reps: int = 3) -> None:
    client, box = await open_toolbox(MCP_URL)
    gold, timing = {}, {}
    try:
        for case in CASES:
            if not case["gold_tool"]:
                continue
            name, args = case["gold_tool"], case["gold_args"]
            # 첫 호출은 cold (도로 그래프·성좌표 적재, Open-Meteo 미캐시) — 따로 남긴다
            text, cold, err = await box.call(name, args)
            if err:
                print(f"  !! {case['id']} {name} → {err}")
                continue
            warm = []
            for _ in range(reps):
                text, rtt, err = await box.call(name, args)
                warm.append(rtt)
            gold[case["id"]] = {
                "tool": name,
                "args": args,
                "response": json.loads(text),
            }
            timing[case["id"]] = {
                "tool": name,
                "cold_s": round(cold, 4),
                "warm_median_s": round(statistics.median(warm), 4),
                "warm_all_s": [round(x, 4) for x in warm],
                "response_bytes": len(text),
            }
            print(f"  {case['id']:5s} {name:16s} cold={cold:6.3f}s "
                  f"warm={statistics.median(warm):6.3f}s  {len(text)}B")
    finally:
        await client.__aexit__(None, None, None)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "gold.json").write_text(
        json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "gold": gold},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    (RESULTS / "tool_timing.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  → {RESULTS/'gold.json'} · {RESULTS/'tool_timing.json'}")


# ────────────────────────────────────────────────────────────────────────
# arm A/B — 모델별 측정
# ────────────────────────────────────────────────────────────────────────

def detect_mode(llm: Ollama, tag: str, box) -> str:
    """이 모델이 native tool calling 을 받는가."""
    try:
        llm.chat(tag, [{"role": "user", "content": "안녕"}],
                 tools=box.ollama_schema, num_predict=8)
        return "native"
    except OllamaError as e:
        d = e.detail.lower()
        if "tool" in d:
            return "prompted"
        raise


async def measure(models: dict, arms: list, reps: int, case_filter=None,
                  variant: str = "v0") -> None:
    llm = Ollama()
    client, box = await open_toolbox(MCP_URL, variant)
    cases = [c for c in CASES if not case_filter or c["id"] in case_filter]
    RAW.mkdir(parents=True, exist_ok=True)
    modes = {}
    try:
        for label, tag in models.items():
            if not llm.have(tag):
                print(f"[skip] {label} ({tag}) — 내려받지 않음")
                continue
            mode = detect_mode(llm, tag, box)
            modes[label] = mode
            print(f"\n### {label}  ({tag})  tool-mode={mode}")

            for arm in arms:
                use_box = box if arm == "mcp" else None
                # 워밍업 1회 — 모델 적재·도구 cold 를 본 측정에서 뺀다
                await run_case(llm, use_box, tag, cases[0], mode)
                suffix = "" if variant == "v0" else f"__{variant}"
                out = RAW / f"{slug(label)}__{arm}{suffix}.jsonl"
                with out.open("w", encoding="utf-8") as f:
                    for rep in range(reps):
                        for case in cases:
                            t = await run_case(llm, use_box, tag, case, mode)
                            t["rep"] = rep
                            t["label"] = label
                            t["tag"] = tag
                            t["variant"] = variant if arm == "mcp" else "-"
                            f.write(json.dumps(t, ensure_ascii=False) + "\n")
                            f.flush()
                            flag = "!" if (t["error"] or t["tool_errors"]) else " "
                            print(f"  {arm:8s} r{rep} {case['id']:5s}{flag} "
                                  f"e2e={t['t_e2e']:6.2f}s llm={t['t_llm']:6.2f}s "
                                  f"tool={t['t_tool_rtt']:5.2f}s "
                                  f"tc={[c['name'] for c in t['tool_calls']]}")
                print(f"  → {out}")
            llm.unload(tag)   # 다음 모델에 8GB 를 비워 준다
    finally:
        await client.__aexit__(None, None, None)
        # 모델을 한 번에 하나씩 돌리므로(회선이 느려 받아지는 대로 잰다) 이 파일은
        # 덮어쓰지 말고 합친다 — 안 그러면 먼저 잰 모델의 도구모드가 지워진다.
        f = RESULTS / "modes.json"
        prev = {}
        if f.exists():
            try:
                prev = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                prev = {}
        prev.update(modes)
        f.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arm", action="append", default=[],
                   choices=["tool-floor", "baseline", "mcp"])
    p.add_argument("--models", nargs="*", default=None,
                   help="표시 이름 또는 ollama 태그 (생략 시 6종 전부)")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--cases", nargs="*", default=None, help="케이스 id 필터")
    p.add_argument("--variant", default="v0", choices=["v0", "v1", "v2"],
                   help="도구 설명 판본. v0=서버 그대로, v1·v2=증강(bench/tool_desc_<판본>.py)")
    a = p.parse_args()

    arms = a.arm or ["tool-floor", "baseline", "mcp"]
    sel = MODELS
    if a.models:
        sel = {k: v for k, v in MODELS.items() if k in a.models or v in a.models}
        for m in a.models:                      # 목록에 없는 태그도 그대로 받는다
            if m not in MODELS and m not in MODELS.values():
                sel[m] = m

    if "tool-floor" in arms:
        print("== arm T: tool-floor (정답 + 도구 로직 시간) ==")
        asyncio.run(tool_floor())
    live = [x for x in arms if x != "tool-floor"]
    if live:
        print(f"== arm {'/'.join(live)} · 모델 {len(sel)}종 · 반복 {a.reps} "
              f"· 도구설명 {a.variant} ==")
        asyncio.run(measure(sel, live, a.reps, a.cases, a.variant))


if __name__ == "__main__":
    main()
