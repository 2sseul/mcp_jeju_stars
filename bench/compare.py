"""고치기 전 ↔ 후를 한 표로 세운다.

세 가지를 고친 뒤(기본 시각 22:00→23:00 · 도구 산문의 어려운 말 · 반려동물 필터
버그) 같은 모델·같은 케이스로 다시 잰 값을, 고치기 전 값과 나란히 놓는다.

    python compare.py     → results/COMPARE_<날짜>.md

전(前) 자료는 `results/raw_before_fix/` 에 있고 **그때의 정답(gold.json)으로** 채점한다.
정답이 바뀐 수정(기본 시각)이 섞여 있어, 각 시행을 제 짝인 정답으로 채점하지 않으면
개선이 아니라 정답 교체가 숫자로 잡힌다.

규칙 채점이 못 보는 두 축(한영 혼용·어려운 말)은 review_html.py 의 탐지기를 그대로
쓴다. 검수 페이지에서 눈으로 본 것과 같은 기준이어야 표와 화면이 어긋나지 않는다.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from cases import BY_ID                                        # noqa: E402
from review_html import jargon_spans, stray_latin              # noqa: E402
from score import load_known_places, score_run, wilson         # noqa: E402

RESULTS = HERE / "results"
BEFORE = RESULTS / "raw_before_fix"
AFTER = RESULTS / "raw"

# 반려동물 판정은 서버와 **같은 함수**를 쓴다. 여기서 다시 짜면 서버가 고쳐져도
# 표가 옛 기준으로 남는다.
from modules.core.spots import all_spots, pets_allowed         # noqa: E402


def load(folder: Path, arm_wanted: str) -> list:
    out = []
    for f in sorted(folder.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["arm"] != arm_wanted:
                continue
            if arm_wanted == "mcp" and r.get("variant", "v0") not in ("v0", "-"):
                continue
            out.append(r)
    return out


def gold_of(folder: Path) -> dict:
    p = folder / "gold.json"
    if not p.exists():
        p = RESULTS / "gold.json"
    return json.loads(p.read_text(encoding="utf-8"))["gold"]


def rate(rows: list, key: str):
    """(비율, 맞은 수, 전체) — None 인 시행은 분모에서 뺀다."""
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None, 0, 0
    k = sum(1 for v in vals if v)
    return k / len(vals), k, len(vals)


def parts(rows: list, key: str):
    a = b = 0
    for r in rows:
        if r.get(key):
            a += r[key][0]
            b += r[key][1]
    return (a / b if b else None), a, b


def pets_violations(runs: list, gold: dict) -> tuple[int, int]:
    """(답변이 말한 동반 불가인 곳 수, 도구가 내놓은 동반 불가인 곳 수).

    R-04("강아지 데리고 갈 수 있는 곳")에서만 센다. 도구 쪽 숫자는 시행마다 같으므로
    한 번만 세고, 답변 쪽은 시행마다 센다.
    """
    banned = {s.name for s in all_spots() if pets_allowed(s.pets) is False}
    said = 0
    for r in runs:
        if r["case_id"] != "R-04":
            continue
        ans = r.get("answer") or ""
        said += sum(1 for n in banned if n in ans)
    resp = gold.get("R-04", {}).get("response", {}) or {}
    served = sum(1 for s in resp.get("spots", []) if s.get("name") in banned)
    return said, served


def set_adherence(runs: list, gold: dict) -> tuple[int, int]:
    """(도구가 준 곳인 이름 수, 답변이 말한 검증된 이름 수) — 추천 케이스만.

    **PNR 로는 못 잡는 환각이 있다.** PNR 은 "제주에 실재하는 이름인가"만 보므로,
    도구가 아부오름을 줬는데 모델이 물영아리오름이라고 써도 통과한다(둘 다 62곳
    목록에 있으므로). 실제로 R-01 에서 그런 일이 났다 — 이름을 바꾸고 구름 50%·
    도보 35분까지 지어냈다.

    그래서 "이 답이 말한 곳이 **이번 호출이 돌려준 곳**인가"를 따로 센다.
    """
    good = tot = 0
    for r in runs:
        if not r["case_id"].startswith("R-"):
            continue
        resp = gold.get(r["case_id"], {}).get("response", {}) or {}
        served = {s["name"] for s in resp.get("spots", [])}
        if not served:
            continue
        ans = (r.get("answer") or "").replace(" ", "")
        for name in {s.name for s in all_spots()}:
            if name.replace(" ", "") in ans:
                tot += 1
                good += int(name in served)
    return good, tot


def quality_counts(runs: list, gold: dict) -> tuple[int, int]:
    """(한영 혼용 건수, 어려운 말 건수) — 규칙 채점 밖의 두 축."""
    eng = jar = 0
    for r in runs:
        resp = gold.get(r["case_id"], {}).get("response", {}) or {}
        ans = r.get("answer") or ""
        eng += len(stray_latin(ans, resp))
        jar += len(jargon_spans(ans))
    return eng, jar


def collect(folder: Path) -> dict:
    gold = gold_of(folder)
    known = load_known_places()
    out = {}
    for arm in ("baseline", "mcp"):
        runs = load(folder, arm)
        if not runs:
            continue
        scored = [score_run(r, gold, known) for r in runs]
        no_tool = [s for s in scored if BY_ID[s["case_id"]]["gold_tool"] is None]
        d = {
            "n": len(runs),
            "tsa": rate(scored, "tsa"),
            "aem": rate(scored, "aem"),
            "tsr": rate(scored, "tsr"),
            "abstain": rate(scored, "abstain_ok"),
            "f1": parts(scored, "f1_parts"),
            "gfr": parts(scored, "gfr_parts"),
            "fnr": parts(scored, "fnr_parts"),
            "pnr": parts(scored, "pnr_parts"),
            "map": parts(scored, "map_parts"),
            "mapfake": parts(scored, "mapfake_parts"),
            "otr": (sum(1 for s in no_tool if s["called"]) / len(no_tool) if no_tool else None,
                    sum(1 for s in no_tool if s["called"]), len(no_tool)),
        }
        d["eng"], d["jar"] = quality_counts(runs, gold)
        g, t = set_adherence(runs, gold)
        d["rsa"] = (g / t if t else None, g, t)
        d["pets"] = pets_violations(runs, gold)
        out[arm] = d
    gp = folder / "gold.json"
    if not gp.exists():          # 후(後) 자료는 현재 정답을 쓴다 — raw/ 에 사본을 두지 않는다.
        gp = RESULTS / "gold.json"
    out["_gold_at"] = json.loads(gp.read_text(encoding="utf-8")).get("generated_at", "?")
    return out


def pct(x):
    return "—" if x is None else f"{100 * x:.1f}%"


def arrow(before, after, higher_better: bool) -> str:
    """변화 표시. 같으면 '유지', 좋아지면 ▲, 나빠지면 ▼."""
    if before is None or after is None:
        return ""
    d = after - before
    if abs(d) < 1e-9:
        return "유지"
    good = (d > 0) == higher_better
    sign = "+" if d > 0 else ""
    return f"{'▲' if good else '▼'} {sign}{100 * d:.1f}%p"


def main() -> None:
    if not BEFORE.exists():
        sys.exit(f"고치기 전 자료가 없다: {BEFORE}")
    b, a = collect(BEFORE), collect(AFTER)
    L = []
    w = L.append

    w("# 고치기 전 ↔ 후 — qwen3.5:4b · 24케이스 × 3회\n")
    w(f"작성 {datetime.now():%Y-%m-%d %H:%M} (KST) · "
      f"전 정답 `{b['_gold_at']}` · 후 정답 `{a['_gold_at']}`\n")
    w("고친 것 셋:\n")
    w("1. **기준 시각 22:00 → 23:00** — 시각을 안 준 질문의 기본값 "
      "(`modules/tools.py: DEFAULT_HOUR`). 정답도 같이 옮겼다.")
    w("2. **도구 산문의 어려운 말** — `Bortle`·`SQM`·`Falchi`·`광공해`·`총운량`·"
      "`수평시정`·`nW·cm⁻²·sr⁻¹` 를 쉬운 말로. `numbers` 의 값은 그대로다.")
    w("3. **반려동물 필터 버그** — `\"가능\" in \"반려견 동반 불가능\"` 이 참이라 "
      "동반 불가 16곳이 통과하고, 목줄 조건 3곳이 빠졌다.\n")
    w("그리고 두 arm 공용 시스템 프롬프트에 \"한국어로만 쓰세요\" 한 줄을 넣었다.\n")

    w("## 1. 도구 사용 (arm B)\n")
    w("| 지표 | 전 | 후 | 변화 |")
    w("|---|---|---|---|")
    rows_tool = [
        ("도구 선택 TSA", "tsa", True, True),
        ("인자 정확 AEM", "aem", True, True),
        ("인자 슬롯 F1", "f1", True, False),
        ("과잉호출 OTR", "otr", False, True),
    ]
    for label, key, higher, as_pct in rows_tool:
        bv, av = b["mcp"][key], a["mcp"][key]
        if as_pct:
            w(f"| {label} | {pct(bv[0])} <sub>{bv[1]}/{bv[2]}</sub> | "
              f"{pct(av[0])} <sub>{av[1]}/{av[2]}</sub> | {arrow(bv[0], av[0], higher)} |")
        else:
            bs = "—" if bv[0] is None else f"{bv[0]:.3f}"
            as_ = "—" if av[0] is None else f"{av[0]:.3f}"
            w(f"| {label} | {bs} | {as_} | "
              f"{'유지' if bs == as_ else ('▲' if av[0] > bv[0] else '▼')} |")

    w("\n## 2. 답변 품질 (arm B)\n")
    w("| 지표 | 전 | 후 | 변화 |")
    w("|---|---|---|---|")
    for label, key, higher in [
        ("근거 재현 GFR", "gfr", True),
        ("환각 수치 FNR", "fnr", False),
        ("장소명 유효 PNR", "pnr", True),
        ("추천한 곳이 도구가 준 곳 RSA", "rsa", True),
        ("지도주소 전달", "map", True),
        ("과제 성공 TSR", "tsr", True),
        ("모른다고 밝힘 ABS", "abstain", True),
    ]:
        bv, av = b["mcp"][key], a["mcp"][key]
        w(f"| {label} | {pct(bv[0])} <sub>{bv[1]}/{bv[2]}</sub> | "
          f"{pct(av[0])} <sub>{av[1]}/{av[2]}</sub> | {arrow(bv[0], av[0], higher)} |")

    w("\n## 3. 이번에 고친 세 가지가 실제로 잡혔는가\n")
    w("| 무엇 | 전 | 후 |")
    w("|---|---|---|")
    w(f"| 답변에 섞인 영어 (72시행 합) | {b['mcp']['eng']}건 | {a['mcp']['eng']}건 |")
    w(f"| 답변의 어려운 말 (72시행 합) | {b['mcp']['jar']}건 | {a['mcp']['jar']}건 |")
    w(f"| R-04 — **도구가** 내놓은 동반 불가 장소 | {b['mcp']['pets'][1]}곳 | "
      f"{a['mcp']['pets'][1]}곳 |")
    w(f"| R-04 — **답변이** 말한 동반 불가 장소 (3시행 합) | {b['mcp']['pets'][0]}회 | "
      f"{a['mcp']['pets'][0]}회 |")

    w("\n## 4. 도구 없음(A) 대비 개선폭 — 수정 뒤에도 서는가\n")
    w("| 지표 | A 도구없음 | B MCP | 개선 |")
    w("|---|---|---|---|")
    for label, key, higher in [("근거 재현 GFR", "gfr", True),
                               ("환각 수치 FNR", "fnr", False),
                               ("과제 성공 TSR", "tsr", True)]:
        av, bv = a["baseline"][key], a["mcp"][key]
        w(f"| {label} | {pct(av[0])} | {pct(bv[0])} | "
          f"**{arrow(av[0], bv[0], higher)}**|")

    tsa = a["mcp"]["tsa"]
    lo, hi = wilson(tsa[1], tsa[2])
    w(f"\nTSA {pct(tsa[0])} 의 Wilson 95% 신뢰구간은 "
      f"[{100*lo:.0f}–{100*hi:.0f}]%p 다 (n={tsa[2]}).")

    w("\n## 5. 이 표가 말하지 못하는 것\n")
    w("- 두 측정의 **정답이 다르다.** 기본 시각을 옮겼으므로 시각을 안 준 케이스는 "
      "구름·시정 값이 통째로 바뀌었다. 각 시행을 제 짝인 정답으로 채점했으니 "
      "비율은 견줄 수 있지만, 절대값이 같아야 할 이유는 없다.")
    w("- **날씨는 두 측정 사이에도 움직인다.** 몇 시간 차이라 예보가 갱신됐다.")
    w("- 한영 혼용·어려운 말은 정규식 탐지라, 목록에 없는 말은 세지 않는다.")

    out = RESULTS / f"COMPARE_{datetime.now():%Y-%m-%d}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
