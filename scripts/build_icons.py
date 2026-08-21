"""마커 아이콘 굽기 — `icon/` 의 원본 그림을 지도에 얹을 크기로 줄여 `data/icon/` 에.

원본은 1500px 안팎에 셋이 합쳐 3.4MB 다. 지도는 이것을 28px 로 그리고, 게다가 그림을
**HTML 안에 박아 넣는다**(`modules/maps.py`) — 지도 한 장이 서버 없이 열려야 하기
때문이다. 원본을 그대로 박으면 지도 파일 하나가 4.5MB 가 되고, 정작 화면에 쓰이는
것은 그 중 0.03% 다.

두 배로 굽는다(28px 를 56px 로). 고해상도 화면에서 등배로 넣으면 가장자리가 뭉갠다.

흰 테두리도 여기서 굽는다
--------------------------------------------------------------------------
위성사진 위에서는 밝은 그림이 밝은 자리에, 어두운 그림이 어두운 자리에 묻힌다.
실루엣을 따라가는 흰 테두리가 어느 배경에서도 그림을 떼어 놓는다. CSS 그림자를 여러
겹 쌓아 흉내 낼 수도 있지만 그건 마커마다 매번 다시 그려지는 일이고, 한 번 계산해
파일에 넣어 두면 그만인 것이다. 테두리가 잘리지 않게 `PAD` 만큼 여백을 두고 그린다.

어디가 '그 자리'인가도 여기서 잰다
--------------------------------------------------------------------------
물방울 모양 표지(주차)는 **뾰족한 끝**이 좌표다. 가운데를 자리로 잡으면 주차 지점을
그림 절반만큼 위로 옮겨 알려 주는 셈이 된다. 그 끝이 그림 어디인지는 그림마다 다르고
여백·테두리를 두면 또 달라지므로, 짐작하지 않고 알파에서 직접 재어 `anchor.json` 에
적는다. 그림을 갈아 끼워도 다시 굽기만 하면 맞는다.

    python scripts/build_icons.py

`icon/` 의 그림을 바꿨을 때만 다시 돌리면 된다. 결과는 커밋한다 — 실행에 필요한 것이고
빌드 도구(numpy·zlib 말고는 아무것도 안 쓴다)를 배포본이 갖고 있을 이유가 없다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _png  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: 구워 내는 한 변(px). 화면에는 이 절반 크기로 그린다.
SIDE = 56
#: 테두리가 캔버스 밖으로 잘리지 않게 남기는 여백.
PAD = 5
#: 테두리 두께.
RING = 3.0

#: 원본 파일 → 마커 갈래(`mapview._KINDS` 의 열쇠). 이름이 다르므로 여기서 잇는다.
ICONS = {
    "star": "spot",
    "parking": "parking",
    "bathroom": "toilet",
}

#: 물방울 모양이라 **아래 끝이 그 자리**인 그림. 나머지는 한가운데가 그 자리다.
PINS = {"parking"}


def main() -> None:
    out_dir = ROOT / "data" / "icon"
    out_dir.mkdir(parents=True, exist_ok=True)
    anchors: dict[str, list[float]] = {}

    for name, kind in ICONS.items():
        src = ROOT / "icon" / f"{name}.png"
        art = _png.pad(_png.fit(_png.trim(_png.read(str(src))), SIDE - 2 * PAD), SIDE)
        # 자리는 **테두리를 두르기 전** 그림에서 잰다. 테두리는 그림 둘레의 후광이지
        # 그림이 아니다 — 그것까지 넣으면 뾰족한 끝이 실제보다 아래로 내려간다.
        anchors[kind] = list(_png.tip(art)) if kind in PINS else [0.5, 0.5]
        dst = out_dir / f"{kind}.png"
        n = _png.write(str(dst), _png.outline(art, RING))
        ax, ay = anchors[kind]
        print(f"{src.name:14s} {src.stat().st_size:>9,}B  →  {dst.name:12s} "
              f"{n:>7,}B  자리 ({ax:.3f}, {ay:.3f})")

    (out_dir / "anchor.json").write_text(
        json.dumps(anchors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"자리표 → {out_dir / 'anchor.json'}")


if __name__ == "__main__":
    main()
