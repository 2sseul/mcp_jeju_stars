"""채점 + 리포트 생성 — TEST_GUIDELINE.md §5 의 구현.

채점은 전부 규칙 기반이다. LLM 판정자를 쓰지 않는 것은 재현성 때문이다
(판정자 모델이 바뀌면 숫자가 흔들린다).

    python score.py                 → results/RESULT_<날짜>.md
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cases import BY_ID, CASES  # noqa: E402

HERE = Path(__file__).parent
RESULTS = HERE / "results"
RAW = RESULTS / "raw"
DATA = HERE.parent / "data" / "jeju_spots.json"


# ────────────────────────────────────────────────────────────────────────
# 값 꺼내기
# ────────────────────────────────────────────────────────────────────────

_SEG = re.compile(r"([^.\[\]]+)(\[(\*|\d+)\])?")


def jpath(obj, path: str):
    """`spots[*].drive.minutes` 같은 경로로 값을 전부 꺼낸다."""
    cur = [obj]
    for seg in path.split("."):
        m = _SEG.fullmatch(seg)
        if not m:
            return []
        key, _, idx = m.groups()
        nxt = []
        for c in cur:
            if not isinstance(c, dict) or key not in c:
                continue
            v = c[key]
            if idx is None:
                nxt.append(v)
            elif idx == "*":
                nxt.extend(v if isinstance(v, list) else [])
            else:
                if isinstance(v, list) and len(v) > int(idx):
                    nxt.append(v[int(idx)])
        cur = nxt
    return [c for c in cur if c is not None]


def nums_in(obj, out=None):
    """중첩 구조 안의 모든 수(문자열 안의 수 포함)."""
    if out is None:
        out = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for t in re.findall(r"\d+(?:\.\d+)?", obj):
            out.add(float(t))
    elif isinstance(obj, dict):
        for v in obj.values():
            nums_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            nums_in(v, out)
    return out


# ────────────────────────────────────────────────────────────────────────
# 답변 채점
# ────────────────────────────────────────────────────────────────────────

_URL = re.compile(r"https?://\S+")
_UNIT_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(분|시간|시|km|킬로미터|미터|m|%|퍼센트|등급|도)")
_PLACE = re.compile(
    # 가운뎃점을 넣지 않는다 — 넣으면 모델이 쓴 "서·해안"·"중산간·야영장" 같은
    # 지역·분류 표기를 장소 이름으로 잘못 집어 유효율이 실제보다 낮게 나온다.
    r"[가-힣A-Za-z0-9]{2,12}?"
    r"(?:오름|해수욕장|해변|해안|폭포|공원|전망대|계곡|포구|목장|주차장|휴게소|"
    r"야영장|방파제|저수지|비행장|생태숲|코지|봉|사)"
)
# "모른다 / 확인되지 않았다 / 내 범위가 아니다" 를 밝혔는가.
# 거절 어미가 한국어에서 여러 갈래라(…못합니다 / …수 없습니다 / …어렵습니다)
# 어미까지 넣어 둔다. 이 정규식은 abstain 케이스에서만 쓴다.
_ABSTAIN = re.compile(
    r"확인되지\s*않|확인할\s*수\s*없|확인\s*불가|확실하지\s*않|정확하지\s*않|"
    r"알\s*수\s*없|모르|모릅|정보가\s*없|다루지\s*않|지원하지\s*않|"
    r"범위\s*(?:가\s*아니|밖|를\s*벗어)|제주(?:도)?\s*(?:밖|외|가\s*아니)|"
    r"대상이\s*아니|전문(?:가)?(?:가|는)?\s*아니|"
    r"수(?:는|가|도)?\s*없|못\s*합니다|못\s*해요|못\s*드립|드릴\s*수\s*는\s*없|"
    r"어렵습니다|어려워요|드리기\s*어렵"
)


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def answer_numbers(text: str) -> list:
    t = _URL.sub(" ", text or "")
    t = re.sub(r"\d{4}-\d{2}-\d{2}", " ", t)     # 날짜는 수치 주장으로 세지 않는다
    return [float(m.group(1)) for m in _UNIT_NUM.finditer(t)]


def all_numbers(text: str) -> list:
    t = _URL.sub(" ", text or "")
    t = re.sub(r"\d{4}-\d{2}-\d{2}", " ", t)
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]


def close(a: float, b: float, tol: float) -> bool:
    if abs(a - b) <= tol:
        return True
    return abs(round(a) - round(b)) <= tol


def fact_hits(answer: str, gold_resp: dict, specs: list):
    """(맞춘 개수, 전체 개수, 놓친 값들)"""
    a_norm = norm(answer)
    a_nums = all_numbers(answer)
    hit = miss = 0
    missed = []
    for spec in specs:
        vals = jpath(gold_resp, spec["path"])
        for v in vals:
            if spec["kind"] == "text":
                toks = [norm(t) for t in str(v).split() if len(t.strip()) > 0]
                ok = bool(toks) and all(t in a_norm for t in toks)
            else:
                tol = spec.get("tol", 1.0)
                ok = any(close(n, float(v), tol) for n in a_nums)
            if ok:
                hit += 1
            else:
                miss += 1
                missed.append(f"{spec['path']}={v}")
    return hit, hit + miss, missed


def fabricated(answer: str, gold_resp: dict, question: str):
    """(근거 없는 수치 개수, 전체 수치 주장 개수)"""
    allowed = nums_in(gold_resp) | set(all_numbers(question))
    claims = answer_numbers(answer)
    bad = 0
    for n in claims:
        if not any(abs(n - a) <= max(0.5, 0.02 * abs(a)) for a in allowed):
            bad += 1
    return bad, len(claims)


_MAP_STEM = re.compile(r"/maps/([0-9a-fA-F]{6,})")


def map_relayed(answer: str, gold_map: str) -> bool:
    """도구가 준 지도 주소를 답변이 그대로 옮겼는가.

    도메인이 아니라 `/maps/<해시>` 조각으로 맞춘다. 겉면 주소(MAP_BASE_URL)는
    ngrok 터널이 바뀌면 같이 바뀌지만 파일 이름은 지도 내용에서 나온 해시라
    그대로다. 해시를 모델이 우연히 지어낼 일은 없으므로 사실상 정확 일치다.
    """
    m = _MAP_STEM.search(gold_map or "")
    if not m:
        return False
    return m.group(1).lower() in (answer or "").lower()


def place_validity(answer: str, known: set):
    cands = {m.group(0) for m in _PLACE.finditer(answer or "")}
    if not cands:
        return 0, 0
    good = 0
    for c in cands:
        cn = norm(c)
        if any(cn in k or k in cn for k in known):
            good += 1
    return good, len(cands)


def args_match(pred: dict, want: dict) -> bool:
    for k, v in want.items():
        if k not in pred:
            return False
        p = pred[k]
        if isinstance(v, bool):
            if bool(p) is not v:
                return False
        elif isinstance(v, (int, float)):
            try:
                if abs(float(p) - float(v)) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
        else:
            # 지명·출발지 같은 자유 문자열은 부분 일치도 인정한다.
            # '1100고지 휴게소'를 '1100고지'로 넘겨도 서버가 같은 곳으로 푼다.
            a, b = norm(str(p)), norm(str(v))
            if not a:
                return False
            if a != b and not (a in b or b in a):
                return False
    return True


def slot_f1(pred: dict, gold: dict):
    pk = {(k, norm(str(v))) for k, v in (pred or {}).items() if v is not None}
    gk = {(k, norm(str(v))) for k, v in gold.items() if v is not None}
    if not pk and not gk:
        return 1.0, 1, 1
    inter = len(pk & gk)
    return inter, len(pk), len(gk)


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - s) / d, (c + s) / d)


# ────────────────────────────────────────────────────────────────────────
# 집계
# ────────────────────────────────────────────────────────────────────────

def load_verdicts() -> dict:
    """사람이 채운 판정. (모델, arm, 케이스) → (O/X, 메모).

    review.py 가 만든 results/verdicts.csv 를 읽는다. 없으면 빈 dict —
    사람 채점은 선택이고, 없으면 리포트에서 그 절이 통째로 빠진다.
    """
    import csv
    f = RESULTS / "verdicts.csv"
    if not f.exists():
        return {}
    out = {}
    with f.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            v = (row.get("verdict") or "").strip().upper()
            if v in ("O", "X"):
                out[(row["model"], row["arm"], row["case_id"])] = (
                    v, (row.get("note") or "").strip())
    return out


def load_known_places() -> set:
    try:
        d = json.loads(DATA.read_text(encoding="utf-8"))
        return {norm(s["name_ko"]) for s in d["spots"]}
    except Exception:
        return set()


def score_run(run: dict, gold: dict, known: set) -> dict:
    case = BY_ID[run["case_id"]]
    g = gold.get(run["case_id"], {})
    resp = g.get("response", {})
    ans = run.get("answer", "") or ""
    out = {"case_id": case["id"], "category": case["category"]}

    # 도구 사용 (mcp arm 전용)
    calls = run.get("tool_calls") or []
    first = calls[0] if calls else None
    out["called"] = bool(calls)
    if case["gold_tool"] is None:
        out["tsa"] = (not calls)
        out["aem"] = None
        out["f1_parts"] = None
    else:
        out["tsa"] = bool(first and first["name"] == case["gold_tool"])
        wants = case.get("accept") or [{k: case["gold_args"][k] for k in case["required"]}]
        out["aem"] = bool(out["tsa"] and any(args_match(first["arguments"], w) for w in wants))
        out["f1_parts"] = slot_f1(first["arguments"] if first else {}, case["gold_args"])
    out["invalid"] = bool(run.get("tool_errors"))

    # 답변 품질
    hit, tot, missed = fact_hits(ans, resp, case.get("facts", []))
    out["gfr_parts"] = (hit, tot)
    out["missed"] = missed
    bad, claims = fabricated(ans, resp, case["question"]) if resp else (0, 0)
    out["fnr_parts"] = (bad, claims)
    if case["category"] == "recommend":
        good, cand = place_validity(ans, known)
        out["pnr_parts"] = (good, cand)
    else:
        out["pnr_parts"] = None

    # 지도 링크 전달 — 도구가 map_url 을 준 케이스에서만 분모가 선다.
    # 이 서버의 산출물 하나가 지도인데, 모델이 안 옮기면 사용자에게 닿지 않는다.
    #
    # 세 가지를 전부 `/maps/<해시>` 조각으로 맞춘다. 겉면 주소(MAP_BASE_URL)는
    # 배포마다 다르다 — 정답은 ngrok 주소로, 실제 측정은 127.0.0.1 로 만들어졌으므로
    # 전체 문자열로 비교하면 같은 지도인데도 전부 불일치로 세어진다(실제로 그렇게
    # 세어 0/60 이 나왔다. 답변은 처음부터 주소를 제대로 싣고 있었다).
    gmap = resp.get("map_url") if resp else None
    urls = _URL.findall(ans or "")
    if gmap:
        first_line = ans.split("\n")[0] if ans else ""
        out["map_parts"] = (int(map_relayed(ans, gmap)), 1)
        out["mapfirst_parts"] = (int(map_relayed(first_line, gmap)), 1)
    else:
        out["map_parts"] = None
        out["mapfirst_parts"] = None

    # 지어낸 지도 주소 — 답에 있는데 도구가 준 그 지도가 아닌 것.
    # v1 첫 판에서 도구 설명의 예시 URL 을 그대로 베끼는 일이 있어 따로 센다.
    stem = _MAP_STEM.search(gmap or "")
    stem = stem.group(1).lower() if stem else None
    fake = [u for u in urls if not (stem and stem in u.lower())]
    out["mapfake_parts"] = (len(fake), len(urls)) if urls else (0, 0)

    # 실패를 네 갈래로 나눈다. "틀렸다"만 세면 설명을 어디부터 고칠지 알 수 없다.
    #   tool     — 다른 도구를 골랐다        → 의도 명확화·키워드 배치 문제
    #   param    — 도구는 맞고 인자가 틀렸다  → 인자 주석의 형식·범위·제외가 모자람
    #   workflow — 사전 조건 도구를 안 불렀다 → [사전 조건]·[다음] 힌트가 모자람
    #   ground   — 호출은 옳고 답이 근거를 놓쳤다 → 응답 산문·결과 인용 문제
    # 이 서버에는 성능 제약(타임아웃·레이트리밋) 실패가 없다. 없는 갈래는 세지 않는다.
    fail = None
    if case["gold_tool"] is None:
        if calls:
            fail = "tool"
    elif not out["tsa"]:
        fail = "tool"
    elif out["invalid"]:
        fail = "workflow"
    elif out["aem"] is False:
        fail = "param"
    elif (hit / tot if tot else 1.0) < 0.5:
        fail = "ground"
    out["fail_kind"] = fail

    # PCA — 도구를 옳게 고른 호출 중 인자까지 유효했던 비율. AEM 과 달리 분모가
    # "정답 도구를 고른 호출"이라, 도구 선택 정확도와 인자 구성 정확도를 갈라 준다.
    out["pca"] = None if not out["tsa"] or out["aem"] is None else bool(
        out["aem"] and not out["invalid"])

    abst = bool(_ABSTAIN.search(ans))
    out["abstain_ok"] = abst if case.get("abstain") else None
    forbidden = any(re.search(p, ans) for p in case.get("forbid", []))
    out["forbidden"] = forbidden

    gfr = hit / tot if tot else 1.0
    if case["gold_tool"] is None:
        ok = abst and not calls
    else:
        ok = gfr >= 0.5 and not forbidden
        if case.get("abstain"):
            ok = ok and abst
    out["tsr"] = bool(ok and not run.get("error"))
    out["gfr"] = gfr
    return out


def agg(rows: list, key: str):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None, 0, 0
    k = sum(1 for v in vals if v)
    return k / len(vals), k, len(vals)


def ratio(rows: list, key: str):
    num = den = 0
    for r in rows:
        p = r.get(key)
        if p:
            num += p[0]
            den += p[1]
    return (num / den if den else None), num, den


def pct(x):
    return "—" if x is None else f"{100*x:.1f}%"


def med(xs):
    return statistics.median(xs) if xs else float("nan")


def p95(xs):
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(math.ceil(0.95 * len(s)) - 1))]


# ────────────────────────────────────────────────────────────────────────
# 리포트
# ────────────────────────────────────────────────────────────────────────

def main() -> None:
    gold = json.loads((RESULTS / "gold.json").read_text(encoding="utf-8"))
    gold_at = gold["generated_at"]
    gold = gold["gold"]
    timing = json.loads((RESULTS / "tool_timing.json").read_text(encoding="utf-8"))
    try:
        modes = json.loads((RESULTS / "modes.json").read_text(encoding="utf-8"))
    except Exception:
        modes = {}
    known = load_known_places()
    verdicts = load_verdicts()

    runs = defaultdict(list)     # (label, arm) → [run]
    for f in sorted(RAW.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            # 도구 설명 판본이 다르면 다른 arm 으로 본다 — 같은 표에서 섞으면 안 된다.
            arm = r["arm"]
            v = r.get("variant", "-")
            if arm == "mcp" and v not in ("v0", "-"):
                arm = f"mcp-{v}"
            r["arm"] = arm
            runs[(r["label"], arm)].append(r)

    labels = sorted({k[0] for k in runs})
    all_arms = sorted({k[1] for k in runs})
    mcp_arms = [a for a in all_arms if a.startswith("mcp")]

    def marms(lb):
        return [a for a in mcp_arms if (lb, a) in runs]
    scored = {k: [score_run(r, gold, known) for r in v] for k, v in runs.items()}

    L = []
    w = L.append
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    w(f"# 제주 별 관측 MCP — 로컬 sLLM 연동 정량 평가 결과\n")
    w(f"측정 {now} (KST) · 정답 생성 {gold_at} · 규약 [TEST_GUIDELINE.md](TEST_GUIDELINE.md)\n")

    # 1. 무엇을 쟀나
    w("## 1. 요약\n")
    hcol = " 사람채점 B |" if verdicts else ""
    hsep = "---|" if verdicts else ""
    w("| 모델 | 도구모드 | TSA | AEM | GFR(base→mcp) | 환각률 FNR(base→mcp) | TSR(base→mcp) |" + hcol)
    w("|---|---|---|---|---|---|---|" + hsep)
    for lb, marm in [(l, a) for l in labels for a in marms(l)]:
        m = scored.get((lb, marm), [])
        b = scored.get((lb, "baseline"), [])
        tsa = agg(m, "tsa")[0]
        aem = agg([x for x in m if x["aem"] is not None], "aem")[0]
        gb, gm = ratio(b, "gfr_parts")[0], ratio(m, "gfr_parts")[0]
        fb, fm = ratio(b, "fnr_parts")[0], ratio(m, "fnr_parts")[0]
        tb, tm = agg(b, "tsr")[0], agg(m, "tsr")[0]
        hv = [v for (mo, ar, _c), (v, _n) in verdicts.items()
              if mo == lb and ar == marm]
        hcell = (f" {pct(hv.count(chr(79))/len(hv)) if hv else chr(8212)}"
                 f" <sub>n={len(hv)}</sub> |") if verdicts else ""
        w(f"| {lb} · {marm} | {modes.get(lb,'—')} | {pct(tsa)} | {pct(aem)} | "
          f"{pct(gb)} → {pct(gm)} | {pct(fb)} → {pct(fm)} | {pct(tb)} → {pct(tm)} |" + hcell)
    w("")

    # 2. 도구 사용 정확도
    w("## 2. 도구 사용 정확도 (arm B)\n")
    w("| 모델 | TSA 도구선택 | AEM 인자정확 | 슬롯 F1 | ICR 오류호출 | OTR 과잉호출 | 평균 턴 |")
    w("|---|---|---|---|---|---|---|")
    for lb, marm in [(l, a) for l in labels for a in marms(l)]:
        m = scored.get((lb, marm), [])
        raw = runs.get((lb, marm), [])
        if not m:
            continue
        tsa, k, n = agg(m, "tsa")
        lo, hi = wilson(k, n)
        aem_rows = [x for x in m if x["aem"] is not None]
        aem, ak, an = agg(aem_rows, "aem")
        inter = sum(x["f1_parts"][0] for x in m if x["f1_parts"])
        pn = sum(x["f1_parts"][1] for x in m if x["f1_parts"])
        gn = sum(x["f1_parts"][2] for x in m if x["f1_parts"])
        f1 = 2 * inter / (pn + gn) if (pn + gn) else 0.0
        icr = agg(m, "invalid")[0]
        nt = [x for x in m if x["category"] == "no-tool"]
        otr = agg(nt, "called")[0]
        turns = statistics.mean([r["turns"] for r in raw]) if raw else 0
        w(f"| {lb} · {marm} | {pct(tsa)} <sub>[{100*lo:.0f}–{100*hi:.0f}]</sub> | {pct(aem)} | "
          f"{f1:.3f} | {pct(icr)} | {pct(otr)} | {turns:.2f} |")
    w("\nTSA 옆 대괄호는 Wilson 95% 신뢰구간(%p).\n")

    # 3. 답변 품질 A vs B
    w("## 3. 답변 품질 — 도구 없음(A) vs MCP(B)\n")
    w("| 모델 | GFR A | GFR B | ΔGFR | FNR A | FNR B | ΔFNR | 장소명 유효 B | "
      "지도주소 포함 | 첫 줄에 | 주소 위조 | TSR A | TSR B | ΔTSR |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for lb, marm in [(l, a) for l in labels for a in marms(l)]:
        b, m = scored.get((lb, "baseline"), []), scored.get((lb, marm), [])
        if not b or not m:
            continue
        gb, gm = ratio(b, "gfr_parts")[0], ratio(m, "gfr_parts")[0]
        fb, fm = ratio(b, "fnr_parts")[0], ratio(m, "fnr_parts")[0]
        pb, pm = ratio(b, "pnr_parts")[0], ratio(m, "pnr_parts")[0]
        tb, tm = agg(b, "tsr")[0], agg(m, "tsr")[0]
        d = lambda x, y: "—" if (x is None or y is None) else f"{100*(y-x):+.1f}%p"
        mu = ratio(m, "map_parts")[0]
        mf = ratio(m, "mapfirst_parts")[0]
        w(f"| {lb} · {marm} | {pct(gb)} | {pct(gm)} | **{d(gb,gm)}** | {pct(fb)} | {pct(fm)} | "
          f"**{d(fb,fm)}** | {pct(pm)} | {pct(mu)} | {pct(mf)} | "
          f"{pct(ratio(m, 'mapfake_parts')[0])} | "
          f"{pct(tb)} | {pct(tm)} | **{d(tb,tm)}** |")
    w("\nGFR↑ 좋음 · FNR↓ 좋음 · TSR↑ 좋음.\n")

    # 3-1. 지도 링크
    w("### 3-1. 지도 링크 전달률 (arm B)\n")
    w("도구가 `map_url` 을 돌려준 케이스에서, 모델이 그 주소를 답변에 옮겼는가. "
      "지도는 좌표를 말로 설명하지 않으려고 만든 산출물이라, 옮겨지지 않으면 "
      "만든 값이 사용자에게 닿지 않는다. 대조는 주소의 `/maps/<해시>` 조각으로 한다.\n")
    w("| 모델 | 전달률 | 옮김/받음 |")
    w("|---|---|---|")
    for lb, marm in [(l, a) for l in labels for a in marms(l)]:
        r, num, den = ratio(scored.get((lb, marm), []), "map_parts")
        if den:
            w(f"| {lb} · {marm} | {pct(r)} | {num}/{den} |")
    w("")

    # 옮겼는지와 **열리는지는 다른 질문이다.** 전달률이 100% 인데 주소가 전부 죽어
    # 있던 적이 두 번 있다(꺼진 ngrok 터널 · 파일 이름 검사식 불일치). 그래서 arm T 가
    # 정답을 만들 때 실제로 GET 해 본 상태 코드를 여기 함께 싣는다.
    codes = [(cid, g.get("map_http")) for cid, g in gold.items()
             if g.get("map_http") is not None]
    if codes:
        dead = [(cid, c) for cid, c in codes if c != 200]
        if dead:
            w(f"**받은 지도 주소 {len(codes)}건 중 {len(dead)}건이 열리지 않는다.** "
              "옮겨져도 사용자에게 닿지 않으므로 전달률과 함께 읽어야 한다.
")
            w("| 케이스 | HTTP |")
            w("|---|---|")
            for cid, c in dead:
                w(f"| {cid} | {c if c else '연결 실패'} |")
        else:
            w(f"받은 지도 주소 {len(codes)}건은 **전부 열린다**(HTTP 200). "
              "arm T 가 정답을 만들 때 실제로 조회해 확인한 값이다.")
        w("")

    # 4. 지연 분해
    w("## 4. 지연 분해 — LLM 시간과 도구 로직 시간을 갈라서\n")
    w("| 모델 | arm | t_e2e 중앙값 | p95 | t_llm | t_tool_rtt | t_harness | 출력 tok/s | 프롬프트 토큰 |")
    w("|---|---|---|---|---|---|---|---|---|")
    for lb in labels:
        for arm in ["baseline"] + marms(lb):
            raw = runs.get((lb, arm), [])
            if not raw:
                continue
            e2e = [r["t_e2e"] for r in raw]
            w(f"| {lb} | {arm} | {med(e2e):.2f}s | {p95(e2e):.2f}s | "
              f"{med([r['t_llm'] for r in raw]):.2f}s | "
              f"{med([r['t_tool_rtt'] for r in raw]):.2f}s | "
              f"{med([r['t_harness'] for r in raw]):.3f}s | "
              f"{sum(r['eval_tokens'] for r in raw)/max(1e-9,sum(r['eval_seconds'] for r in raw)):.1f} | "
              f"{med([r['prompt_tokens'] for r in raw]):.0f} |")
    w("")

    # 5. 도구 로직 시간 (모델 무관 상수)
    w("## 5. 도구 로직 시간 — 모델과 무관한 상수\n")
    w("LLM 없이 MCP 도구만 직접 부른 값(arm T). 아래 시간은 어떤 모델을 써도 줄지 않는다.\n")
    w("| 케이스 | 도구 | cold | warm 중앙값 | 응답 크기 |")
    w("|---|---|---|---|---|")
    for cid, t in timing.items():
        w(f"| {cid} | {t['tool']} | {t['cold_s']:.3f}s | {t['warm_median_s']:.3f}s | {t['response_bytes']:,}B |")
    by_tool = defaultdict(list)
    for t in timing.values():
        by_tool[t["tool"]].append(t["warm_median_s"])
    w("")
    w("| 도구 | warm 중앙값 | 최소 | 최대 |")
    w("|---|---|---|---|")
    for tool, xs in by_tool.items():
        w(f"| {tool} | {med(xs):.3f}s | {min(xs):.3f}s | {max(xs):.3f}s |")
    w("")

    # 6. 범주별
    w("## 6. 범주별 정확도 (arm B, TSA)\n")
    cats = ["recommend", "evaluate", "details", "no-tool"]
    w("| 모델 | " + " | ".join(cats) + " |")
    w("|---" * (len(cats) + 1) + "|")
    for lb, marm in [(l, a) for l in labels for a in marms(l)]:
        m = scored.get((lb, marm), [])
        cells = []
        for c in cats:
            rows = [x for x in m if x["category"] == c]
            cells.append(pct(agg(rows, "tsa")[0]))
        w(f"| {lb} · {marm} | " + " | ".join(cells) + " |")
    w("")

    # 7. 실패 사례
    w("## 7. 실패 사례 (모델별 최대 3건)\n")
    for lb, marm in [(l, a) for l in labels for a in marms(l)]:
        raw = runs.get((lb, marm), [])
        sc = scored.get((lb, marm), [])
        bad = [(r, s) for r, s in zip(raw, sc) if not s["tsr"]]
        if not bad:
            continue
        w(f"### {lb} · {marm}\n")
        seen = set()
        shown = 0
        for r, s in bad:
            if s["case_id"] in seen or shown >= 3:
                continue
            seen.add(s["case_id"])
            shown += 1
            case = BY_ID[s["case_id"]]
            w(f"- **{s['case_id']}** {case['question']}")
            w(f"  - 기대 도구 `{case['gold_tool']}` / 실제 "
              f"`{[c['name'] for c in r['tool_calls']] or '없음'}` "
              f"인자 `{json.dumps(r['tool_calls'][0]['arguments'], ensure_ascii=False) if r['tool_calls'] else '—'}`")
            if s["missed"]:
                w(f"  - 답변에 없던 근거: {', '.join(s['missed'][:4])}")
            ans = (r["answer"] or "").replace("\n", " ")[:220]
            w(f"  - 답변: {ans}")
        w("")

    # 8. 사람 채점 (verdicts.csv 가 있을 때만)
    if verdicts:
        w("## 8. 사람 채점 — 자동 채점과 대조\n")
        w("`results/verdicts.csv` 에 사람이 직접 찍은 O/X 다. 규칙이 못 가르는 "
          "애매한 건을 사람이 판정한 결과이고, 아래 불일치 목록은 **자동 채점(TSR)과 "
          "엇갈린 것**만 추린 것이다 — 엇갈리는 자리가 곧 채점 규칙을 고칠 자리다.\n")
        w("| 모델 | arm | 사람 O율 | 판정 수 | 자동 TSR | 불일치 |")
        w("|---|---|---|---|---|---|")
        mismatch = []
        for lb in labels:
            for arm in ["baseline"] + marms(lb):
                hv = {cid: v for (mo, ar, cid), (v, _n) in verdicts.items()
                      if mo == lb and ar == arm}
                if not hv:
                    continue
                sc = {x["case_id"]: x for x in scored.get((lb, arm), [])}
                dis = [cid for cid, v in hv.items()
                       if cid in sc and (v == "O") != bool(sc[cid]["tsr"])]
                auto = agg([sc[c] for c in hv if c in sc], "tsr")[0]
                ok = list(hv.values()).count("O") / len(hv)
                w(f"| {lb} | {arm} | {pct(ok)} | {len(hv)} | {pct(auto)} | {len(dis)} |")
                for cid in dis:
                    mismatch.append((lb, arm, cid, hv[cid],
                                     "O" if sc[cid]["tsr"] else "X",
                                     verdicts[(lb, arm, cid)][1]))
        if mismatch:
            w("\n**불일치 목록** (사람 / 자동)\n")
            for lb, arm, cid, hvv, av, note in mismatch:
                w(f"- `{lb}` {arm} **{cid}** — 사람 {hvv} / 자동 {av}"
                  + (f" · {note}" if note else ""))
        w("")

    # 9. 한계
    w("## 9. 한계\n")
    w("- 규칙 기반 채점이라 문장 품질·설득력은 재지 않는다. 사실 일치만 본다.")
    w("- 규칙이 사람과 갈리는 자리가 실제로 있다. (a) D-04 는 답이 "
      "\"화장실은 500m 안에 없으며\" 라고 말로 썼는데 채점은 숫자 0 을 찾아 실패로 "
      "셌다. (b) E-05 는 시각을 안 물었는데 모델이 23:00 으로 불러 정답(22:00)과 "
      "구름값이 달라졌다 — 틀린 호출이라기보다 다른 호출이다. 이런 건 "
      "`results/verdicts.csv` 의 사람 채점이 갈라 준다.")
    w("- 다단계(도구 2개 연쇄) 사용은 범위 밖이다. 1-hop 정확도만 본다.")
    w("- 구름·시상은 측정 시점 예보라 며칠 뒤 다시 돌리면 정답 자체가 달라진다. "
      f"이 리포트의 정답은 {gold_at} 에 생성했다.")
    w("- 장소명 유효율은 정규식으로 뽑은 후보에 대한 값이라, 정규식이 놓친 이름은 세지 않는다.")
    w("- 모델 순위는 이 도구 셋·이 한국어 스키마 한정이다.")
    w("")

    out = RESULTS / f"RESULT_{datetime.now():%Y-%m-%d}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
