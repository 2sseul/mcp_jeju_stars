"""도구 설명·프롬프트를 고칠 때마다 도는 회귀 게이트.

왜 필요한가
--------------------------------------------------------------------------
이번 측정에서 **내용이 같고 표현만 다른** 변경이 지표를 두 자릿수 %p 로 움직였다.

    시스템 프롬프트 원칙을 6줄 → 7줄   TSA 100% → 91.7%  (도구를 아예 안 불렀다)
    같은 문장을 어순만 바꿈            GFR 82.5% → 66.7%  (수치를 통째로 뺐다)
    도구 산문의 숫자를 문장에 녹임      GFR 85.7% → 66.1%  (괄호째 버렸다)

셋 다 사람 눈에는 "같은 말"이라 리뷰로 걸러지지 않는다. 그래서 **숫자가 문지기를**
해야 한다. 이 파일은 기준선을 파일로 박아 두고, 새 측정이 그보다 정해진 폭 이상
떨어지면 0 이 아닌 코드로 끝난다 — CI 나 커밋 훅에 그대로 걸 수 있다.

쓰는 법
--------------------------------------------------------------------------
    python regress.py --save          # 지금 결과를 기준선으로 박는다
    python regress.py                 # 기준선과 견준다. 퇴행이면 exit 1

문턱은 지표마다 다르다. 도구 선택은 되느냐 마느냐라 조금만 떨어져도 막고, 근거
재현은 날씨가 바뀌면 자연히 흔들리므로 여유를 준다. 문턱을 넘지 않은 하락도 표에는
찍는다 — 막지 않는 것과 안 보이는 것은 다르다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from cases import BY_ID                                      # noqa: E402
from score import load_known_places, score_run               # noqa: E402

RESULTS = HERE / "results"
RAW = RESULTS / "raw"
BASELINE = RESULTS / "regress_baseline.json"

#: (지표, 사람이 읽는 이름, 허용 하락폭 %p, 높을수록 좋은가)
GATES = [
    ("tsa", "도구 선택 TSA", 2.0, True),
    ("pca", "인자 구성 PCA", 2.0, True),
    ("otr", "과잉호출 OTR", 2.0, False),
    ("tsr", "과제 성공 TSR", 3.0, True),
    ("map", "지도주소 전달", 3.0, True),
    ("gfr", "근거 재현 GFR", 5.0, True),
    ("fnr", "환각 수치 FNR", 3.0, False),
]


def measure(variant: str = "v0") -> dict:
    gold = json.loads((RESULTS / "gold.json").read_text(encoding="utf-8"))["gold"]
    known = load_known_places()
    rows = []
    for f in sorted(RAW.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["arm"] != "mcp":
                continue
            # 판본을 가른다. 안 가르면 v0 과 v3 시행이 한 통에 섞여 둘 다 흐려진다.
            if (r.get("variant") or "v0") != variant:
                continue
            rows.append(score_run(r, gold, known))
    if not rows:
        sys.exit(f"mcp arm({variant}) 결과가 없다 — 먼저 run_bench.py 를 돌린다.")

    def rate(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return (sum(1 for v in vals if v) / len(vals) * 100) if vals else None

    def parts(key):
        a = b = 0
        for r in rows:
            if r.get(key):
                a += r[key][0]
                b += r[key][1]
        return (a / b * 100) if b else None

    no_tool = [r for r in rows if BY_ID[r["case_id"]]["gold_tool"] is None]
    kinds = defaultdict(int)
    for r in rows:
        if r.get("fail_kind"):
            kinds[r["fail_kind"]] += 1

    return {
        "n": len(rows),
        "tsa": rate("tsa"), "pca": rate("pca"), "tsr": rate("tsr"),
        "gfr": parts("gfr_parts"), "fnr": parts("fnr_parts"), "map": parts("map_parts"),
        "otr": (sum(1 for r in no_tool if r["called"]) / len(no_tool) * 100) if no_tool else None,
        "fail_kinds": dict(kinds),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="지금 결과를 기준선으로 박는다")
    ap.add_argument("--variant", default="v0", help="견줄 도구 설명 판본 (기본 v0)")
    a = ap.parse_args()

    cur = measure(a.variant)
    if a.save:
        BASELINE.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"→ 기준선을 박았다: {BASELINE} (시행 {cur['n']})")
        return

    if not BASELINE.exists():
        sys.exit(f"기준선이 없다 — 먼저 `python regress.py --save` 를 돌린다 ({BASELINE})")
    base = json.loads(BASELINE.read_text(encoding="utf-8"))

    print(f"회귀 게이트 — 기준선(v0) 시행 {base['n']} · "
          f"이번({a.variant}) 시행 {cur['n']}\n")
    print(f"{'지표':<16}{'기준선':>9}{'이번':>9}{'변화':>9}   판정")
    failed = []
    for key, label, tol, higher in GATES:
        b, c = base.get(key), cur.get(key)
        if b is None or c is None:
            continue
        delta = c - b
        drop = -delta if higher else delta          # 나쁜 쪽으로 간 폭
        if drop > tol:
            verdict, mark = "퇴행", "✗"
            failed.append(f"{label} {b:.1f}% → {c:.1f}% (허용 {tol:.0f}%p)")
        elif drop > 0:
            verdict, mark = "하락(허용 안)", "·"
        else:
            verdict, mark = "유지·개선", " "
        print(f"{label:<16}{b:>8.1f}%{c:>8.1f}%{delta:>+8.1f}p   {mark} {verdict}")

    if cur["fail_kinds"]:
        order = {"tool": "도구 선택", "param": "인자 구성",
                 "workflow": "워크플로우 순서", "ground": "근거 누락"}
        bits = [f"{order.get(k, k)} {v}" for k, v in sorted(cur["fail_kinds"].items())]
        print("\n실패 갈래:", " · ".join(bits))
        print("  도구 선택 → 의도·키워드 · 인자 구성 → 형식/범위/제외 주석 · "
              "워크플로우 → 사전 조건 힌트 · 근거 누락 → 응답 산문")

    if failed:
        print("\n퇴행 " + str(len(failed)) + "건:")
        for f in failed:
            print("  -", f)
        sys.exit(1)
    print("\n퇴행 없음.")


if __name__ == "__main__":
    main()
