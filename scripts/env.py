"""`.env` 읽기 — 서버와 같은 구현을 쓴다.

예전에는 여기에 같은 열 줄이 따로 있었다. 두 벌이면 언젠가 한쪽만 고쳐져,
스크립트는 키를 찾는데 서버는 못 찾는 식으로 갈린다. `server/env.py` 하나만 둔다.
"""

from __future__ import annotations

from server.env import read

__all__ = ["read"]
