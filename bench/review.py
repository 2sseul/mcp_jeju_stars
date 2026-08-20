"""사람이 읽고 판정하는 검토 시트를 만든다.

자동 채점(score.py)은 규칙이라 애매한 것을 못 가른다. 그래서 케이스마다
**질문 · 기대 호출 · 실제 호출 · 도구가 돌려준 정답 · 두 arm 의 답변**을 한자리에
놓고, 사람이 O/X 만 찍으면 되게 한다.

    python review.py                      → results/REVIEW_<모델>.md · results/verdicts.csv (빈 양식)

판정을 적는 곳은 `results/verdicts.csv` 다. 이미 있으면 덮어쓰지 않는다 —
사람이 채운 판정이 날아가면 안 되기 때문이다. 채워 넣은 뒤 score.py 를 다시 돌리면
리포트에 "사람 채점" 열이 붙는다.

verdicts.csv 열:
    model,arm,case_id,verdict,note
    verdict 는 O(맞음) · X(틀림) · ?(판단보류/미기입). 빈칸은 미기입으로 본다.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cases import BY_ID  # noqa: E402
from score import fact_hits, jpath, load_known_places, score_run  # noqa: E402

HERE = Path(__file__).parent
RESULTS = HERE / "results"
RAW = RESULTS / "raw"


def gold_evidence(case: dict, resp: dict) -> str:
    """이 케이스에서 답변에 실려야 하는 값들을 사람이 읽게 늘어놓는다."""
    if not resp:
        return "(정답 없음)"
    bits = []
    for spec in case.get("facts", []):
        for v in jpath(resp, spec["path"]):
            bits.append(f"`{spec['path'].split('.')[-1]}={v}`")
    if not bits:
        bits.append("(검증 대상 값 없음 — 도구를 부르지 않는 것이 정답)")
    head = str(resp.get("verdict", ""))[:80]
    return (f"**verdict**: {head}\n\n  - " + " · ".join(bits)) if head else " · ".join(bits)


def main() -> None:
    gold = json.loads((RESULTS / "gold.json").read_text(encoding="utf-8"))["gold"]
    known = load_known_places()

    runs = defaultdict(dict)      # (label, case_id) → {arm: run}
    labels = set()
    for f in sorted(RAW.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("rep", 0) != 0:      # 반복 3회는 같은 설정이라 첫 회만 본다
                continue
            # 도구 설명 판본이 다르면 다른 arm 으로 본다(score.py 와 같은 규칙).
            arm = r["arm"]
            v = r.get("variant", "-")
            if arm == "mcp" and v not in ("v0", "-"):
                arm = f"mcp-{v}"
            r["arm"] = arm
            runs[(r["label"], r["case_id"])][arm] = r
            labels.add(r["label"])

    rows = []
    for label in sorted(labels):
        L = []
        w = L.append
        w(f"# 사람 채점 시트 — {label}\n")
        w("각 케이스에서 **도구를 제대로 골라 제대로 된 인자로 불렀는지**, 그리고 "
          "**답변이 도구 결과에 충실한지**를 보고 `results/verdicts.csv` 에 O/X 를 적는다.\n")
        w("- `verdict=O` 사람이 보기에 이 시행은 성공 · `X` 실패 · `?` 보류\n")
        w("- 자동 채점 결과는 참고용으로 각 항목에 붙여 둔다. 사람 판정이 있으면 "
          "리포트는 그것을 함께 싣는다.\n")
        w("---\n")

        for cid in [c for c in BY_ID if (label, c) in runs]:
            case = BY_ID[cid]
            pair = runs[(label, cid)]
            resp = gold.get(cid, {}).get("response", {})
            marms = sorted(a for a in pair if a.startswith("mcp"))
            b = pair.get("baseline")

            w(f"## {cid} · {case['category']}\n")
            w(f"**질문** — {case['question']}\n")
            want = case["gold_tool"] or "(도구 부르지 않기)"
            args = json.dumps({k: case['gold_args'][k] for k in case['required']},
                              ensure_ascii=False) if case["required"] else "{}"
            w(f"**기대 호출** — `{want}` {args}\n")
            w(f"**도구가 돌려준 정답** — {gold_evidence(case, resp)}\n")

            if b:
                w("<details><summary><b>[baseline] 도구 없이 쓴 답</b></summary>\n")
                w("\n> " + (b["answer"] or "(빈 응답)").replace("\n", "\n> ") + "\n")
                w("</details>\n")
                rows.append([label, "baseline", cid, "", ""])

            mark = lambda x: "OK" if x else "X"
            for marm in marms:
                m = pair[marm]
                sc = score_run(m, gold, known)
                calls = m["tool_calls"]
                got = (f"`{calls[0]['name']}` "
                       f"{json.dumps(calls[0]['arguments'], ensure_ascii=False)}"
                       if calls else "**(도구 안 부름)**")
                w(f"### [{marm}]\n")
                w(f"- 실제 호출 — {got}")
                w(f"- 자동채점 — 도구선택 {mark(sc['tsa'])} · "
                  f"인자 {mark(sc['aem']) if sc['aem'] is not None else '-'} · "
                  f"근거 {sc['gfr_parts'][0]}/{sc['gfr_parts'][1]} · "
                  f"환각수치 {sc['fnr_parts'][0]}/{sc['fnr_parts'][1]} · "
                  f"지도 {mark(sc['map_parts'][0]) if sc['map_parts'] else '-'}")
                if len(calls) > 1:
                    w(f"- 추가 호출: {[c['name'] for c in calls[1:]]}")
                if m["tool_errors"]:
                    w(f"- 도구 오류: {m['tool_errors']}")
                if sc["missed"]:
                    w(f"- 답변에 없던 근거: {', '.join(sc['missed'][:4])}")
                w("")
                w("> " + (m["answer"] or "(빈 응답)").replace("\n", "\n> ") + "\n")
                rows.append([label, marm, cid, "", ""])

            if not marms:
                w("**실제 호출** — (측정 없음)\n")

            w(f"판정 → `verdicts.csv` 의 해당 행 verdict 열에 O | X | ? 를 적는다 "
              f"(arm: {', '.join(['baseline'] + marms)})\n")
            w("---\n")

        out = RESULTS / f"REVIEW_{label.replace('/', '_')}.md"
        out.write_text("\n".join(L), encoding="utf-8")
        print(f"→ {out}")

    csv_path = RESULTS / "verdicts.csv"
    if csv_path.exists():
        print(f"= {csv_path} (이미 있어 두었다 — 사람이 채운 판정을 덮어쓰지 않는다)")
    else:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            wtr = csv.writer(f)
            wtr.writerow(["model", "arm", "case_id", "verdict", "note"])
            wtr.writerows(sorted(rows))
        print(f"→ {csv_path} ({len(rows)} 행 · verdict 열에 O/X/? 를 채우세요)")


if __name__ == "__main__":
    main()
