"""별자리 데이터 생성 — Stellarium(구성) + Hipparcos(좌표·등급)를 합친다.

    실행: uv run python -m scripts.build_constellations
    산출: data/constellations/constellations.json

왜 두 출처인가
--------------------------------------------------------------------------
"오리온자리를 보려면 어디를 봐야 하나"에 답하려면 두 가지가 있어야 한다.

    **어떤 별들이 그 별자리를 이루는가**  →  Stellarium `modern_iau` 스카이컬처
    **그 별들이 하늘 어디에 있는가**      →  Hipparcos 성표(ESA 1997)
    **한국어로 뭐라 부르는가**            →  Stellarium 한국어 번역(ko.po)

앞의 것은 사람이 정한 것(전통적 선 잇기)이라 계산으로 유도되지 않고, 뒤의 것은
관측값이라 사람이 정할 수 없다. 그래서 나눠 받아 HIP 번호로 잇는다.

**IAU 경계 중심을 쓰지 않는 이유.** 별자리의 '중심'은 경계 다각형의 무게중심이라
별이 없는 빈 하늘일 수 있다(큰 별자리일수록 그렇다). 사용자가 실제로 찾는 것은 눈에
보이는 별 무리이므로 **밝은 별들의 위치**로 방향을 답한다.

에포크 — 고유운동을 무시한다
--------------------------------------------------------------------------
Hipparcos 위치는 ICRS(J2000 정렬), 에포크 J1991.25 다. 밝은 별의 고유운동은 대개 100년에
수 초각이라, 방위를 도(度) 단위로 말하는 이 용도에서는 무시해도 눈금이 바뀌지 않는다.
세차·광행차는 skyfield 가 관측 시각마다 처리한다.

출처·라이선스 (산출 파일의 `meta` 에도 박아 둔다)
--------------------------------------------------------------------------
- 별자리 구성: Stellarium `modern_iau` 스카이컬처 — CC BY-SA 4.0, Stellarium's team.
- 별 좌표·등급: Hipparcos Catalogue (ESA 1997), CDS/VizieR I/239.
- 한국어 이름: Stellarium 한국어 번역(`po/stellarium-skycultures/ko.po`), 같은 라이선스.

한국어 이름은 **손질해서 쓴다**(`_korean`). 번역이 "천칭자리"처럼 '자리'까지 옮긴 것과
"독수리"처럼 빼고 옮긴 것이 섞여 있어(88개 중 13개만 붙어 있다) 그대로 쓰면 목록이
들쭉날쭉해진다. 규칙은 하나 — 끝이 '자리'가 아니면 붙인다. 번역이 비어 있는 셋은
표준 표기로 채운다(`_KO_MISSING`).

재현 가능하게 **받아서 만든다**. 원본을 저장소에 넣지 않는 것은 표고 격자와 같은
규율이고, 런타임에는 이 스크립트가 만든 정적 파일만 읽는다(서버는 네트워크로 성표를
받지 않는다).
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request

from server import path

# Windows 콘솔(cp949)에서 한글·기호가 깨지지 않도록 UTF-8로 출력한다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# --- 출처 --------------------------------------------------------------------

STELLARIUM_URL = (
    "https://raw.githubusercontent.com/Stellarium/stellarium/master"
    "/skycultures/modern_iau/index.json"
)
STELLARIUM_CREDIT = (
    "별자리 구성: Stellarium modern_iau 스카이컬처 (CC BY-SA 4.0, Stellarium's team)"
)

HIPPARCOS_URL = "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat"
HIPPARCOS_CREDIT = "별 좌표·등급: Hipparcos Catalogue (ESA 1997) via CDS/VizieR I/239"

KO_PO_URL = (
    "https://raw.githubusercontent.com/Stellarium/stellarium/master"
    "/po/stellarium-skycultures/ko.po"
)
KO_CREDIT = "별자리 한국어 이름: Stellarium 한국어 번역 (CC BY-SA 4.0)"

#: 한국어 번역이 비어 있는 별자리. 셋 다 국내에서 굳어진 표기이고, 특히 Hydra(바다뱀)와
#: Hydrus(물뱀)는 영문명이 둘 다 "Water Snake" 계열이라 번역을 그대로 두면 구별이
#: 사라진다. 고래자리는 한국천문연구원이 가을철 별자리로 같은 이름을 쓴다.
_KO_MISSING = {
    "Cet": "고래자리",
    "Hya": "바다뱀자리",
    "Hyi": "물뱀자리",
}

#: 별자리 이름의 우리말 꼬리.
_SUFFIX = "자리"

#: `hip_main.dat` 의 고정폭 자리(0-기준 슬라이스). CDS ReadMe(I/239) 의 바이트 정의를
#: 그대로 옮긴 것이다 — H1 HIP(9-14) · H5 Vmag(42-46) ·
#: H8 RAdeg(52-63) · H9 DEdeg(65-76).
_COL_HIP = slice(8, 14)
_COL_VMAG = slice(41, 46)
_COL_RA = slice(51, 63)
_COL_DE = slice(64, 76)

#: 파싱이 어긋나지 않았는지 확인하는 붙박이 별들. 값은 Hipparcos 자체의 것이라
#: 컬럼이 한 칸만 밀려도 여기서 바로 드러난다(조용히 틀린 성표를 쓰지 않게).
_CHECKS = {
    32349: ("시리우스", -1.44, 101.28, -16.71),
    27989: ("베텔게우스", 0.45, 88.79, 7.41),
    91262: ("직녀(베가)", 0.03, 279.23, 38.78),
}


def _fetch(url: str, cache_name: str | None = None) -> bytes:
    """URL 을 받는다. cache_name 을 주면 받은 것을 캐시에 두고 다음부터 그것을 쓴다.

    성표(hip_main.dat)가 53MB 라 다시 만들 때마다 받으면 몇 분이 든다. 캐시는
    `.cache/` 아래이므로 저장소에 남지 않는다(예보 캐시와 같은 자리).
    """
    cached = None if cache_name is None else path.CACHE_DIR / cache_name
    if cached is not None and cached.exists():
        print(f"  캐시에서 읽음 … {cached.name} ({cached.stat().st_size / 1e6:.0f} MB)")
        return cached.read_bytes()

    print(f"  받는 중 … {url}")
    with urllib.request.urlopen(url, timeout=180) as r:
        data = r.read()
    if cached is not None:
        path.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return data


def load_stellarium() -> dict[str, dict]:
    """별자리 약자 → {라틴명, 영문명, HIP 번호 목록}."""
    doc = json.loads(_fetch(STELLARIUM_URL).decode("utf-8"))
    out: dict[str, dict] = {}
    for c in doc.get("constellations", []):
        # id 는 "CON modern_iau Ori" 꼴이다. 마지막 토막이 IAU 세 글자 약자.
        abbr = c["id"].split()[-1]
        hips: list[int] = []
        for seg in c.get("lines", []):
            for hip in seg:
                if isinstance(hip, int) and hip not in hips:
                    hips.append(hip)
        name = c.get("common_name", {})
        out[abbr] = {
            "latin": name.get("native") or name.get("english") or abbr,
            "english": name.get("english") or "",
            "hips": hips,
        }
    return out


def load_korean() -> dict[str, str]:
    """Stellarium 한국어 번역에서 IAU 별자리 이름만 뽑는다(영문명 → 한국어)."""
    po = _fetch(KO_PO_URL, "stellarium-ko.po").decode("utf-8")
    # gettext 블록 하나가 세 줄이다 — 문맥(IAU 별자리 이름) · 원문 · 번역.
    # 문맥을 함께 걸어야 같은 낱말의 다른 쓰임(별 이름·심원천체)이 섞이지 않는다.
    pattern = (
        r'msgctxt "IAU constellation name"\n'
        r'msgid "([^"]+)"\n'
        r'msgstr "([^"]*)"'
    )
    pairs = re.findall(pattern, po)
    return {en: ko for en, ko in pairs if ko.strip()}


def _korean(abbr: str, latin: str, english: str, table: dict[str, str]) -> str:
    """별자리 하나의 한국어 이름. 없으면 표준 표기로 채우고, 꼬리를 맞춘다."""
    ko = table.get(english) or table.get(latin) or _KO_MISSING.get(abbr, "")
    if not ko:
        return ""
    return ko if ko.endswith(_SUFFIX) else ko + _SUFFIX


def load_hipparcos(wanted: set[int]) -> dict[int, dict]:
    """필요한 HIP 번호만 골라 {HIP: {ra_deg, dec_deg, vmag}}."""
    raw = _fetch(HIPPARCOS_URL, "hip_main.dat").decode("latin-1")
    stars: dict[int, dict] = {}
    for line in raw.splitlines():
        try:
            hip = int(line[_COL_HIP])
        except ValueError:
            continue
        if hip not in wanted:
            continue
        try:
            ra = float(line[_COL_RA])
            dec = float(line[_COL_DE])
        except ValueError:
            continue  # 위치가 없는 항목은 별자리를 가리키는 데 쓸 수 없다
        try:
            vmag = float(line[_COL_VMAG])
        except ValueError:
            vmag = None
        stars[hip] = {
            "ra_deg": round(ra, 5),
            "dec_deg": round(dec, 5),
            "vmag": None if vmag is None else round(vmag, 2),
        }
    return stars


def verify(stars: dict[int, dict]) -> None:
    """붙박이 별로 컬럼 파싱을 확인한다. 어긋나면 만들지 않고 멈춘다."""
    for hip, (name, vmag, ra, dec) in _CHECKS.items():
        got = stars.get(hip)
        if got is None:
            raise SystemExit(f"검증 실패: HIP {hip}({name})을 성표에서 못 찾았습니다")
        if (
            abs(got["ra_deg"] - ra) > 0.05
            or abs(got["dec_deg"] - dec) > 0.05
            or abs((got["vmag"] or 99) - vmag) > 0.05
        ):
            raise SystemExit(
                f"검증 실패: HIP {hip}({name}) 값이 어긋납니다 — "
                f"기대 V={vmag} ({ra}, {dec}), 받음 {got}"
            )
    print(f"  검증 통과 — 붙박이 {len(_CHECKS)}개 일치")


def main() -> None:
    print("별자리 데이터를 만듭니다.")
    consts = load_stellarium()
    print(f"  별자리 {len(consts)}개")

    wanted = {h for c in consts.values() for h in c["hips"]}
    print(f"  필요한 별 {len(wanted)}개")

    korean = load_korean()
    print(f"  한국어 번역 {len(korean)}개")

    stars = load_hipparcos(wanted)
    print(f"  성표에서 찾은 별 {len(stars)}개")
    missing = sorted(wanted - set(stars))
    if missing:
        # 못 찾은 별은 버리지 않고 **밝힌다**. 조용히 빠지면 그 별자리의 선이 한 칸
        # 짧아진 채로 방위를 답하게 된다.
        print(f"  성표에 없는 HIP {len(missing)}개: {missing}")
    verify(stars)

    out = {
        "meta": {
            "sources": [STELLARIUM_CREDIT, HIPPARCOS_CREDIT, KO_CREDIT],
            "epoch": "ICRS (J2000 정렬), Hipparcos 에포크 J1991.25 — 고유운동 미보정",
            "built_by": "scripts/build_constellations.py",
        },
        "constellations": [
            {
                "abbr": abbr,
                "latin": c["latin"],
                "english": c["english"],
                "korean": _korean(abbr, c["latin"], c["english"], korean),
                "stars": [
                    {"hip": h, **stars[h]} for h in c["hips"] if h in stars
                ],
            }
            for abbr, c in sorted(consts.items())
        ],
    }

    path.CONSTELLATIONS.parent.mkdir(parents=True, exist_ok=True)
    with open(path.CONSTELLATIONS, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    nameless = [c["abbr"] for c in out["constellations"] if not c["korean"]]
    if nameless:
        # 이름 없는 별자리는 **밝힌다**. 조용히 비면 응답에 라틴명이 그대로 나가
        # 한국어 답 안에 "Camelopardalis" 가 섞인다.
        print(f"  한국어 이름이 없는 별자리 {len(nameless)}개: {nameless}")

    size = path.CONSTELLATIONS.stat().st_size / 1024
    total = sum(len(c["stars"]) for c in out["constellations"])
    print(
        f"완료 — {path.CONSTELLATIONS.relative_to(path.ROOT)} "
        f"({size:.0f} KB · 별자리 {len(out['constellations'])}개 · 별 {total}개)"
    )


if __name__ == "__main__":
    main()
