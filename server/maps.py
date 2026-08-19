"""지도 파일 만들기와 그 주소 — `core` 밖의 I/O 한 겹.

`core/mapview.py` 가 HTML **문자열**까지 만들고, 이 모듈이 그것을 파일로 떨어뜨려
브라우저가 열 수 있는 주소로 바꾼다. 둘을 가른 이유는 `core` 가 I/O 를 하지 않는다는
규율 때문이고, 덕분에 렌더링은 파일 없이 테스트된다.

세션 상태를 만들지 않는다 (`decisions.md` §2.15)
--------------------------------------------------------------------------
파일 이름은 **내용의 해시**다. 같은 질의는 같은 파일로 떨어지므로 요청마다 새 파일이
쌓이지 않고, 서버가 "누가 뭘 봤는지"를 기억할 필요도 없다. stateless 방침 그대로다.

주소는 어디를 가리키나
--------------------------------------------------------------------------
서버가 자기 포트로 직접 서빙한다(`server/app.py` 의 `/maps/{name}`). 컨테이너에서
`MCP_HOST=0.0.0.0` 으로 뜨더라도 **0.0.0.0 은 브라우저가 열 수 있는 주소가 아니므로**
겉으로 내보내는 주소는 따로 정한다 — `MAP_BASE_URL` 환경변수, 없으면 루프백.
"""

from __future__ import annotations

import hashlib
import os
import re

from server import env, path
from server.core.mapview import (
    DEFAULT_SATELLITE,
    Item,
    Marker,
    Tiles,
    render,
)

#: 지도 파일이 쌓이는 자리. `outputs/` 아래라 커밋되지 않는다.
MAPS_DIR = path.OUTPUTS / "maps"

#: 파일 이름으로 허용하는 모양. 서빙 라우트가 이걸로 검사해 경로 탈출을 막는다.
NAME_RE = re.compile(r"^[0-9a-f]{16}\.html$")


def base_url() -> str:
    """지도 주소의 앞부분. 실행 환경이 정한다.

    `MAP_BASE_URL` 이 우선이다 — 컨테이너·원격에서는 서버가 바인딩한 주소와 사용자가
    열 수 있는 주소가 다르기 때문이다(0.0.0.0 을 브라우저에 줄 수는 없다).
    """
    explicit = os.getenv("MAP_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    return f"http://127.0.0.1:{os.getenv('MCP_PORT', '8000')}"


def satellite() -> Tiles:
    """배경 위성 타일 — VWorld 키가 있으면 그것을, 없으면 기본 공급자를.

    VWorld(국토지리정보원 항공사진)는 제주 **z19 까지 실사진**이다 — 네 지점에서
    z19 네 장의 해시가 모두 달랐다(같으면 '자료 없음' 타일이다). 기본 공급자는 대부분
    z18 까지라, 키가 있으면 주차 구획과 탐방로가 눈에 띄게 선명해진다.

    **키는 지도 HTML 에 그대로 실린다.** 클라이언트가 직접 타일을 받는 방식이라
    피할 수 없다(카카오 JS 키와 같은 성격). 그래서 지도를 여는 사람에게는 키가 보인다 —
    VWorld 콘솔에서 도메인을 등록해 접근을 제한하는 것이 실질적인 통제다.

    `MAP_TILE_URL` 을 주면 그것이 최우선이다. 공급자를 바꿔 볼 때 코드를 안 고치려는
    구멍이고, `{z}`·`{x}`·`{y}` 자리표시자를 그대로 두면 된다.
    """
    explicit = env.read("MAP_TILE_URL")
    if explicit:
        return Tiles(
            url=explicit,
            attribution=env.read("MAP_TILE_CREDIT") or "위성사진 제공: 설정된 공급자",
            max_native_zoom=int(env.read("MAP_TILE_MAX_ZOOM") or 19),
        )

    key = env.read("VWORLD_API_KEY")
    if key:
        return Tiles(
            url=f"https://api.vworld.kr/req/wmts/1.0.0/{key}/Satellite/{{z}}/{{y}}/{{x}}.jpeg",
            attribution="항공사진 &copy; 국토지리정보원 · 브이월드(국토교통부)",
            max_native_zoom=19,
        )
    return DEFAULT_SATELLITE


def write(
    title: str,
    markers: list[Marker],
    walk_segments: list[tuple[list[tuple[float, float]], str, str]] | None = None,
    caption: str = "",
    items: list[Item] | None = None,
) -> str | None:
    """지도를 파일로 떨어뜨리고 주소를 돌려준다. 그릴 것이 없으면 None.

    같은 내용이면 같은 주소가 나온다(이름이 내용 해시라서). 이미 있으면 다시 쓰지
    않는다 — 추천을 두 번 물어도 파일이 두 개 생기지 않는다.
    """
    document = render(
        title=title,
        satellite=satellite(),
        markers=markers,
        walk_segments=walk_segments,
        caption=caption,
        items=items,
    )
    if not document:
        return None

    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()[:16]
    name = f"{digest}.html"
    target = MAPS_DIR / name
    if not target.exists():
        MAPS_DIR.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
    return f"{base_url()}/maps/{name}"


def read(name: str) -> str | None:
    """서빙용 — 이름으로 지도 HTML 을 읽는다. 모양이 어긋나거나 없으면 None.

    이름을 정규식으로 먼저 검사하는 것은 `../` 같은 경로 탈출을 막기 위해서다.
    해시 이름만 통과하므로 이 디렉터리 밖은 어떤 요청으로도 읽히지 않는다.
    """
    if not NAME_RE.match(name):
        return None
    target = MAPS_DIR / name
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8")
