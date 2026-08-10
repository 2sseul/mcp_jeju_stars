"""관측지 20곳 어둡기 근거 리포트 HTML 생성 (발표용, 오프라인 배치).

지도(`build_light_map`)가 "제주가 어떻게 생겼나"를 보여준다면, 이 리포트는
**"왜 신호를 셋이나 쓰나"**에 답한다. 한 장으로 그 근거가 드러나게 짰다.

    큐레이션 관측지 20곳 중 19곳이 Falchi iv — SQM 만으로는 순위가 갈리지 않는다.
    갈리는 것은 발밑 가로등이다(1100고지 1km 안 0개 ↔ 저지오름 23m 앞).

수치는 전부 `server.core.darkness.assess_site` 를 그대로 호출해 얻는다. 이 스크립트는
계산하지 않고 **표시만** 한다 — 리포트와 판정이 다른 숫자를 말하면 근거가 아니다.

가중치·경계는 운영값이라 화면에 그대로 노출한다(`docs/decisions.md` §1.8).

실행:
    uv run python -m scripts.build_spot_report
"""

from __future__ import annotations

import html
import json

from server import path
from server.core import darkness, lamps, nightlight

# --- 색 ----------------------------------------------------------------------
# dataviz 기준 팔레트 categorical 슬롯 1·2·3. 3계열 전체쌍 검증 통과
# (CVD ΔE 9.2 / 일반 ΔE 24.0, validate_palette.js --pairs all). aqua 는 밝은 표면에서
# 대비 3:1 미만이라 **표(table view)와 범례**로 식별을 보완한다(relief rule).
_SERIES = (
    {"key": "sqm", "label": "하늘밝기 SQM", "light": "#2a78d6", "dark": "#3987e5"},
    {"key": "lamp", "label": "가로등 근접", "light": "#eb6834", "dark": "#d95926"},
    {"key": "viirs", "label": "야간광 VIIRS", "light": "#1baf7a", "dark": "#199e70"},
)

#: 막대 하나에 실린 두 축(종합 점수 · 1km 안 가로등 수)은 눈금이 달라 **차트를 나눈다**.
#: 한 그림에 축 두 개를 그리지 않는다.


def _rows() -> list[dict]:
    """관측지 20곳 → 판정값 + 성분별 기여도. 정렬은 종합 점수 오름차순(어두운 순)."""
    spots = json.loads(path.SPOTS.read_text(encoding="utf-8"))["spots"]
    rows = []
    for spot in spots:
        site = darkness.assess_site(spot["lat"], spot["lon"])
        d, n, lamp = site.darkness, site.nightlight, site.lamps
        # SQM 격자 밖이면 종합 점수 자체가 없다(해상 등) — 표에 실을 값이 없어 건너뛴다.
        if d is None:
            continue
        near_max = n.near_max if n is not None else 0.0
        rows.append(
            {
                "name": spot["name_ko"],
                "region": spot["region"],
                "type": spot["type"],
                "why": spot["why"],
                "sqm": d.sqm,
                "falchi": d.falchi_grade,
                "falchiLabel": darkness.falchi_label(d.falchi_grade),
                "bortle": d.bortle,
                "milkyWay": d.milky_way,
                "nearestM": lamp.nearest_m,
                "lampNear": lamp.near,
                "lampFar": lamp.far,
                "viirsNear": near_max,
                "score": site.score,
                "cap": site.cap,
                # 가중합의 성분별 기여도 — 막대를 쌓으면 합이 곧 종합 점수다.
                "parts": {
                    "sqm": darkness.W_SQM * darkness.sqm_part(d.sqm),
                    "lamp": darkness.W_LAMP * darkness.lamp_part(lamp.nearest_m),
                    "viirs": darkness.W_NIGHTLIGHT * darkness.nightlight_part(near_max),
                },
            }
        )
    return sorted(rows, key=lambda r: r["score"])


_HTML = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>제주 관측지 20곳 — 어둡기 근거</title>
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7;
    --surface: #fcfcfb;
    --ink: #0b0b0b;
    --ink-2: #52514e;
    --ink-muted: #898781;
    --grid: #e1e0d9;
    --axis: #c3c2b7;
    --border: rgba(11, 11, 11, 0.10);
    --track: rgba(11, 11, 11, 0.055);
    --s-sqm: #2a78d6;
    --s-lamp: #eb6834;
    --s-viirs: #1baf7a;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
      --ink-muted: #898781; --grid: #2c2c2a; --axis: #383835;
      --border: rgba(255, 255, 255, 0.10); --track: rgba(255, 255, 255, 0.07);
      --s-sqm: #3987e5; --s-lamp: #d95926; --s-viirs: #199e70;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --ink-muted: #898781; --grid: #2c2c2a; --axis: #383835;
    --border: rgba(255, 255, 255, 0.10); --track: rgba(255, 255, 255, 0.07);
    --s-sqm: #3987e5; --s-lamp: #d95926; --s-viirs: #199e70;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--page); color: var(--ink);
    font: 14px/1.6 system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  }
  main { max-width: 1080px; margin: 0 auto; padding: 40px 24px 64px; }
  header { margin-bottom: 32px; }
  h1 { margin: 0 0 6px; font-size: 26px; font-weight: 600; letter-spacing: -0.02em; }
  header p { margin: 0; color: var(--ink-2); max-width: 62ch; }

  .hero {
    background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
    padding: 24px 26px; margin: 24px 0 32px;
    display: flex; align-items: baseline; gap: 24px; flex-wrap: wrap;
  }
  .hero .fig {
    font-size: 52px; font-weight: 600; line-height: 1; letter-spacing: -0.03em;
  }
  .hero .say { flex: 1 1 32ch; }
  .hero .say b { display: block; font-size: 15px; margin-bottom: 2px; }
  .hero .say span { color: var(--ink-2); font-size: 13px; }

  section { margin: 40px 0 0; }
  h2 { font-size: 17px; font-weight: 600; margin: 0 0 4px; letter-spacing: -0.01em; }
  .sub { margin: 0 0 18px; color: var(--ink-2); font-size: 13px; max-width: 68ch; }

  .legend {
    display: flex; gap: 16px; flex-wrap: wrap; margin: 0 0 16px; font-size: 12px;
  }
  .legend i {
    display: inline-block; width: 10px; height: 10px; border-radius: 3px;
    margin-right: 6px; vertical-align: -1px;
  }
  .legend span { color: var(--ink-2); }

  .chart {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 20px 22px;
  }
  .bars {
    display: grid; gap: 4px 14px; align-items: center;
    grid-template-columns: minmax(9ch, 20ch) 1fr minmax(5ch, auto);
  }
  .bars .name { font-size: 12.5px; color: var(--ink-2); text-align: right; }
  .bars .track {
    background: var(--track); border-radius: 4px; height: 14px; position: relative;
  }
  .bars .fill { position: absolute; inset: 0 auto 0 0; display: flex; height: 100%; }
  .bars .seg { height: 100%; }
  /* 데이터 끝만 둥글고 기준선(왼쪽)은 각지게. 세그먼트 사이는 2px 표면색 간격. */
  .bars .seg + .seg { margin-left: 2px; }
  .bars .fill .seg:last-child { border-radius: 0 4px 4px 0; }
  .bars .single { border-radius: 0 4px 4px 0; }
  .bars .val {
    font-size: 12.5px; color: var(--ink-2); font-variant-numeric: tabular-nums;
    text-align: right;
  }
  .bars .lead .name, .bars .lead .val { color: var(--ink); font-weight: 600; }
  .axis {
    grid-column: 2; display: flex; justify-content: space-between;
    font-size: 11px; color: var(--ink-muted); font-variant-numeric: tabular-nums;
    border-top: 1px solid var(--grid); margin-top: 8px; padding-top: 5px;
  }

  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { padding: 7px 10px; text-align: right; border-bottom: 1px solid var(--grid); }
  th { color: var(--ink-muted); font-weight: 500; white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  td { font-variant-numeric: tabular-nums; color: var(--ink-2); }
  td:first-child { color: var(--ink); }
  tbody tr:hover { background: var(--track); }
  .wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border);
          border-radius: 14px; padding: 8px 12px; }

  footer {
    margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--grid);
    font-size: 11.5px; color: var(--ink-muted); line-height: 1.7;
  }
  footer b { color: var(--ink-2); font-weight: 600; }

  #tip {
    position: fixed; z-index: 10; pointer-events: none; opacity: 0;
    transition: opacity .12s; background: var(--surface); color: var(--ink);
    border: 1px solid var(--border); border-radius: 8px; padding: 8px 11px;
    font-size: 12px; box-shadow: 0 6px 24px rgba(0, 0, 0, .18); max-width: 34ch;
  }
  #tip b { display: block; margin-bottom: 3px; }
</style>
<main>
  <header>
    <h1>제주 관측지 20곳 — 어둡기 근거</h1>
    <p>큐레이션한 관측지들이 실제로 어두운지, 그리고
       <b>왜 광공해 신호를 셋이나 쓰는지</b>를 수치로 확인한다. 모든 값은 MCP
       판정 경로(<code>core.darkness.assess_site</code>)가 내놓는 것과 같다.</p>
  </header>

  <div class="hero">
    <div class="fig" id="heroFig"></div>
    <div class="say">
      <b id="heroLead"></b>
      <span id="heroSub"></span>
    </div>
  </div>

  <section>
    <h2>종합 어둡기 점수 — 무엇이 순위를 가르나</h2>
    <p class="sub">낮을수록 어둡다(0 = 완전 암흑, 1 = 도심). 막대는 세 신호의
      가중 기여도를 쌓은 것이라 길이의 합이 곧 점수다. 등급이 같아도
      <b>주황(가로등)</b> 칸이 길면 실제 관측은 나빠진다.</p>
    <div class="legend" id="legend"></div>
    <div class="chart"><div class="bars" id="scoreChart"></div></div>
  </section>

  <section>
    <h2>반경 1km 안 가로등 수</h2>
    <p class="sub">위 차트와 <b>같은 순서</b>다. 하늘밝기로는 갈리지 않던 곳들이 여기서
      갈린다 — 격자 데이터는 관측자 바로 옆 가로등 하나를 픽셀 평균에 묻어 버린다.</p>
    <div class="chart"><div class="bars" id="lampChart"></div></div>
  </section>

  <section>
    <h2>전체 수치</h2>
    <p class="sub">SQM 은 클수록 어둡고, 종합 점수는 작을수록 어둡다.</p>
    <div class="wrap"><table id="table"></table></div>
  </section>

  <footer id="footer"></footer>
</main>
<div id="tip"></div>
<script>
const DATA = /*__DATA__*/;
const esc = function (s) { return String(s).replace(/[&<>]/g, function (c) {
  return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); };

/* --- 호버 툴팁 (마크보다 넉넉한 히트 영역은 track 전체) --- */
const tip = document.getElementById('tip');
function bindTip(el, html) {
  el.addEventListener('mousemove', function (e) {
    tip.innerHTML = html;
    tip.style.opacity = 1;
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(e.clientX + 14, window.innerWidth - r.width - 8) + 'px';
    tip.style.top = Math.max(e.clientY - r.height - 12, 8) + 'px';
  });
  el.addEventListener('mouseleave', function () { tip.style.opacity = 0; });
}

/* --- 히어로 --- */
document.getElementById('heroFig').textContent = DATA.hero.figure;
document.getElementById('heroLead').textContent = DATA.hero.lead;
document.getElementById('heroSub').textContent = DATA.hero.sub;

/* --- 범례 --- */
document.getElementById('legend').innerHTML = DATA.series.map(function (s) {
  return '<span><i style="background:var(--s-' + s.key + ')"></i>' + esc(s.label)
    + ' · 가중 ' + s.weight.toFixed(2) + '</span>';
}).join('');

/* --- 차트 1: 종합 점수(누적) --- */
function renderScore() {
  const host = document.getElementById('scoreChart');
  const max = DATA.scoreAxisMax;
  DATA.rows.forEach(function (r, i) {
    const lead = (i === 0 || i === DATA.rows.length - 1) ? ' lead' : '';
    const name = document.createElement('div');
    name.className = 'name' + lead;
    name.textContent = r.name;

    const track = document.createElement('div');
    track.className = 'track';
    const fill = document.createElement('div');
    fill.className = 'fill';
    fill.style.width = (100 * r.score / max) + '%';
    /* 기여도 0 인 신호(예: 야간광 임계 미만)는 세그먼트를 만들지 않는다 —
       폭 0 짜리가 마지막에 끼면 둥근 데이터 끝이 그쪽으로 가 버린다. */
    fill.innerHTML = DATA.series.filter(function (s) { return r.parts[s.key] > 0; })
      .map(function (s) {
        return '<div class="seg" style="width:'
          + (100 * r.parts[s.key] / r.score)
          + '%;background:var(--s-' + s.key + ')"></div>';
      }).join('');
    track.appendChild(fill);

    const val = document.createElement('div');
    val.className = 'val' + lead;
    val.textContent = r.score.toFixed(3);

    bindTip(track, '<b>' + esc(r.name) + '</b>'
      + '종합 ' + r.score.toFixed(3) + ' · ' + esc(r.cap) + '<br>'
      + DATA.series.map(function (s) {
          return esc(s.label) + ' ' + r.parts[s.key].toFixed(3);
        }).join('<br>'));

    host.append(name, track, val);
  });
  const axis = document.createElement('div');
  axis.className = 'axis';
  axis.innerHTML = '<span>0</span><span>' + (max / 2).toFixed(2)
    + '</span><span>' + max.toFixed(2) + '</span>';
  host.appendChild(axis);
}

/* --- 차트 2: 1km 안 가로등 수(단일 계열) --- */
function renderLamps() {
  const host = document.getElementById('lampChart');
  const max = DATA.lampAxisMax;
  DATA.rows.forEach(function (r) {
    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = r.name;

    const track = document.createElement('div');
    track.className = 'track';
    if (r.lampFar > 0) {
      const fill = document.createElement('div');
      fill.className = 'fill single';
      fill.style.width = (100 * r.lampFar / max) + '%';
      fill.style.background = 'var(--s-lamp)';
      track.appendChild(fill);
    }

    const val = document.createElement('div');
    val.className = 'val';
    val.textContent = r.lampFar.toLocaleString();

    bindTip(track, '<b>' + esc(r.name) + '</b>'
      + '1km 안 ' + r.lampFar.toLocaleString() + '개 · 100m 안 ' + r.lampNear + '개<br>'
      + '최근접 '
      + (r.nearestM === null ? '1km 안에 없음' : r.nearestM.toFixed(0) + ' m'));

    host.append(name, track, val);
  });
  const axis = document.createElement('div');
  axis.className = 'axis';
  axis.innerHTML = '<span>0</span><span>' + Math.round(max / 2).toLocaleString()
    + '</span><span>' + max.toLocaleString() + '개</span>';
  host.appendChild(axis);
}

/* --- 표 --- */
function renderTable() {
  const milky = { visible: '보임', degraded: '흐릿', lost: '어려움' };
  const head = ['관측지', '지역', 'SQM', 'Falchi', 'Bortle', '은하수',
                '최근접 등(m)', '100m', '1km', 'VIIRS 1km', '종합', '상한'];
  document.getElementById('table').innerHTML =
    '<thead><tr>' + head.map(function (h) { return '<th>' + h + '</th>'; }).join('')
    + '</tr></thead><tbody>' + DATA.rows.map(function (r) {
      return '<tr>' + [
        esc(r.name), esc(r.region), r.sqm.toFixed(2), r.falchi, r.bortle,
        milky[r.milkyWay] || '—',
        r.nearestM === null ? '1km+' : r.nearestM.toFixed(0),
        r.lampNear, r.lampFar, r.viirsNear.toFixed(2),
        r.score.toFixed(3), esc(r.cap)
      ].map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>';
    }).join('') + '</tbody>';
}

document.getElementById('footer').innerHTML = DATA.footer;
renderScore(); renderLamps(); renderTable();
</script>
"""


def _footer() -> str:
    """가중치·경계가 운영값이라는 사실과 데이터 귀속을 화면에 그대로 남긴다."""
    weights = (
        f"SQM {darkness.W_SQM:.2f} · 가로등 {darkness.W_LAMP:.2f} · "
        f"VIIRS {darkness.W_NIGHTLIGHT:.2f}"
    )
    caps = (
        f"{darkness.SCORE_GOOD_CAP:g} (관측지급) · "
        f"{darkness.SCORE_LIMITED_CAP:g} (은하수 소실급)"
    )
    lines = [
        f"<b>가중치(운영값)</b> {weights} — 문헌값이 아니다. 근거·검산은 "
        f"<code>docs/decisions.md</code> §1.8.",
        f"<b>등급 상한 경계(운영값)</b> {caps}. "
        "점수는 등급을 낮추기만 하고 올리지 않는다.",
        f"<b>집계 반경</b> 가로등 {lamps.NEAR_M:g}m·{lamps.FAR_M / 1000:g}km · "
        f"VIIRS {nightlight.NEAR_KM:g}km "
        f"(노이즈 임계 {nightlight.NOISE_FLOOR:g} 미만은 0).",
        "",
        html.escape(darkness.SOURCE),
        html.escape(nightlight.SOURCE),
        html.escape(lamps.SOURCE),
        "관측지 좌표는 큐레이션 추정치를 포함한다 — 신뢰도는 "
        "<code>data/jeju_spots.json</code> 의 <code>coord_confidence</code> 참조.",
    ]
    return "<br>".join(lines)


def _topic(word: str) -> str:
    """'은/는' 을 받침 유무로 고른다.

    관측지 이름은 '우도(우도봉 일대)'처럼 괄호로 끝나기도 해서 맨 끝 글자가 아니라
    **마지막 한글 음절**을 본다. 한글이 하나도 없으면 병기형으로 피한다.
    """
    for ch in reversed(word):
        if "가" <= ch <= "힣":
            return "은" if (ord(ch) - 0xAC00) % 28 else "는"
    return "은(는)"


def _hero(rows: list[dict]) -> dict:
    """가장 큰 한 숫자 — '등급만으로는 안 갈린다'는 이 리포트의 논점."""
    top_grade, count = max(
        ((g, sum(1 for r in rows if r["falchi"] == g)) for g in darkness.FALCHI_GRADES),
        key=lambda pair: pair[1],
    )
    # 대비는 **같은 등급 안에서** 잡는다. 등급이 다른 곳끼리 비교하면
    # "등급만으로는 안 갈린다"는 논점이 성립하지 않는다. 또 문장이 말하는 것이
    # 가로등 수이므로, 비교 상대도 점수 순위가 아니라 **가로등 수**로 고른다.
    same = [r for r in rows if r["falchi"] == top_grade]
    fewest = min(same, key=lambda r: r["lampFar"])
    most = max(same, key=lambda r: r["lampFar"])
    return {
        "figure": f"{count} / {len(rows)}",
        "lead": f"관측지 {len(rows)}곳 중 {count}곳이 똑같은 Falchi {top_grade} 등급",
        "sub": (
            f"하늘밝기(SQM)만 보면 이 {count}곳은 거의 구분되지 않는다. "
            f"그런데 같은 등급 안에서 {fewest['name']}{_topic(fewest['name'])} "
            f"1km 안 가로등이 {fewest['lampFar']}개, "
            f"{most['name']}{_topic(most['name'])} {most['lampFar']}개다 "
            "— 신호를 셋 쓰는 이유다."
        ),
    }


def main() -> None:
    rows = _rows()
    payload = {
        "rows": rows,
        "series": [
            {"key": s["key"], "label": s["label"], "weight": w}
            for s, w in zip(
                _SERIES,
                (darkness.W_SQM, darkness.W_LAMP, darkness.W_NIGHTLIGHT),
                strict=True,
            )
        ],
        "hero": _hero(rows),
        # 축 상한은 눈금이 깔끔하게 떨어지는 값으로 올림한다(0.1 배수는 부동소수
        # 찌꺼기가 남아 눈금 문자열에 새므로 자릿수를 잘라 둔다).
        "scoreAxisMax": round(
            max(0.1 * (int(max(r["score"] for r in rows) / 0.1) + 1), 0.1), 2
        ),
        "lampAxisMax": max(100 * (int(max(r["lampFar"] for r in rows) / 100) + 1), 100),
        "footer": _footer(),
    }

    path.OUTPUTS.mkdir(parents=True, exist_ok=True)
    path.SPOT_REPORT.write_text(
        _HTML.replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8",
    )

    print(f"관측지 {len(rows)}곳 (종합 점수 오름차순)")
    header = f"{'관측지':<22}{'SQM':>7}{'Falchi':>8}"
    print(header + f"{'최근접m':>9}{'1km등':>7}{'종합':>8}  상한")
    for r in rows:
        nearest = "1km+" if r["nearestM"] is None else f"{r['nearestM']:.0f}"
        print(f"{r['name']:<22}{r['sqm']:>7.2f}{r['falchi']:>8}{nearest:>9}"
              f"{r['lampFar']:>7}{r['score']:>8.3f}  {r['cap']}")
    print(f"저장: {path.SPOT_REPORT.relative_to(path.ROOT)} "
          f"({path.SPOT_REPORT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
