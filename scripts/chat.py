r"""cmd 에서 말로 물어보는 REPL — LLM 이 도구를 고르고 부르고, 그 답을 읽어 준다.

호스트 애플리케이션(외부 LLM 자리)을 흉내 내는 자리다. 등록 게이트웨이가 할 일을
로컬 ollama 로 대신할 뿐, MCP 쪽은 실제와 같은 경로를 탄다.

    python scripts\chat.py                     qwen3.5:4b 로 대화 시작
    python scripts\chat.py --model llama3.1:8b
    python scripts\chat.py --once "제주공항에서 30분 안에 별 보기 좋은 곳"

명령: /exit  /reset(대화 비우기)  /tools(도구 목록)  /model <이름>  /raw(도구 원문 토글)

도구 스키마·시스템 문장은 bench/harness.py 것을 그대로 쓴다 — 측정에 쓰는 계약과
여기서 보는 계약이 갈라지면, 손으로 해 본 느낌이 측정과 다른 것을 뜻하게 된다.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))   # harness 가 tool_desc_* 를 최상위로 부른다

os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11435")
os.environ.setdefault("MCP_URL", "http://127.0.0.1:11000/")

from harness import (  # noqa: E402
    Ollama, OllamaError, SYSTEM_BASE, SYSTEM_TOOL_SUFFIX,
    open_toolbox, strip_think,
)

# cp949 콘솔에 없는 글자로 죽지 않게. 원문 그대로 보려면 cmd 에서 `chcp 65001`.
try:
    sys.stdout.reconfigure(errors="replace")
    # 파이프로 물려 줄 때(`type 질문.txt | chat.py`)는 콘솔 코드페이지가 아니라
    # UTF-8 로 읽는다 — 대화창에 직접 칠 때는 콘솔 설정을 그대로 둔다.
    if not sys.stdin.isatty():
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MAX_TOOL_CALLS = 3   # 한 번 물어볼 때 도구를 몇 번까지 부르게 둘 것인가
MAX_TURNS = 5

# 벤치는 한 번만 오가지만 대화는 이어진다 — 그 한 줄만 바꿔 끼운다.
SYSTEM = (
    SYSTEM_BASE
    .replace(f"오늘은 {SYSTEM_BASE.split('오늘은 ')[1].split(' (KST)')[0]}",
             f"오늘은 {date.today().isoformat()}")
    .replace("- 이 대화는 한 번만 오갑니다. 사용자에게 되묻지 말고, 주어진 정보만으로 답하세요.\n",
             "- 앞선 대화를 기억하고 이어서 답하세요.\n")
    + SYSTEM_TOOL_SUFFIX
)


def _extract_calls(msg):
    out = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        out.append({"name": fn.get("name"), "arguments": args or {}})
    return out


async def ask(llm, box, model, messages, show_raw):
    """한 번 물어본 것에 대해 도구를 부르고 최종 답까지 만든다."""
    used = 0
    for _ in range(MAX_TURNS):
        try:
            resp = llm.chat(model, messages, tools=box.ollama_schema)
        except OllamaError as e:
            print(f"  [모델 오류] {e}")
            return
        msg = resp.get("message", {}) or {}
        content = msg.get("content") or ""
        calls = _extract_calls(msg) if used < MAX_TOOL_CALLS else []

        if not calls:
            answer = strip_think(content)
            print(f"\n{answer}\n")
            messages.append({"role": "assistant", "content": answer})
            return

        messages.append({"role": "assistant", "content": content,
                         "tool_calls": msg.get("tool_calls")})
        for call in calls[:MAX_TOOL_CALLS - used]:
            used += 1
            name, args = call["name"], call["arguments"]
            print(f"  → {name}({json.dumps(args, ensure_ascii=False)})")
            if name not in box.names:
                result = f"오류: '{name}' 라는 도구는 없습니다. 사용 가능: {', '.join(box.names)}"
            else:
                text, rtt, err = await box.call(name, args)
                result = f"오류: {err}" if err else text
                print(f"    {rtt:.2f}s · {len(result)}자" + (f" · {err}" if err else ""))
                if show_raw and not err:
                    try:
                        print(json.dumps(json.loads(result), ensure_ascii=False, indent=2))
                    except Exception:
                        print(result)
            messages.append({"role": "tool", "content": result, "name": name})
    print("  [도구를 너무 여러 번 불러 멈춥니다]")


async def main():
    p = argparse.ArgumentParser(description="MCP 도구를 쓰는 대화")
    p.add_argument("--model", default=os.getenv("CHAT_MODEL", "qwen3.5:4b"))
    p.add_argument("--url", default=os.getenv("MCP_URL"))
    p.add_argument("--ollama", default=os.getenv("OLLAMA_URL"))
    p.add_argument("--variant", default="v0", help="도구 설명 판 (v0=서버 원문 · v1 · v2 · v3)")
    p.add_argument("--raw", action="store_true", help="도구 응답 원문도 찍는다")
    p.add_argument("--once", help="한 번만 묻고 끝낸다")
    ns = p.parse_args()

    llm = Ollama(ns.ollama)
    if not llm.have(ns.model):
        print(f"ollama 에 '{ns.model}' 가 없습니다. `docker exec etri-jejuax-ollama "
              f"ollama pull {ns.model}` 로 받으세요.")
        return 2

    client, box = await open_toolbox(ns.url, ns.variant)
    try:
        print(f"MCP {ns.url} · 도구 {len(box.names)}개 ({', '.join(box.names)})")
        print(f"모델 {ns.model} · /exit 로 나감\n")

        messages = [{"role": "system", "content": SYSTEM}]
        show_raw = ns.raw

        if ns.once:
            print(f"> {ns.once}")
            messages.append({"role": "user", "content": ns.once})
            await ask(llm, box, ns.model, messages, show_raw)
            return 0

        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("/exit", "/quit"):
                break
            if line == "/reset":
                messages = [{"role": "system", "content": SYSTEM}]
                print("  [대화를 비웠습니다]")
                continue
            if line == "/raw":
                show_raw = not show_raw
                print(f"  [도구 원문 {'켬' if show_raw else '끔'}]")
                continue
            if line == "/tools":
                for t in box.mcp_tools:
                    first = (t.description or "").strip().splitlines()[0]
                    print(f"  {t.name}: {first}")
                continue
            if line.startswith("/model "):
                want = line.split(None, 1)[1].strip()
                if llm.have(want):
                    ns.model = want
                    print(f"  [모델 {want}]")
                else:
                    print(f"  [ollama 에 {want} 가 없습니다]")
                continue
            messages.append({"role": "user", "content": line})
            await ask(llm, box, ns.model, messages, show_raw)
    finally:
        await client.__aexit__(None, None, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
