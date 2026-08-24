"""로컬 Ollama 모델에 이 서버의 도구를 물려 대화한다.

모델이 어느 도구를 어떤 인자로 부르는지 stderr 로 찍고, 답을 stdout 으로 낸다.

    python bench/ask_local.py                     대화 모드 (프롬프트를 계속 입력)
    python bench/ask_local.py "성산일출봉 별 보여?"   한 번만 묻고 끝

모델은 MODEL 로 바꾼다:  set MODEL=qwen3.5:4b
"""
import asyncio
import json
import os
import sys

import requests
from fastmcp import Client

MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:11000/")
OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("MODEL", "qwen3.5:4b")
MAX_TURNS = 6

# 도구 설명만 8.6KB 다 — Ollama 기본 컨텍스트 4096 토큰으로는 도구 목록조차 다 못
# 넣어서, 모델이 "recommend_spots 를 부르면 되겠다"고 생각만 하고 빈 답을 낸다.
# 넉넉히 잡는다. 모자라면 NUM_CTX 로 더 올린다.
NUM_CTX = int(os.getenv("NUM_CTX", "16384"))


def chat(payload: dict) -> dict:
    payload = {**payload, "options": {"num_ctx": NUM_CTX}}
    resp = requests.post(f"{OLLAMA}/api/chat", json=payload, timeout=600)
    resp.raise_for_status()
    return resp.json()["message"]


async def answer(mcp: Client, tools: list, messages: list, question: str) -> None:
    """대화 기록(messages)에 이어 붙여 한 질문을 끝까지 처리한다."""
    messages.append({"role": "user", "content": question})

    for _ in range(MAX_TURNS):
        message = chat(
            {"model": MODEL, "messages": messages, "tools": tools, "stream": False}
        )
        messages.append(message)

        calls = message.get("tool_calls") or []
        if not calls:
            content = (message.get("content") or "").strip()
            if content:
                print(content)
            else:
                # 작은 모델은 도구 결과를 받고도 생각만 하다 빈 답을 내놓을 때가 있다.
                # 무엇을 하다 말았는지는 보여 준다 — 서버 잘못과 구분이 되어야 한다.
                thinking = (message.get("thinking") or "").strip()
                print("(모델이 빈 답을 냈다 — 도구 결과는 위 [tool] 줄 참고)")
                if thinking:
                    print(f"  생각 일부: {thinking[:300]}...", file=sys.stderr)
            return

        for call in calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            if isinstance(args, str):
                args = json.loads(args or "{}")
            print(f"[tool] {name} {json.dumps(args, ensure_ascii=False)}", file=sys.stderr)
            try:
                result = await mcp.call_tool(name, args)
                content = json.dumps(result.data, ensure_ascii=False)
            except Exception as error:  # 모델이 인자를 틀리면 그대로 되돌려 준다
                content = f"도구 실패: {error}"
                print(f"[tool] ↑ {content}", file=sys.stderr)
            messages.append({"role": "tool", "tool_name": name, "content": content})

    print("(도구 호출이 끝나지 않았다 — MAX_TURNS 초과)", file=sys.stderr)


async def main() -> None:
    async with Client(MCP_URL) as mcp:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.inputSchema,
                },
            }
            for t in await mcp.list_tools()
        ]
        print(f"[{MODEL}] 도구 {len(tools)}개 물림", file=sys.stderr)

        messages: list = []

        if len(sys.argv) > 1:  # 한 번만 묻는 모드
            await answer(mcp, tools, messages, " ".join(sys.argv[1:]))
            return

        # 대화 모드 — 빈 줄이나 Ctrl+Z(Enter) 로 끝낸다. `/new` 는 기록을 비운다.
        print("질문을 입력하세요. 빈 줄이면 끝, /new 면 대화 초기화.", file=sys.stderr)
        while True:
            try:
                question = input("\n> ").strip()
            except EOFError:
                break
            if not question:
                break
            if question == "/new":
                messages.clear()
                print("(대화 기록을 비웠다)", file=sys.stderr)
                continue
            try:
                await answer(mcp, tools, messages, question)
            except Exception as error:
                print(f"[에러] {error}", file=sys.stderr)


asyncio.run(main())
