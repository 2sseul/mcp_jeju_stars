"""사람이 눈으로 훑는 검수 페이지를 만든다 (HTML).

review.py 가 만드는 마크다운 시트는 판정을 적어 넣기 위한 것이고, 이 파일은
**할루시네이션을 눈으로 찾기 위한 것**이다. 규칙 채점이 세는 것과 똑같은 기준으로
답변 본문에 색을 칠한다 — 근거 있는 수치는 청록, 근거 없는 수치는 주홍, 도구가 준
지도 주소는 남색, 그 밖의 주소는 주홍. 그래서 문장을 읽지 않고 색만 훑어도
"이 답에 지어낸 값이 있나"가 먼저 눈에 들어온다.

    python review_html.py     → results/REVIEW_<모델>.html
"""

from __future__ import annotations

import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cases import BY_ID                                              # noqa: E402
from score import (_ABSTAIN, _MAP_STEM, _PLACE, _UNIT_NUM, _URL,     # noqa: E402
                   all_numbers, jpath, load_known_places, nums_in, score_run)

HERE = Path(__file__).parent
RESULTS = HERE / "results"
RAW = RESULTS / "raw"

CAT_KR = {"recommend": "추천", "evaluate": "판정", "details": "상세", "no-tool": "도구 금지"}

# 한국어 답변에 섞여 나오는 영어 — 규칙 채점이 못 잡는 품질 문제라 여기서만 센다.
# 도구 응답·고유명사에 원래 로마자로 들어 있는 말은 세지 않는다.
_LATIN = re.compile(r"[A-Za-z][A-Za-z'-]{1,}")
_LATIN_OK = {
    # 도구가 로마자로 내보내는 값·단위·출처
    "sqm", "bortle", "falchi", "viirs", "nw", "cm", "sr", "km", "m", "mcd",
    "jpl", "de421", "skyfield", "open-meteo", "meteo", "com", "org", "html",
    "http", "https", "maps", "localhost", "api", "mcp", "gps", "kst", "utc",
    # 도구 이름 자체
    "recommend_spots", "evaluate_place", "spot_details", "spots",
}


# 사용자가 바로 알아듣기 어려운 말. 대부분 도구 응답의 `reasons` 산문에서 그대로
# 옮겨 온 것이라, 고칠 자리는 모델이 아니라 modules/tools.py 다.
_JARGON = [
    (re.compile(r"Bortle"), "밤하늘 어둡기 등급 — 숫자가 작을수록 어둡다"),
    (re.compile(r"\bSQM\b"), "하늘 밝기 측정값 — 클수록 어둡다"),
    (re.compile(r"Falchi\s*[ivx]*"), "광공해 분류 등급"),
    (re.compile(r"\bVIIRS\b"), "위성이 잰 야간 불빛"),
    (re.compile(r"광공해"), "인공 불빛 때문에 하늘이 밝아지는 것"),
    (re.compile(r"(?:천문|항해|시민)?박명"), "해가 진 뒤 아직 하늘이 덜 어두운 때"),
    (re.compile(r"수평시정"), "옆으로 내다보이는 거리"),
    (re.compile(r"총운량"), "하늘을 구름이 덮은 정도"),
    (re.compile(r"\b시상\b"), "대기가 흔들려 별이 번지는 정도"),
    (re.compile(r"성운"), "별구름 — 망원경이 있어야 보이는 대상"),
]


def jargon_spans(answer: str):
    """(시작, 끝, 풀어 쓴 말) 목록 — 사용자가 알아듣기 어려운 말."""
    url_ranges = [(u.start(), u.end()) for u in _URL.finditer(answer or "")]
    out = []
    for rx, gloss in _JARGON:
        for m in rx.finditer(answer or ""):
            if any(a <= m.start() < b for a, b in url_ranges):
                continue
            out.append((m.start(), m.end(), gloss))
    return out


def stray_latin(answer: str, resp: dict):
    """(시작, 끝) 목록 — 도구 응답에도 없는 로마자 낱말."""
    in_gold = {w.lower() for w in _LATIN.findall(json.dumps(resp, ensure_ascii=False))} if resp else set()
    url_ranges = [(u.start(), u.end()) for u in _URL.finditer(answer or "")]
    out = []
    for m in _LATIN.finditer(answer or ""):
        if any(a <= m.start() < b for a, b in url_ranges):
            continue
        w = m.group(0).lower()
        if w in _LATIN_OK or w in in_gold:
            continue
        out.append((m.start(), m.end()))
    return out


# ────────────────────────────────────────────────────────────────────────
# 본문 색칠 — 채점과 같은 기준으로 칠한다
# ────────────────────────────────────────────────────────────────────────

def spans(answer: str, resp: dict, question: str, known: set, category: str):
    """(시작, 끝, 클래스, 툴팁) 목록. 겹치지 않게 정리해서 돌려준다."""
    allowed = (nums_in(resp) | set(all_numbers(question))) if resp else set()
    gmap = (resp or {}).get("map_url") or ""
    m = _MAP_STEM.search(gmap)
    stem = m.group(1).lower() if m else None

    out = []
    url_ranges = []
    for u in _URL.finditer(answer):
        url_ranges.append((u.start(), u.end()))
        if stem and stem in u.group(0).lower():
            out.append((u.start(), u.end(), "ok-url", "도구가 준 지도 주소 그대로"))
        else:
            out.append((u.start(), u.end(), "bad-url", "도구가 주지 않은 주소 — 위조"))

    for n in _UNIT_NUM.finditer(answer):
        if any(a <= n.start() < b for a, b in url_ranges):
            continue
        v = float(n.group(1))
        ok = any(abs(v - a) <= max(0.5, 0.02 * abs(a)) for a in allowed)
        out.append((n.start(), n.end(), "ok-num" if ok else "bad-num",
                    "도구 응답·질문에 있는 값" if ok else "도구 응답에도 질문에도 없는 값 — 환각"))

    if category == "recommend":
        for p in _PLACE.finditer(answer):
            if any(a <= p.start() < b for a, b in url_ranges):
                continue
            ok = p.group(0) in known
            out.append((p.start(), p.end(), "ok-place" if ok else "bad-place",
                        "검증된 62곳에 있는 이름" if ok else "검증 목록에 없는 이름"))

    for a, b in stray_latin(answer, resp):
        out.append((a, b, "latin", "한국어 답변에 섞인 영어 — 도구 응답에도 없는 말"))

    for a, b, gloss in jargon_spans(answer):
        out.append((a, b, "jargon", f"어려운 말 — 이런 뜻: {gloss}"))

    out.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    keep, last = [], -1
    for s in out:
        if s[0] >= last:
            keep.append(s)
            last = s[1]
    return keep


def paint(answer: str, resp: dict, question: str, known: set, category: str) -> str:
    if not answer:
        return '<span class="empty">(빈 응답)</span>'
    pieces, cur = [], 0
    for a, b, cls, tip in spans(answer, resp, question, known, category):
        pieces.append(html.escape(answer[cur:a]))
        pieces.append(f'<mark class="{cls}" title="{html.escape(tip)}">'
                      f'{html.escape(answer[a:b])}</mark>')
        cur = b
    pieces.append(html.escape(answer[cur:]))
    return "".join(pieces).replace("\n", "<br>")


# ────────────────────────────────────────────────────────────────────────
# 자료 모으기
# ────────────────────────────────────────────────────────────────────────

def load_runs():
    """(모델, 케이스, arm) → 반복 목록."""
    runs = defaultdict(lambda: defaultdict(list))
    labels = set()
    for f in sorted(RAW.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            arm, v = r["arm"], r.get("variant", "-")
            if arm == "mcp" and v not in ("v0", "-"):
                arm = f"mcp-{v}"
            r["arm"] = arm
            runs[(r["label"], r["case_id"])][arm].append(r)
            labels.add(r["label"])
    return runs, sorted(labels)


def gold_spots_table(resp: dict, case: dict) -> str:
    """추천 케이스의 정답을 **곳마다 한 줄로** 보여 준다.

    채점 규칙은 `spots[0].cloud_cover` 처럼 첫 곳만 검증 대상으로 잡는데, 그 값 하나만
    화면에 띄우면 세 곳 전부에 해당하는 값처럼 읽힌다. 실제로 그렇게 읽혀서 "구름이
    19%인데 답은 왜 50%냐"는 오해가 났다 — 50%는 세 번째 곳의 제 값이었다.
    곳마다 다른 값은 곳마다 보여 준다. 채점 대상인 칸에는 표시를 달아 둔다.
    """
    spots = resp.get("spots") or []
    if not spots:
        return ""
    checked = {sp["path"] for sp in case.get("facts", [])}

    def mark(path: str) -> str:
        if path not in checked:
            return ""
        return ' <span class="chk" title="이 값이 채점 대상">채점</span>'

    def cell(value, suffix: str = "") -> str:
        return "" if value is None else f"{value}{suffix}"

    rows = ['<table class="spots"><thead><tr><th>도구가 고른 곳</th><th>구름</th>'
            '<th>어둡기</th><th>차로</th><th>도보</th></tr></thead><tbody>']
    for i, sp in enumerate(spots):
        walk = sp.get("walk_minutes")
        if walk is None and isinstance(sp.get("walk"), dict):
            walk = sp["walk"].get("minutes")
        drive = (sp.get("drive") or {}).get("minutes")
        first = mark if i == 0 else (lambda _p: "")
        name = html.escape(str(sp.get("name", "")))
        rows.append(
            "<tr>"
            f'<td>{name}{mark("spots[*].name")}</td>'
            f'<td>{cell(sp.get("cloud_cover"), "%")}{first("spots[0].cloud_cover")}</td>'
            f'<td>{cell(sp.get("bortle"))}{first("spots[0].bortle")}</td>'
            f'<td>{cell(drive, "분")}{mark("spots[*].drive.minutes")}</td>'
            f'<td>{cell(walk, "분")}</td>'
            "</tr>")
    rows.append("</tbody></table>")
    return "".join(rows)


def gold_chips(case: dict, resp: dict) -> str:
    if not resp:
        return '<span class="muted">도구를 부르지 않는 것이 정답 — 대조할 값 없음</span>'
    if resp.get("spots") and case["category"] == "recommend":
        return gold_spots_table(resp, case)
    bits = []
    for spec in case.get("facts", []):
        for v in jpath(resp, spec["path"]):
            key = spec["path"].split(".")[-1]
            bits.append(f'<code class="chip">{html.escape(key)} <b>{html.escape(str(v))}</b></code>')
    if not bits:
        return '<span class="muted">검증 대상 값 없음</span>'
    return " ".join(bits[:24]) + (f' <span class="muted">외 {len(bits)-24}개</span>' if len(bits) > 24 else "")


def call_chip(run: dict) -> str:
    calls = run.get("tool_calls") or []
    if not calls:
        return '<code class="chip none">도구 안 부름</code>'
    c = calls[0]
    args = html.escape(json.dumps(c["arguments"], ensure_ascii=False))
    extra = ""
    if len(calls) > 1:
        extra = f' <span class="muted">+{len(calls)-1}회 더</span>'
    return f'<code class="chip"><b>{html.escape(c["name"])}</b> {args}</code>{extra}'


CSS = """
:root{
  --paper:#F4F6FA; --surface:#FFFFFF; --surface-2:#EEF1F7;
  --ink:#141A26; --muted:#5B6478; --line:#DDE3EC;
  --accent:#3A4FC4; --accent-soft:#E4E8FA;
  --good:#0B6E5F; --good-soft:#DCF0EB;
  --bad:#C03A22;  --bad-soft:#FBE2DC;
  --warn:#8A6300; --warn-soft:#F7ECD4;
  --shadow:0 1px 2px rgba(20,26,38,.05),0 8px 24px -16px rgba(20,26,38,.28);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#0D1119; --surface:#151B27; --surface-2:#1B2231;
    --ink:#E6EAF2; --muted:#8B97AC; --line:#242D3E;
    --accent:#92A2FF; --accent-soft:#1E2643;
    --good:#4FD1B4; --good-soft:#123029;
    --bad:#FF8A6E;  --bad-soft:#3A1D16;
    --warn:#E2B25A; --warn-soft:#332711;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  --paper:#0D1119; --surface:#151B27; --surface-2:#1B2231;
  --ink:#E6EAF2; --muted:#8B97AC; --line:#242D3E;
  --accent:#92A2FF; --accent-soft:#1E2643;
  --good:#4FD1B4; --good-soft:#123029;
  --bad:#FF8A6E;  --bad-soft:#3A1D16;
  --warn:#E2B25A; --warn-soft:#332711;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.7);
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;
  font-size:15px; line-height:1.7; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1080px; margin:0 auto; padding:0 24px 140px}

/* ── 머리 ── */
header.top{
  position:sticky; top:0; z-index:20; background:var(--paper);
  border-bottom:1px solid var(--line);
}
.top-inner{max-width:1080px; margin:0 auto; padding:20px 24px 0}
.eyebrow{
  font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:11px;
  letter-spacing:.16em; text-transform:uppercase; color:var(--muted); margin:0 0 6px;
}
h1{
  font-family:"Gowun Batang","Apple SD Gothic Neo",serif; font-weight:700;
  font-size:clamp(26px,3.4vw,38px); line-height:1.2; margin:0 0 4px; text-wrap:balance;
}
.sub{color:var(--muted); font-size:13.5px; margin:0 0 18px}
.sub code{font-family:"IBM Plex Mono",monospace; font-size:12.5px; color:var(--ink)}

.rail{display:flex; flex-wrap:wrap; gap:10px; margin:0 0 18px}
.stat{
  flex:1 1 132px; background:var(--surface); border:1px solid var(--line);
  border-radius:10px; padding:10px 12px; box-shadow:var(--shadow);
}
.stat .k{font-size:11px; letter-spacing:.08em; color:var(--muted); text-transform:uppercase;
  font-family:"IBM Plex Mono",monospace}
.stat .v{font-size:24px; font-weight:600; font-variant-numeric:tabular-nums; line-height:1.25}
.stat .d{font-size:11.5px; color:var(--muted); font-variant-numeric:tabular-nums}
.stat.is-good .v{color:var(--good)} .stat.is-bad .v{color:var(--bad)}

.filters{display:flex; flex-wrap:wrap; gap:8px; padding-bottom:16px}
.filters button{
  font:inherit; font-size:13px; padding:5px 12px; border-radius:999px; cursor:pointer;
  border:1px solid var(--line); background:var(--surface); color:var(--muted);
}
.filters button:hover{border-color:var(--accent); color:var(--ink)}
.filters button[aria-pressed="true"]{background:var(--accent); border-color:var(--accent); color:#fff}
.filters button:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
:root[data-theme="dark"] .filters button[aria-pressed="true"],
.filters button[aria-pressed="true"]{color:#fff}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]) .filters button[aria-pressed="true"]{color:#0D1119}
}

/* ── 범례 ── */
.legend{
  display:flex; flex-wrap:wrap; gap:8px 18px; margin:20px 0 26px; padding:14px 16px;
  background:var(--surface); border:1px solid var(--line); border-radius:10px; font-size:13px;
}
.legend b{font-weight:500; color:var(--muted)}

/* ── 케이스 카드 ── */
.case{
  background:var(--surface); border:1px solid var(--line); border-radius:12px;
  margin:0 0 18px; overflow:hidden; box-shadow:var(--shadow);
  border-left:4px solid var(--good);
}
.case.fail{border-left-color:var(--bad)}
.case.warn{border-left-color:var(--warn)}
.case-head{display:flex; flex-wrap:wrap; align-items:baseline; gap:10px; padding:16px 20px 0}
.cid{font-family:"IBM Plex Mono",monospace; font-weight:600; font-size:13px; color:var(--accent)}
.tag{
  font-size:11px; letter-spacing:.06em; padding:2px 8px; border-radius:999px;
  background:var(--surface-2); color:var(--muted);
}
.tag.pass{background:var(--good-soft); color:var(--good)}
.tag.fail{background:var(--bad-soft); color:var(--bad)}
.tag.warn{background:var(--warn-soft); color:var(--warn)}
.q{
  font-family:"Gowun Batang","Apple SD Gothic Neo",serif; font-size:20px; line-height:1.45;
  margin:8px 20px 14px; text-wrap:balance;
}
.rows{display:grid; grid-template-columns:88px 1fr; gap:2px 14px; padding:0 20px 4px; font-size:13.5px}
.rows dt{color:var(--muted); font-size:12px; padding-top:3px}
.rows dd{margin:0; min-width:0; overflow-x:auto}
code.chip{
  font-family:"IBM Plex Mono",monospace; font-size:12.5px; background:var(--surface-2);
  border:1px solid var(--line); border-radius:6px; padding:1px 7px; white-space:nowrap;
}
code.chip.none{background:var(--bad-soft); border-color:transparent; color:var(--bad)}
table.spots{
  border-collapse:collapse; font-size:13px; margin:2px 0 4px;
  font-variant-numeric:tabular-nums; min-width:100%;
}
table.spots th{
  text-align:left; font-weight:500; font-size:11px; letter-spacing:.05em; color:var(--muted);
  border-bottom:1px solid var(--line); padding:2px 12px 4px 0; white-space:nowrap;
}
table.spots td{padding:4px 12px 4px 0; border-bottom:1px solid var(--line); white-space:nowrap}
table.spots tr:last-child td{border-bottom:0}
table.spots td:first-child{font-weight:500}
.chk{
  font-size:10px; letter-spacing:.04em; padding:1px 5px; border-radius:4px;
  background:var(--accent-soft); color:var(--accent); vertical-align:1px;
}
code.chip b{color:var(--accent); font-weight:600}
.muted{color:var(--muted); font-size:12.5px}

.answer{
  margin:14px 20px 18px; padding:14px 16px; background:var(--surface-2);
  border:1px solid var(--line); border-radius:10px; font-size:14px; line-height:1.85;
  overflow-x:auto;
}
.answer .empty{color:var(--muted); font-style:italic}
details.base{margin:0 20px 18px}
details.base summary{
  cursor:pointer; font-size:12.5px; color:var(--muted); list-style:none;
  padding:6px 10px; border:1px dashed var(--line); border-radius:8px; display:inline-block;
}
details.base summary::-webkit-details-marker{display:none}
details.base summary:hover{color:var(--ink); border-color:var(--accent)}
details.base[open] summary{margin-bottom:10px}
details.base .answer{margin:0}

mark{background:none; color:inherit; padding:0 1px; border-radius:3px}
mark.ok-num{color:var(--good); background:var(--good-soft); font-weight:500}
mark.bad-num{color:var(--bad); background:var(--bad-soft); font-weight:600;
  box-shadow:inset 0 -2px 0 var(--bad)}
mark.ok-url{color:var(--accent); background:var(--accent-soft); word-break:break-all}
mark.bad-url{color:var(--bad); background:var(--bad-soft); word-break:break-all;
  box-shadow:inset 0 -2px 0 var(--bad)}
mark.ok-place{box-shadow:inset 0 -1px 0 var(--good)}
mark.bad-place{color:var(--warn); box-shadow:inset 0 -2px 0 var(--warn)}
mark.latin{color:var(--warn); background:var(--warn-soft); font-style:italic}
mark.jargon{
  color:var(--accent); cursor:help;
  box-shadow:inset 0 -2px 0 var(--accent-soft), inset 0 -3px 0 -1px var(--accent);
}
.tag.jargon{background:var(--accent-soft); color:var(--accent)}

.sw{display:inline-block; width:11px; height:11px; border-radius:3px; vertical-align:-1px; margin-right:5px}
.sw.g{background:var(--good-soft); box-shadow:inset 0 0 0 1px var(--good)}
.sw.b{background:var(--bad-soft); box-shadow:inset 0 0 0 1px var(--bad)}
.sw.a{background:var(--accent-soft); box-shadow:inset 0 0 0 1px var(--accent)}
.sw.w{background:var(--warn-soft); box-shadow:inset 0 0 0 1px var(--warn)}
.sw.j{background:var(--accent-soft); box-shadow:inset 0 0 0 1px var(--accent)}

/* ── 사람 판정 ── */
.judge{
  display:flex; flex-wrap:wrap; align-items:center; gap:8px;
  margin:0 20px 18px; padding-top:14px; border-top:1px dashed var(--line);
}
.judge .lbl{font-size:12px; color:var(--muted); margin-right:4px}
.jbtn{
  font:inherit; font-size:13px; padding:5px 15px; border-radius:8px; cursor:pointer;
  border:1px solid var(--line); background:var(--surface); color:var(--muted);
}
.jbtn:hover{border-color:var(--accent); color:var(--ink)}
.jbtn:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.jbtn.o[aria-pressed="true"]{background:var(--good); border-color:var(--good); color:var(--surface)}
.jbtn.x[aria-pressed="true"]{background:var(--bad); border-color:var(--bad); color:var(--surface)}
.jclear{font:inherit; font-size:12px; background:none; border:0; color:var(--muted);
  cursor:pointer; text-decoration:underline; padding:4px}
.jclear:hover{color:var(--ink)}
.fix{display:none; width:100%; margin-top:6px}
.judge.is-x .fix{display:block}
.fix .why{font-size:12px; color:var(--muted); margin:0 0 6px}
.fix .chips{display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px}
.fix .chips button{
  font:inherit; font-size:12px; padding:3px 11px; border-radius:999px; cursor:pointer;
  border:1px dashed var(--line); background:transparent; color:var(--muted);
}
.fix .chips button:hover{border-color:var(--warn); color:var(--ink)}
.fix .chips button[aria-pressed="true"]{
  background:var(--warn-soft); border-style:solid; border-color:var(--warn); color:var(--warn);
}
.fix textarea{
  width:100%; min-height:66px; resize:vertical; font:inherit; font-size:13.5px;
  padding:10px 12px; border-radius:8px; border:1px solid var(--line);
  background:var(--surface-2); color:var(--ink);
}
.fix textarea:focus{outline:2px solid var(--accent); outline-offset:1px; border-color:var(--accent)}
.case.judged-o{border-left-color:var(--good)}
.case.judged-x{border-left-color:var(--bad)}
.seal{font-size:12px; font-weight:600; margin-left:auto}
.seal.o{color:var(--good)} .seal.x{color:var(--bad)}

/* ── 내보내기 독 ── */
.dock{
  position:fixed; left:0; right:0; bottom:0; z-index:30; background:var(--surface);
  border-top:1px solid var(--line); box-shadow:0 -10px 30px -22px rgba(0,0,0,.6);
  max-height:78vh; overflow-y:auto;
}
.dock-bar{max-width:1080px; margin:0 auto; padding:10px 24px; display:flex;
  align-items:center; gap:12px; flex-wrap:wrap}
.dock .prog{font-size:13px; color:var(--muted); font-variant-numeric:tabular-nums}
.dock .prog b{color:var(--ink); font-weight:600}
.dock .prog .o{color:var(--good)} .dock .prog .x{color:var(--bad)}
.dock button.act{
  font:inherit; font-size:13px; padding:6px 15px; border-radius:8px; cursor:pointer;
  border:1px solid var(--accent); background:var(--accent); color:#fff;
}
.dock button.act:first-of-type{margin-left:auto}
.dock button.ghost{background:transparent; color:var(--muted); border-color:var(--line)}
.dock button.ghost:hover{color:var(--ink); border-color:var(--accent)}
.dock button:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.dock-panel{display:none; max-width:1080px; margin:0 auto; padding:0 24px 20px}
.dock.open .dock-panel{display:block}
.dock-panel h3{font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:var(--muted);
  margin:14px 0 6px; font-weight:500; font-family:"IBM Plex Mono",monospace}
.dock-panel p.how{font-size:12.5px; color:var(--muted); margin:0 0 8px}
.dock-panel textarea{
  width:100%; height:160px; font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:12px;
  line-height:1.6; padding:10px 12px; border-radius:8px; border:1px solid var(--line);
  background:var(--surface-2); color:var(--ink); resize:vertical;
}

.hidden{display:none}
footer{color:var(--muted); font-size:12.5px; border-top:1px solid var(--line); padding-top:18px; margin-top:32px}
@media (max-width:640px){
  .rows{grid-template-columns:1fr; gap:0}
  .rows dt{padding-top:8px}
}
"""


JS = """
(function(){
  var cases = Array.prototype.slice.call(document.querySelectorAll('.case'));
  var btns  = Array.prototype.slice.call(document.querySelectorAll('.filters button'));
  var KEY_F = 'jeju-review-filter', KEY_V = 'jeju-review-verdicts';

  var state = {cat:'all', only:false, todo:false};
  try{ var s = localStorage.getItem(KEY_F); if(s){ state = JSON.parse(s); } }catch(e){}
  var verdicts = {};
  try{ var v = localStorage.getItem(KEY_V); if(v){ verdicts = JSON.parse(v); } }catch(e){}

  function save(){
    try{ localStorage.setItem(KEY_V, JSON.stringify(verdicts)); }catch(e){}
  }

  /* ── 걸러 보기 ───────────────────────────────────────── */
  function apply(){
    cases.forEach(function(c){
      var cid = c.querySelector('.judge').dataset.cid;
      var okCat  = state.cat === 'all' || c.dataset.cat === state.cat;
      var okOnly = !state.only || c.dataset.flag !== 'pass';
      var okTodo = !state.todo || !verdicts[cid];
      c.classList.toggle('hidden', !(okCat && okOnly && okTodo));
    });
    btns.forEach(function(b){
      var on = b.dataset.only ? state.only
             : b.dataset.todo ? state.todo
             : (b.dataset.cat === state.cat);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    try{ localStorage.setItem(KEY_F, JSON.stringify(state)); }catch(e){}
  }
  btns.forEach(function(b){
    b.addEventListener('click', function(){
      if(b.dataset.only){ state.only = !state.only; }
      else if(b.dataset.todo){ state.todo = !state.todo; }
      else { state.cat = b.dataset.cat; }
      apply();
    });
  });

  /* ── 한 케이스의 판정 화면을 상태에 맞춘다 ───────────── */
  function paintJudge(box){
    var cid = box.dataset.cid, rec = verdicts[cid];
    var card = box.closest('.case');
    var seal = box.querySelector('.seal');
    var clear = box.querySelector('.jclear');
    box.querySelectorAll('.jbtn').forEach(function(b){
      b.setAttribute('aria-pressed', (rec && rec.v === b.dataset.v) ? 'true' : 'false');
    });
    box.classList.toggle('is-x', !!(rec && rec.v === 'X'));
    card.classList.toggle('judged-o', !!(rec && rec.v === 'O'));
    card.classList.toggle('judged-x', !!(rec && rec.v === 'X'));
    clear.classList.toggle('hidden', !rec);
    seal.className = 'seal' + (rec ? ' ' + rec.v.toLowerCase() : '');
    seal.textContent = rec ? (rec.v === 'O' ? '잘 나옴으로 기록됨' : '안 나옴으로 기록됨') : '';
    box.querySelectorAll('.chips button').forEach(function(t){
      var on = !!(rec && rec.tags && rec.tags.indexOf(t.dataset.tag) >= 0);
      t.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    var ta = box.querySelector('textarea');
    if(document.activeElement !== ta){ ta.value = (rec && rec.note) || ''; }
  }

  document.querySelectorAll('.judge').forEach(function(box){
    var cid = box.dataset.cid;
    box.querySelectorAll('.jbtn').forEach(function(b){
      b.addEventListener('click', function(){
        var rec = verdicts[cid] || {v:'', tags:[], note:''};
        rec.v = (rec.v === b.dataset.v) ? '' : b.dataset.v;
        if(!rec.v){ delete verdicts[cid]; } else { verdicts[cid] = rec; }
        save(); paintJudge(box); refresh();
        if(rec.v === 'X'){ box.querySelector('textarea').focus(); }
      });
    });
    box.querySelector('.jclear').addEventListener('click', function(){
      delete verdicts[cid]; save(); paintJudge(box); refresh();
    });
    box.querySelectorAll('.chips button').forEach(function(t){
      t.addEventListener('click', function(){
        var rec = verdicts[cid] || {v:'X', tags:[], note:''};
        rec.tags = rec.tags || [];
        var i = rec.tags.indexOf(t.dataset.tag);
        if(i >= 0){ rec.tags.splice(i, 1); } else { rec.tags.push(t.dataset.tag); }
        verdicts[cid] = rec; save(); paintJudge(box); refresh();
      });
    });
    box.querySelector('textarea').addEventListener('input', function(){
      var rec = verdicts[cid] || {v:'X', tags:[], note:''};
      rec.note = this.value; verdicts[cid] = rec; save(); refresh();
    });
    paintJudge(box);
  });

  /* ── 진행 상황과 내보내기 ────────────────────────────── */
  function csvCell(s){
    s = (s == null) ? '' : String(s);
    return /[",\\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function buildCSV(){
    var rows = ['model,arm,case_id,verdict,note'];
    META.cases.forEach(function(c){
      var rec = verdicts[c.id];
      if(!rec || !rec.v){ return; }
      var note = (rec.tags && rec.tags.length ? '[' + rec.tags.join('/') + '] ' : '')
               + (rec.note || '');
      rows.push([META.model, META.arm, c.id, rec.v, csvCell(note.trim())].join(','));
    });
    return rows.join('\\n');
  }
  function buildMD(){
    var bad = META.cases.filter(function(c){
      return verdicts[c.id] && verdicts[c.id].v === 'X';
    });
    if(!bad.length){ return '아직 “안 나옴” 으로 찍은 케이스가 없습니다.'; }
    var byWhere = {};
    bad.forEach(function(c){
      var tags = (verdicts[c.id].tags && verdicts[c.id].tags.length)
                 ? verdicts[c.id].tags : ['자리 미지정'];
      tags.forEach(function(t){ (byWhere[t] = byWhere[t] || []).push(c); });
    });
    var out = ['# 개선 목록 — ' + META.model + ' · ' + META.arm,
               '', '안 나옴 ' + bad.length + ' / 전체 ' + META.cases.length + ' 케이스', ''];
    META.where.concat(['자리 미지정']).forEach(function(w){
      if(!byWhere[w]){ return; }
      out.push('## ' + w, '');
      byWhere[w].forEach(function(c){
        out.push('- **' + c.id + '** (' + c.cat + ') ' + c.q);
        var n = (verdicts[c.id].note || '').trim();
        out.push('  - ' + (n ? n : '_사유 미기입_'));
      });
      out.push('');
    });
    return out.join('\\n');
  }
  function refresh(){
    var done = 0, o = 0, x = 0;
    META.cases.forEach(function(c){
      var rec = verdicts[c.id];
      if(rec && rec.v){ done++; if(rec.v === 'O'){ o++; } else { x++; } }
    });
    var n = META.cases.length;
    document.getElementById('prog').innerHTML = done
      ? '판정 <b>' + done + '/' + n + '</b> · <span class="o">잘 나옴 ' + o
        + '</span> · <span class="x">안 나옴 ' + x + '</span>'
      : '아직 판정 없음 — ' + n + ' 케이스';
    document.getElementById('out-csv').value = buildCSV();
    document.getElementById('out-md').value = buildMD();
    if(state.todo){ apply(); }
  }

  var dock = document.getElementById('dock');
  document.getElementById('toggle-export').addEventListener('click', function(){
    dock.classList.toggle('open');
    this.textContent = dock.classList.contains('open') ? '닫기' : '판정 내보내기';
    if(dock.classList.contains('open')){ document.getElementById('out-csv').select(); }
  });
  document.getElementById('wipe').addEventListener('click', function(){
    if(this.dataset.armed !== '1'){
      this.dataset.armed = '1'; this.textContent = '정말 지울까요? 한 번 더';
      var b = this;
      setTimeout(function(){ b.dataset.armed = ''; b.textContent = '전부 지우기'; }, 4000);
      return;
    }
    verdicts = {}; save();
    document.querySelectorAll('.judge').forEach(paintJudge);
    this.dataset.armed = ''; this.textContent = '전부 지우기';
    refresh(); apply();
  });

  apply(); refresh();
})();
"""



# 안 나온 답이 어디서 고쳐지는가 — 이 저장소에서 실제로 손댈 수 있는 자리들.
# 자유 서술만 받으면 나중에 묶기가 어려워, 자리부터 고르고 이유를 적게 한다.
FIX_WHERE = [
    ("도구 설명", "modules/routes.py 의 도구·인자 설명"),
    ("시스템 프롬프트", "bench/harness.py 의 역할·답변 규칙"),
    ("도구 응답", "modules/tools.py 가 돌려주는 값·문장"),
    ("서버 로직", "판정·경로·천문 계산 자체"),
    ("채점 규칙", "score.py 가 사람과 다르게 셈"),
    ("케이스 설계", "질문·정답이 잘못 잡힘"),
]


def judge_box(cid: str) -> str:
    chips = "".join(
        f'<button type="button" data-tag="{html.escape(w)}" title="{html.escape(tip)}" '
        f'aria-pressed="false">{html.escape(w)}</button>'
        for w, tip in FIX_WHERE)
    return (
        f'<div class="judge" data-cid="{cid}">'
        '<span class="lbl">이 답,</span>'
        '<button type="button" class="jbtn o" data-v="O" aria-pressed="false">잘 나옴</button>'
        '<button type="button" class="jbtn x" data-v="X" aria-pressed="false">안 나옴</button>'
        '<button type="button" class="jclear hidden">지우기</button>'
        '<span class="seal"></span>'
        '<div class="fix">'
        '<p class="why">어디를 고쳐야 하나 — 자리를 고르고, 무엇이 어떻게 되어야 하는지 한 줄 적습니다.</p>'
        f'<div class="chips">{chips}</div>'
        '<textarea rows="3" placeholder="예: 도구가 준 verdict 를 답변 첫 문단에 그대로 옮기게 해야 한다"></textarea>'
        '</div></div>')


def stat(k, v, d, tone=""):
    return (f'<div class="stat {tone}"><div class="k">{k}</div>'
            f'<div class="v">{v}</div><div class="d">{d}</div></div>')


def main() -> None:
    goldf = json.loads((RESULTS / "gold.json").read_text(encoding="utf-8"))
    gold, gen_at = goldf["gold"], goldf.get("generated_at", "")
    known = load_known_places()
    runs, labels = load_runs()

    for label in labels:
        arms = sorted({a for (lb, _), d in runs.items() if lb == label for a in d})
        marms = [a for a in arms if a.startswith("mcp")]
        if not marms:
            continue
        marm = marms[0]

        cards, tot, meta_cases = [], defaultdict(lambda: [0, 0]), []
        for cid, case in BY_ID.items():
            reps = runs.get((label, cid), {}).get(marm, [])
            if not reps:
                continue
            reps = sorted(reps, key=lambda r: r.get("rep", 0))
            scs = [score_run(r, gold, known) for r in reps]
            r0, s0 = reps[0], scs[0]
            resp = gold.get(cid, {}).get("response", {})

            for key in ("tsa", "aem", "tsr", "abstain_ok"):
                for s in scs:
                    if s.get(key) is not None:
                        tot[key][1] += 1
                        tot[key][0] += bool(s[key])
            for key in ("gfr_parts", "fnr_parts", "map_parts", "mapfake_parts"):
                for s in scs:
                    if s.get(key):
                        tot[key][0] += s[key][0]
                        tot[key][1] += s[key][1]

            n = len(scs)
            tsa_n = sum(bool(s["tsa"]) for s in scs)
            bad_n = sum(s["fnr_parts"][0] for s in scs)
            fake_n = sum(s["mapfake_parts"][0] for s in scs)
            eng_flag = any(stray_latin(r.get("answer", ""), resp) for r in reps)
            if tsa_n < n or any(not s["tsr"] for s in scs):
                flag = "fail"
            elif bad_n or fake_n or eng_flag:
                flag = "warn"
            else:
                flag = "pass"

            tags = [f'<span class="tag {"pass" if tsa_n == n else "fail"}">도구 선택 {tsa_n}/{n}</span>']
            aem = [s["aem"] for s in scs if s["aem"] is not None]
            if aem:
                tags.append(f'<span class="tag {"pass" if all(aem) else "fail"}">'
                            f'인자 일치 {sum(map(bool, aem))}/{len(aem)}</span>')
            g_h = sum(s["gfr_parts"][0] for s in scs)
            g_t = sum(s["gfr_parts"][1] for s in scs)
            if g_t:
                tags.append(f'<span class="tag {"pass" if g_h == g_t else "warn"}">근거 {g_h}/{g_t}</span>')
            tags.append(f'<span class="tag {"pass" if not bad_n else "fail"}">환각 수치 {bad_n}건</span>')
            eng_n = sum(len(stray_latin(r.get("answer", ""), resp)) for r in reps)
            if eng_n:
                tags.append(f'<span class="tag warn">한영 혼용 {eng_n}건</span>')
            jar_n = sum(len(jargon_spans(r.get("answer", ""))) for r in reps)
            if jar_n:
                tags.append(f'<span class="tag jargon">어려운 말 {jar_n}건</span>')
            if s0["map_parts"]:
                mh = sum(s["map_parts"][0] for s in scs)
                tags.append(f'<span class="tag {"pass" if mh == n else "fail"}">지도 {mh}/{n}</span>')
            if s0["abstain_ok"] is not None:
                ab = sum(bool(s["abstain_ok"]) for s in scs)
                tags.append(f'<span class="tag {"pass" if ab == n else "fail"}">모른다고 밝힘 {ab}/{n}</span>')

            want = case["gold_tool"] or "도구 부르지 않기"
            wargs = json.dumps({k: case["gold_args"][k] for k in case["required"]},
                               ensure_ascii=False) if case["required"] else ""
            base = runs.get((label, cid), {}).get("baseline", [])

            L = [f'<article class="case {flag}" data-cat="{case["category"]}" data-flag="{flag}">',
                 '<div class="case-head">',
                 f'<span class="cid">{cid}</span>',
                 f'<span class="tag">{CAT_KR[case["category"]]}</span>',
                 *tags, '</div>',
                 f'<p class="q">{html.escape(case["question"])}</p>',
                 '<dl class="rows">',
                 f'<dt>기대 호출</dt><dd><code class="chip"><b>{html.escape(want)}</b> '
                 f'{html.escape(wargs)}</code></dd>',
                 f'<dt>실제 호출</dt><dd>{call_chip(r0)}</dd>',
                 f'<dt>도구 정답</dt><dd>{gold_chips(case, resp)}</dd>']
            if s0["missed"]:
                L.append('<dt>답에 없던 값</dt><dd><span class="muted">'
                         + html.escape(", ".join(s0["missed"][:5])) + '</span></dd>')
            if r0.get("tool_errors"):
                L.append('<dt>도구 오류</dt><dd><span class="muted">'
                         + html.escape(str(r0["tool_errors"])) + '</span></dd>')
            L.append('</dl>')
            L.append('<div class="answer">'
                     + paint(r0.get("answer", ""), resp, case["question"], known, case["category"])
                     + '</div>')
            if base:
                L.append('<details class="base"><summary>도구 없이 쓴 답(baseline)과 비교</summary>')
                L.append('<div class="answer">'
                         + paint(base[0].get("answer", ""), resp, case["question"], known,
                                 case["category"])
                         + '</div></details>')
            L.append(judge_box(cid))
            L.append('</article>')
            cards.append("\n".join(L))
            meta_cases.append({"id": cid, "q": case["question"],
                               "cat": CAT_KR[case["category"]], "flag": flag})

        meta_js = {"model": label, "arm": marm, "cases": meta_cases,
                   "where": [w for w, _ in FIX_WHERE]}

        def ratio_of(k):
            a, b = tot[k]
            return (f"{100 * a / b:.1f}%" if b else "—"), f"{a}/{b}"

        tsa, tsa_d = ratio_of("tsa")
        aemv, aem_d = ratio_of("aem")
        gfr, gfr_d = ratio_of("gfr_parts")
        mp, mp_d = ratio_of("map_parts")
        tsr, tsr_d = ratio_of("tsr")
        fb, ft = tot["fnr_parts"]
        fnr = f"{100 * fb / ft:.1f}%" if ft else "—"

        rail = "\n    ".join([
            stat("도구 선택 TSA", tsa, tsa_d, "is-good" if tot["tsa"][0] == tot["tsa"][1] else "is-bad"),
            stat("인자 일치 AEM", aemv, aem_d, "is-good" if tot["aem"][0] == tot["aem"][1] else "is-bad"),
            stat("근거 재현 GFR", gfr, gfr_d),
            stat("환각 수치 FNR", fnr, f"{fb}/{ft}", "is-good" if fb == 0 else "is-bad"),
            stat("지도 전달", mp, mp_d),
            stat("과제 성공 TSR", tsr, tsr_d),
        ])

        page = (
            "<title>제주 별 MCP 검수대</title>\n"
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
            'family=Gowun+Batang:wght@400;700&family=IBM+Plex+Mono:wght@400;600&'
            'family=IBM+Plex+Sans+KR:wght@300;400;500;600&display=swap">\n'
            f"<style>{CSS}</style>\n"
            '<header class="top"><div class="top-inner">\n'
            '  <p class="eyebrow">Jeju-Star MCP · 사람 검수</p>\n'
            f'  <h1>{html.escape(label)} 가 도구를 부르고 쓴 답, 24 케이스</h1>\n'
            '  <p class="sub">운영 서버가 지금 주는 도구 설명 그대로 · 케이스당 3회 · 정답은 '
            f'<code>{html.escape(gen_at)}</code> 에 도구를 직접 불러 만든 것</p>\n'
            f'  <div class="rail">\n    {rail}\n  </div>\n'
            '  <div class="filters">\n'
            '    <button data-cat="all">전체 24</button>\n'
            '    <button data-cat="recommend">추천 7</button>\n'
            '    <button data-cat="evaluate">판정 8</button>\n'
            '    <button data-cat="details">상세 5</button>\n'
            '    <button data-cat="no-tool">도구 금지 4</button>\n'
            '    <button data-only="1">눈여겨볼 것만</button>\n'
            '    <button data-todo="1">아직 안 본 것만</button>\n'
            '  </div>\n'
            '</div></header>\n'
            '<div class="wrap">\n'
            '  <div class="legend">\n'
            '    <span><span class="sw g"></span><b>근거 있는 수치</b> — 도구 응답이나 질문에 있는 값</span>\n'
            '    <span><span class="sw b"></span><b>환각 수치 · 위조 주소</b> — 어디에도 없는 값</span>\n'
            '    <span><span class="sw a"></span><b>도구가 준 지도 주소</b></span>\n'
            '    <span><span class="sw w"></span><b>검증 목록에 없는 지명</b> (추천 케이스만) · '
            '<b><i>한국어 답에 섞인 영어</i></b></span>\n'
            '    <span><span class="sw j"></span><b>어려운 말</b> — 짚어 보면 풀어 쓴 뜻이 나옵니다</span>\n'
            '  </div>\n'
            + "".join(cards) +
            '\n  <footer>색칠 기준은 <code>score.py</code> 의 규칙 채점과 같다 — 수치는 도구 응답·질문의 '
            '값과 ±0.5(또는 2%) 안이면 근거 있음으로 본다. 지도 주소는 겉면 도메인이 아니라 '
            '<code>/maps/&lt;해시&gt;</code> 조각으로 맞춘다. 보이는 답변은 3회 중 첫 회이고, 배지의 '
            'n/3 은 세 회 전부를 센 것이다.</footer>\n'
            '</div>\n'
            '<div class="dock" id="dock">\n'
            '  <div class="dock-bar">\n'
            '    <span class="prog" id="prog">아직 판정 없음 — 24 케이스</span>\n'
            '    <button type="button" class="act" id="toggle-export">판정 내보내기</button>\n'
            '    <button type="button" class="act ghost" id="wipe">전부 지우기</button>\n'
            '  </div>\n'
            '  <div class="dock-panel">\n'
            '    <h3>1 · verdicts.csv</h3>\n'
            '    <p class="how">아래를 통째로 <code>bench/results/verdicts.csv</code> 에 붙여넣고 '
            '<code>python score.py</code> 를 다시 돌리면, 리포트에 사람 채점 열이 붙습니다.</p>\n'
            '    <textarea id="out-csv" readonly></textarea>\n'
            '    <h3>2 · 개선 목록</h3>\n'
            '    <p class="how">“안 나옴” 으로 찍은 것만 자리별로 묶은 것입니다. 그대로 이슈나 '
            '커밋 메시지로 옮길 수 있습니다.</p>\n'
            '    <textarea id="out-md" readonly></textarea>\n'
            '  </div>\n'
            '</div>\n'
            f"<script>var META = {json.dumps(meta_js, ensure_ascii=False)};</script>\n"
            f"<script>{JS}</script>\n"
        )
        out = RESULTS / f"REVIEW_{label.replace('/', '_')}.html"
        out.write_text(page, encoding="utf-8")
        print(f"→ {out}  ({len(cards)} 케이스 · {out.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
