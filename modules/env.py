"""`.env` 에서 키 하나 읽기 — 서버·배치가 함께 쓴다.

python-dotenv 를 끌어오지 않는다. 배포 의존을 이 열 줄 때문에 늘리지 않는 것이
`build_viirs_grid.py` 가 tifffile 을 scripts 그룹에만 두는 것과 같은 규율이다.

환경변수가 먼저다 — 컨테이너·CI·셸에서 넘긴 값이 파일보다 우선한다. 컨테이너에는
`.env` 를 넣지 않으므로(비밀은 이미지에 굽지 않는다) 거기서는 환경변수만 쓰인다.
"""

from __future__ import annotations

import os

from modules import path


def read(name: str) -> str:
    """환경변수 또는 저장소 루트 `.env` 에서 값을 읽는다. 없으면 빈 문자열."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_file = path.ROOT / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, raw = line.partition("=")
        if sep and key.strip() == name:
            return raw.strip().strip("\"'")
    return ""
