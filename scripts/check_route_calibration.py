"""주행시간 추정이 실제와 얼마나 맞나 (점검용, 아무것도 쓰지 않는다).

`core/routing.py` 의 `_JUNCTION_S`(갈림길 지연)는 문헌 상수가 아니라 **이 스크립트로
맞춘 값**이다. 그러니 그 값을 바꾸려면 여기서 근거를 다시 만든다.

`REFERENCE` 의 소요시간은 내비게이션 앱이 야간·정체 없음으로 안내하는 대략치다.
정밀 측정이 아니므로 **직접 재서 갱신할 것을 전제로 둔다** — 카카오내비·티맵에서
같은 구간을 재고 아래 표를 고친 뒤 이 스크립트를 돌리면 새 보정값이 나온다.

실행:
    uv run python -m scripts.check_route_calibration
"""

from __future__ import annotations

from server.core import routing

#: 출발지. 관광객 동선의 시작점이라 공항을 기준으로 삼는다.
ORIGIN = (33.5070, 126.4930)
ORIGIN_NAME = "제주국제공항"

#: (목적지, 좌표, 참고 소요시간 分, 참고 거리 km).
#: 참고값은 내비게이션 안내 기준의 대략치다 — 실측으로 갱신하라.
REFERENCE: list[tuple[str, tuple[float, float], float, float]] = [
    ("성산일출봉", (33.4588, 126.9408), 57.5, 55.0),
    ("서귀포시청", (33.2541, 126.5601), 50.0, 40.0),
    ("1100고지", (33.3608, 126.4650), 37.5, 26.0),
    ("새별오름", (33.3644, 126.3570), 27.5, 25.0),
    ("협재해변", (33.3940, 126.2396), 37.5, 30.0),
]

#: 시험해 볼 갈림길 지연(초).
CANDIDATES = (0.0, 5.0, 10.0, 15.0)


def _run(delay: float) -> list[tuple[str, float, float, float]]:
    """지연을 delay 로 두고 전 구간을 재본다. [(이름, 계산 分, 참고 分, 비율)]."""
    routing._JUNCTION_S = delay
    routes = routing.drive_times(ORIGIN, [c[1] for c in REFERENCE])
    out = []
    for (name, _, ref_min, _ref_km), r in zip(REFERENCE, routes, strict=True):
        if r is None:
            out.append((name, float("nan"), ref_min, float("nan")))
            continue
        out.append((name, r.minutes, ref_min, r.minutes / ref_min))
    return out


def main() -> None:
    original = routing._JUNCTION_S
    try:
        print(f"출발지: {ORIGIN_NAME} {ORIGIN}\n")
        best = None
        for delay in CANDIDATES:
            rows = _run(delay)
            ratios = [r for *_, r in rows if r == r]  # NaN 제외
            mean = sum(ratios) / len(ratios)
            spread = max(ratios) - min(ratios)
            mark = ""
            if best is None or abs(mean - 1.0) < abs(best[1] - 1.0):
                best = (delay, mean)
                mark = "  ← 지금까지 최적"
            print(
                f"=== 갈림길 지연 {delay:4.0f}초 · 평균 비율 {mean:.2f} · "
                f"편차 {spread:.2f}{mark}"
            )
            for name, got, ref, ratio in rows:
                print(
                    f"    {name:<10} {got:5.1f}분  "
                    f"(참고 {ref:4.1f}분)  비율 {ratio:4.2f}"
                )
            print()

        print(
            f"채택 권고: _JUNCTION_S = {best[0]:.0f}  (평균 비율 {best[1]:.2f})"
        )
        print(f"현재 코드값: _JUNCTION_S = {original:.0f}")
        if abs(best[0] - original) > 1e-9:
            print(
                "→ 값이 다르다. routing.py 를 고치고 "
                "주석의 보정 근거도 함께 갱신할 것."
            )
    finally:
        routing._JUNCTION_S = original


if __name__ == "__main__":
    main()
