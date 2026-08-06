"""`.env` 에서 키 하나 읽기 — 배치 스크립트 전용.

python-dotenv 를 끌어오지 않는다. 배포 의존을 이 열 줄 때문에 늘리지 않는 것이
`build_viirs_grid.py` 가 tifffile 을 scripts 그룹에만 두는 것과 같은 규율이다.

환경변수가 먼저다 — CI·셸에서 넘긴 값이 파일보다 우선한다.
"""

from __future__ import annotations

import os

from server import path


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


def require(name: str, hint: str = "") -> str:
    """값이 없으면 `SystemExit` — 스크립트가 절반쯤 돌다 실패하지 않게 앞에서 막는다."""
    value = read(name)
    if not value:
        tail = f"\n  {hint}" if hint else ""
        raise SystemExit(f"{name} 가 없습니다(.env 또는 환경변수).{tail}")
    return value
