"""측정 하네스 — Host 애플리케이션 역할. LLM(Ollama)과 MCP 서버를 각각 컨테이너
바깥에서 부르고, 그 사이 시간을 쪼개어 기록한다.

시간 분해 (TEST_GUIDELINE.md §5.3):

    t_e2e = t_llm + t_tool_rtt + t_harness
            └ t_llm      Ollama 가 보고한 total_duration - load_duration 의 합
            └ t_tool_rtt call_tool 앞뒤로 잰 벽시계 (프로토콜·네트워크 포함)
            └ t_harness  나머지 (파싱·프롬프트 조립)

모델 적재 시간(load_duration)은 어떤 지표에도 넣지 않는다 — 8GB VRAM 이라 모델을
갈아 끼우는데, 그 비용을 지연으로 세면 모델 비교가 망가진다.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastmcp import Client

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://etri-jejuax-ollama:11434")
MCP_URL = os.getenv("MCP_URL", "http://jeju-star-mcp-server:11000/")

TODAY = "2026-08-20"

# 두 arm 이 공유하는 역할 문장. 도구 유무 말고는 프롬프트가 같아야 개선폭이 도구
# 덕인지 프롬프트 덕인지 갈린다.
#
# 그래서 **답변 형식 지시는 전부 여기 둔다** — "수치를 함께 써라"를 도구 쪽에만
# 주면 arm B 의 GFR 이 도구가 아니라 프롬프트 때문에 오른다. 아래 TOOL_SUFFIX 에는
# 도구가 없으면 뜻이 없는 문장(무엇을 인용할지·인자를 어떻게 채울지)만 남긴다.
SYSTEM_BASE = f"""당신은 제주도 밤하늘 별 관측을 돕는 한국어 비서입니다.
오늘은 {TODAY} (KST) 입니다.

원칙:
- 장소 이름·소요 시간·관측 등급 같은 수치는 정확해야 합니다.
- 확실하지 않은 것은 지어내지 말고 "확인되지 않았다"고 밝히세요.
- 제주도 밖의 일이나 별 관측과 무관한 질문은 답할 수 없다고 밝히세요.
- 이 대화는 한 번만 오갑니다. 사용자에게 되묻지 말고, 주어진 정보만으로 답하세요.
- 답에는 주행시간·도보시간·구름·관측 등급 같은 구체적인 수치를 함께 쓰세요.
- 답은 한국어로, 3~6문장으로 간결하게 쓰세요."""

SYSTEM_TOOL_SUFFIX = """

제공된 도구로 실제 데이터를 조회한 뒤 답하세요. 도구가 돌려준 값만 인용하고,
도구 결과에 없는 수치는 만들어 내지 마세요. 도구가 필요 없는 질문이면 도구를
부르지 말고 바로 답하세요.

인자가 모자라도 되묻지 마세요. 질문에서 알 수 있는 인자만 채워 부르고, 조건이
하나도 없으면 인자 없이 부르세요 — 나머지는 도구가 기본값으로 채웁니다.

답에 쓰는 수치는 전부 도구 결과에서 그대로 가져오세요.
도구 결과에 map_url 이 있으면 **답의 첫 줄**에 `지도: <주소>` 형태로 그대로 싣고,
그 아래에 장소별 상세를 쓰세요. 주소 줄은 문장 수에 세지 않습니다."""

_THINK = re.compile(r"<think>.*?</think>", re.S)
_JSON_OBJ = re.compile(r"\{.*\}", re.S)


def strip_think(text: str) -> str:
    return _THINK.sub("", text or "").strip()


# ────────────────────────────────────────────────────────────────────────
# LLM 컨테이너
# ────────────────────────────────────────────────────────────────────────

class Ollama:
    def __init__(self, url: str = OLLAMA_URL, timeout: float = 600.0):
        self.url = url.rstrip("/")
        self.http = httpx.Client(timeout=timeout)

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        num_ctx: int = 8192,
        num_predict: int = 1024,
        keep_alive: str = "10m",
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive,
            "options": {
                "temperature": 0,
                "top_p": 1.0,
                "top_k": 1,
                "seed": 42,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        }
        if tools:
            body["tools"] = tools
        # 사고 토큰은 지연·토큰 비교를 오염시키므로 끈다. 지원 안 하는 모델은 무시된다.
        body["think"] = False
        r = self.http.post(f"{self.url}/api/chat", json=body)
        if r.status_code >= 400:
            detail = r.text[:400]
            if "think" in detail or "does not support thinking" in detail:
                body.pop("think", None)
                r = self.http.post(f"{self.url}/api/chat", json=body)
            if r.status_code >= 400:
                raise OllamaError(r.status_code, r.text[:400])
        return r.json()

    def unload(self, model: str) -> None:
        try:
            self.http.post(
                f"{self.url}/api/chat",
                json={"model": model, "messages": [], "keep_alive": 0},
                timeout=120.0,
            )
        except Exception:
            pass

    def have(self, model: str) -> bool:
        r = self.http.get(f"{self.url}/api/tags", timeout=60.0)
        names = {m["name"] for m in r.json().get("models", [])}
        return model in names or f"{model}:latest" in names


class OllamaError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"ollama {status}: {detail}")
        self.status = status
        self.detail = detail


def supports_tools(err: OllamaError) -> bool:
    """이 오류가 '도구 미지원' 인가."""
    d = err.detail.lower()
    return not ("does not support tools" in d or "tool" in d and "support" in d)


def llm_seconds(resp: Dict[str, Any]) -> float:
    """모델 적재 시간을 뺀 순수 생성 시간(초)."""
    total = resp.get("total_duration") or 0
    load = resp.get("load_duration") or 0
    return max(0.0, (total - load) / 1e9)


# ────────────────────────────────────────────────────────────────────────
# MCP 컨테이너
# ────────────────────────────────────────────────────────────────────────

class Toolbox:
    """MCP 서버에 붙어 도구 스키마를 Ollama 형식으로 옮기고, 호출 시간을 잰다."""

    def __init__(self, client: Client, tools: List[Any], variant: str = "v0"):
        self.client = client
        self.mcp_tools = tools
        self.names = [t.name for t in tools]
        # v0 = 서버가 준 설명 그대로. v1 = MAID 구조로 증강한 설명(bench/tool_desc_v1.py).
        # 서버는 두 경우 모두 같다 — LLM 이 읽는 계약만 갈아 끼운다.
        self.variant = variant

    def _contract(self, t):
        """이 도구를 LLM 에게 어떤 설명·스키마로 보여줄 것인가."""
        desc, schema = (t.description or "").strip(), t.inputSchema
        if self.variant != "v0":
            import importlib
            mod = importlib.import_module(f"tool_desc_{self.variant}")
            desc, schema = mod.apply(t.name, schema, desc)
        return desc, schema

    @property
    def ollama_schema(self) -> List[Dict[str, Any]]:
        out = []
        for t in self.mcp_tools:
            desc, schema = self._contract(t)
            out.append({
                "type": "function",
                "function": {"name": t.name, "description": desc, "parameters": schema},
            })
        return out

    @property
    def prompt_schema(self) -> str:
        """도구 미지원 모델에게 프롬프트로 싣는 스키마."""
        out = []
        for t in self.mcp_tools:
            desc, schema = self._contract(t)
            props = schema.get("properties", {})
            out.append(
                {
                    "name": t.name,
                    "description": desc[:1200],
                    "arguments": {k: (v.get("description") or "")[:160]
                                  for k, v in props.items()},
                    "required": schema.get("required", []),
                }
            )
        return json.dumps(out, ensure_ascii=False, indent=1)

    async def call(self, name: str, args: Dict[str, Any]) -> Tuple[Optional[str], float, Optional[str]]:
        """(응답 텍스트, 왕복 초, 오류) — 오류면 텍스트가 None."""
        t0 = time.perf_counter()
        try:
            res = await self.client.call_tool(name, args)
            rtt = time.perf_counter() - t0
            text = res.content[0].text if res.content else ""
            return text, rtt, None
        except Exception as e:  # 스키마 거부·없는 도구·서버 오류
            return None, time.perf_counter() - t0, f"{type(e).__name__}: {e}"[:500]


async def open_toolbox(url: str = MCP_URL, variant: str = "v0"):
    client = Client(url)
    await client.__aenter__()
    tools = await client.list_tools()
    return client, Toolbox(client, tools, variant)


# ────────────────────────────────────────────────────────────────────────
# 에이전트 루프
# ────────────────────────────────────────────────────────────────────────

MAX_TOOL_CALLS = 2
MAX_TURNS = 4


def _parse_prompted(text: str) -> Optional[Dict[str, Any]]:
    """프롬프트 모드에서 도구 호출 한 줄을 뽑는다."""
    t = strip_think(text)
    m = _JSON_OBJ.search(t)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    name = d.get("tool") or d.get("name") or d.get("tool_name")
    if not name:
        return None
    args = d.get("arguments") or d.get("args") or d.get("parameters") or {}
    if not isinstance(args, dict):
        return None
    return {"name": name, "arguments": args}


def _extract_tool_calls(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"__unparsed__": args}
        calls.append({"name": fn.get("name"), "arguments": args or {}})
    return calls


async def run_case(
    llm: Ollama,
    box: Optional[Toolbox],
    model: str,
    case: Dict[str, Any],
    mode: str = "native",
) -> Dict[str, Any]:
    """한 케이스 한 시행. arm 은 box 유무로 정해진다(None 이면 baseline)."""
    t_start = time.perf_counter()
    trace: Dict[str, Any] = {
        "case_id": case["id"],
        "model": model,
        "arm": "baseline" if box is None else "mcp",
        "mode": mode if box is not None else "none",
        "tool_calls": [],
        "tool_errors": [],
        "t_llm": 0.0,
        "t_load": 0.0,      # 모델 적재 시간(진단용 — 지연 지표에는 안 들어간다)
        "t_tool_rtt": 0.0,
        "turns": 0,
        "prompt_tokens": 0,
        "eval_tokens": 0,
        "eval_seconds": 0.0,
        "error": None,
        "answer": "",
    }

    if box is None:
        system = SYSTEM_BASE
        tools = None
    elif mode == "native":
        system = SYSTEM_BASE + SYSTEM_TOOL_SUFFIX
        tools = box.ollama_schema
    else:  # prompted
        system = (
            SYSTEM_BASE
            + SYSTEM_TOOL_SUFFIX
            + "\n\n사용 가능한 도구:\n"
            + box.prompt_schema
            + '\n\n도구를 쓰려면 다른 말 없이 JSON 한 줄만 출력하세요: '
              '{"tool": "<도구이름>", "arguments": {...}}\n'
              "도구가 필요 없으면 그냥 한국어로 답하세요."
        )
        tools = None

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": case["question"]},
    ]

    used_calls = 0
    try:
        for _turn in range(MAX_TURNS):
            resp = llm.chat(model, messages, tools=tools)
            trace["turns"] += 1
            trace["t_llm"] += llm_seconds(resp)
            trace["t_load"] += (resp.get("load_duration") or 0) / 1e9
            trace["prompt_tokens"] += resp.get("prompt_eval_count") or 0
            trace["eval_tokens"] += resp.get("eval_count") or 0
            trace["eval_seconds"] += (resp.get("eval_duration") or 0) / 1e9
            msg = resp.get("message", {}) or {}
            content = msg.get("content") or ""

            calls: List[Dict[str, Any]] = []
            if box is not None and used_calls < MAX_TOOL_CALLS:
                if mode == "native":
                    calls = _extract_tool_calls(msg)
                else:
                    one = _parse_prompted(content)
                    calls = [one] if one else []

            if not calls:
                trace["answer"] = strip_think(content)
                break

            messages.append({"role": "assistant", "content": content,
                             **({"tool_calls": msg["tool_calls"]}
                                if mode == "native" and msg.get("tool_calls") else {})})

            for call in calls[:MAX_TOOL_CALLS - used_calls]:
                used_calls += 1
                name, args = call["name"], call["arguments"]
                trace["tool_calls"].append({"name": name, "arguments": args})
                if name not in box.names:
                    trace["tool_errors"].append(f"unknown tool: {name}")
                    result = f"오류: '{name}' 라는 도구는 없습니다. 사용 가능: {', '.join(box.names)}"
                else:
                    text, rtt, err = await box.call(name, args)
                    trace["t_tool_rtt"] += rtt
                    if err:
                        trace["tool_errors"].append(err)
                        result = f"오류: {err}"
                    else:
                        result = text
                if mode == "native":
                    messages.append({"role": "tool", "content": result, "name": name})
                else:
                    messages.append({"role": "user",
                                     "content": f"도구 {name} 결과:\n{result}\n\n"
                                                "이 결과만 근거로 사용자 질문에 한국어로 답하세요."})
    except Exception as e:
        trace["error"] = f"{type(e).__name__}: {e}"[:500]

    trace["t_e2e"] = time.perf_counter() - t_start
    trace["t_harness"] = max(0.0, trace["t_e2e"] - trace["t_llm"] - trace["t_tool_rtt"])
    return trace
