"""`data/` 의 CSV 를 UTF-8 로 통일한다 (배치, 다시 돌려도 안전).

공공데이터포털은 같은 표준데이터도 기관마다 다른 인코딩으로 내려준다 — 제주시
가로등은 UTF-8(BOM), 서귀포시 가로등은 CP949 다. 그 상태로 두면 파일을 여는 쪽마다
인코딩을 알아야 하고(`core.lamps` 는 파일별 인코딩 표를 들고 있었다), 편집기·엑셀로
그냥 열면 글자가 깨져 **원본을 눈으로 확인할 수 없다**. 데이터를 사람이 못 읽으면
"이 값이 왜 이런가"를 파일에서 되짚을 수 없다.

그래서 저장소 안의 CSV 는 한 가지 규약으로 맞춘다.

    UTF-8 (BOM) · 파일 이름은 ASCII 만

BOM 을 붙이는 것은 엑셀이 UTF-8 을 알아보게 하기 위해서다(`fetch_kakao_places.py`
가 쓰는 것과 같은 규약). 이미 UTF-8 인 파일은 손대지 않는다 — BOM 하나 붙이자고
375MB 짜리 토지대장을 다시 쓰지 않는다.

파일 이름도 고친다
--------------------------------------------------------------------------
`jeju_speed_​bumps.csv` 처럼 **눈에 보이지 않는 문자**(제로폭 공백 등)가 이름에
섞여 들어오는 일이 있다 — 포털에서 복사해 붙일 때 딸려 온다. 셸에서 탭 완성으로는
치지지 않고, 코드에 적어 둔 경로와도 안 맞는데 화면으로는 똑같아 보여서 원인을
찾는 데 오래 걸린다. 그래서 이름에서 제로폭 문자를 떼어 낸다.

변환은 **바이트 통째로 다시 인코딩**하는 것뿐이다 — CSV 로 파싱하지 않는다.
따옴표·줄바꿈·빈 칸이 원본 그대로 남아야 "복구했더니 값이 달라졌다"가 없다.

실행:
    uv run python -m scripts.normalize_csv          # 무엇을 고칠지 보기만 한다
    uv run python -m scripts.normalize_csv --write  # 실제로 고친다
"""

from __future__ import annotations

import sys
from pathlib import Path

from server import path

#: 이 순서로 디코딩을 시도한다. 첫 번째로 성공한 것이 그 파일의 인코딩이다.
#: 한국 공공데이터에 실제로 나오는 두 가지뿐이라 추측(chardet)을 끌어오지 않는다 —
#: 둘 다 실패하면 **모르는 것**이고, 모르는 채로 다시 쓰는 것이 진짜 파괴다.
_ENCODINGS = ("utf-8", "cp949")

#: 저장 규약. BOM 은 엑셀이 UTF-8 을 알아보게 하는 표식이다.
_TARGET = "utf-8-sig"

#: 파일 이름에서 떼어 낼 보이지 않는 문자 — 제로폭 공백·비접합자·접합자·BOM.
_INVISIBLE = "​‌‍﻿"


def sniff(data: bytes) -> str | None:
    """바이트를 읽을 수 있는 인코딩. 아무것도 안 맞으면 None."""
    for encoding in _ENCODINGS:
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return None


def clean_name(name: str) -> str:
    """파일 이름에서 보이지 않는 문자를 뗀다."""
    return "".join(ch for ch in name if ch not in _INVISIBLE)


def _invisible_note(name: str) -> str:
    """이름에 섞인 보이지 않는 문자를 **코드포인트로** 적는다.

    화면에 그대로 찍으면 아무것도 안 보여서 "왜 개명한다는 거지"가 된다. 게다가
    윈도우 콘솔(CP949)은 이 문자를 못 찍어 출력 자체가 죽는다.
    """
    codes = sorted({f"U+{ord(ch):04X}" for ch in name if ch in _INVISIBLE})
    return f"이름에 보이지 않는 문자 {'·'.join(codes)}"


def plan(csv_path: Path) -> tuple[str, str]:
    """(할 일, 사유). 할 일은 'skip' · 'rename' · 'convert' · 'fail'."""
    data = csv_path.read_bytes()
    encoding = sniff(data)
    notes = []
    if clean_name(csv_path.name) != csv_path.name:
        notes.append(_invisible_note(csv_path.name))

    if encoding is None:
        return "fail", f"{'·'.join(_ENCODINGS)} 어느 쪽으로도 읽히지 않는다"
    if encoding == "utf-8":
        bom = " (BOM)" if data.startswith(b"\xef\xbb\xbf") else ""
        notes.insert(0, f"이미 UTF-8{bom}")
        return ("rename" if len(notes) > 1 else "skip"), " · ".join(notes)
    notes.insert(0, f"{encoding} → UTF-8 (BOM)")
    return "convert", " · ".join(notes)


def apply(csv_path: Path, action: str) -> None:
    """변환·개명을 실제로 수행한다.

    쓰기는 **임시 파일에 쓴 뒤 바꿔치기**한다. 중간에 끊겨도 반쪽짜리 CSV 가 원래
    자리에 남지 않게 — 원본이 곧 유일본인 데이터라 되돌릴 곳이 없다.
    """
    if action == "convert":
        data = csv_path.read_bytes()
        tmp = csv_path.with_suffix(".csv.tmp")
        tmp.write_bytes(data.decode(sniff(data)).encode(_TARGET))
        tmp.replace(csv_path)

    cleaned = csv_path.with_name(clean_name(csv_path.name))
    if cleaned != csv_path:
        csv_path.rename(cleaned)


def main() -> None:
    write = "--write" in sys.argv[1:]
    files = sorted(path.DATA.rglob("*.csv"))
    if not files:
        raise SystemExit(f"{path.DATA} 안에 CSV 가 없습니다.")

    changed = failed = 0
    for csv_path in files:
        action, why = plan(csv_path)
        # 화면에 찍는 경로는 **고친 이름**이다 — 보이지 않는 문자를 그대로 내보내면
        # 윈도우 콘솔(CP949)이 못 찍고 죽는다. 그 문자는 사유 쪽에 코드포인트로 적힌다.
        rel = csv_path.relative_to(path.ROOT).with_name(clean_name(csv_path.name))
        size = csv_path.stat().st_size / 1024

        if action == "skip":
            print(f"  그대로  {rel}  ({size:,.0f} KB · {why})")
            continue
        if action == "fail":
            failed += 1
            print(f"  ✗ 실패  {rel}  — {why}")
            continue

        changed += 1
        label = "변환" if action == "convert" else "개명"
        if not write:
            print(f"  [예정] {label}  {rel}  ({size:,.0f} KB · {why})")
            continue
        apply(csv_path, action)
        print(f"  {label}  {rel}  ({size:,.0f} KB · {why})")

    print()
    if failed:
        print(f"읽지 못한 파일 {failed}개 — 원본을 다시 받아야 합니다.")
    if not changed:
        print(f"CSV {len(files)}개 전부 UTF-8 입니다. 고칠 것이 없습니다.")
    elif write:
        print(f"CSV {len(files)}개 중 {changed}개를 고쳤습니다.")
    else:
        print(
            f"CSV {len(files)}개 중 {changed}개를 고쳐야 합니다. "
            "실제로 고치려면 --write 를 붙이세요."
        )


if __name__ == "__main__":
    main()
