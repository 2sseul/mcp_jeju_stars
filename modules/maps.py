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
서버가 자기 포트로 직접 서빙한다(`app.py` 의 `/maps/{name}`). 컨테이너에서
`MCP_HOST=0.0.0.0` 으로 뜨더라도 **0.0.0.0 은 브라우저가 열 수 있는 주소가 아니므로**
겉으로 내보내는 주소는 따로 정한다 — `MAP_BASE_URL` 환경변수, 없으면 루프백.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import os
import re

from modules import env, path, tiles
from modules.core.mapview import (
    DEFAULT_SATELLITE,
    Icon,
    Item,
    Marker,
    Tiles,
    Walk,
    render,
)

#: 지도 파일이 쌓이는 자리. `outputs/` 아래라 커밋되지 않는다.
MAPS_DIR = path.OUTPUTS / "maps"

#: 지도 파일 이름에 쓰는 sha256 앞자리 수.
#:
#: 16자리였을 때 qwen3.5:4b 가 "871efe3f80f07e5d" 를 "871fe3f80f07e5d" 로 한 글자
#: 흘려 죽은 주소를 내보냈다(E-02). 지도는 이 서버가 만드는 산출물이라 주소가 한
#: 글자만 틀려도 사용자에게 닿지 않는다. 10자리면 지도 수십만 장 규모에서도 충돌
#: 확률이 무시할 만하다.
DIGEST_LEN = 10

#: 파일 이름으로 허용하는 모양. 서빙 라우트가 이걸로 검사해 경로 탈출을 막는다.
#:
#: 자릿수를 **`write` 와 같은 상수에서** 뽑는다. 한때 여기에 16 이 박혀 있었는데,
#: `write` 의 해시를 10자리로 줄이면서 이쪽을 못 고쳐 새로 만든 지도가 전부 404 였다.
#: 파일은 멀쩡히 생겼고 라우트도 있었지만 이름 검사에서 걸렸다. 옛 16자리 지도도
#: 계속 열려야 하므로 범위로 받는다.
NAME_RE = re.compile(rf"^[0-9a-f]{{{DIGEST_LEN},16}}\.html$")


def base_url() -> str:
    """지도 주소의 앞부분. 실행 환경이 정한다.

    `MAP_BASE_URL` 이 우선이다 — 컨테이너·원격에서는 서버가 바인딩한 주소와 사용자가
    열 수 있는 주소가 다르기 때문이다(0.0.0.0 을 브라우저에 줄 수는 없다).
    """
    explicit = os.getenv("MAP_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    return f"http://127.0.0.1:{os.getenv('MCP_PORT', '11000')}"


def satellite() -> Tiles:
    """배경 위성 타일 — VWorld 키가 있으면 그것을, 없으면 기본 공급자를.

    VWorld(국토지리정보원 항공사진)는 제주 **z19 까지 실사진**이다 — 네 지점에서
    z19 네 장의 해시가 모두 달랐다(같으면 '자료 없음' 타일이다). 기본 공급자는 대부분
    z18 까지라, 키가 있으면 주차 구획과 탐방로가 눈에 띄게 선명해진다.

    키가 막히면(만료·미등록) 지도는 화면에서 기본 공급자로 갈아탄다 — `write` 가
    `fallback` 으로 함께 실어 보낸다. 이미 내보낸 지도 파일도 그 뒤로 계속 열리므로
    갈아타기는 서버가 아니라 지도 안에 있어야 한다.

    타일은 이 서버가 중계한다(`modules/tiles.py`) — 그쪽에 이유가 적혀 있다. 중계를
    끄면(`MAP_TILE_PROXY=0`) 공급자 주소가 지도에 그대로 실리고, 그때는 **키도 함께
    실린다**. 클라이언트가 직접 타일을 받는 방식이라 피할 수 없다(카카오 JS 키와 같은
    성격). 중계를 켜 두면 키는 서버 밖으로 나가지 않는다.

    `MAP_TILE_URL` 을 주면 그것이 최우선이다. 공급자를 바꿔 볼 때 코드를 안 고치려는
    구멍이고, `{z}`·`{x}`·`{y}` 자리표시자를 그대로 두면 된다. 중계를 거치지 않는다 —
    바꿔 보려고 넣은 주소를 사본으로 굳혀 두면 무엇을 보고 있는지가 흐려진다.
    """
    explicit = env.read("MAP_TILE_URL")
    if explicit:
        return Tiles(
            url=explicit,
            attribution=env.read("MAP_TILE_CREDIT") or "위성사진 제공: 설정된 공급자",
            max_native_zoom=int(env.read("MAP_TILE_MAX_ZOOM") or 19),
        )

    if env.read("VWORLD_API_KEY"):
        return _vworld("sat", "항공사진 &copy; 국토지리정보원 · 브이월드(국토교통부)")
    return DEFAULT_SATELLITE


def _vworld(layer: str, credit: str) -> Tiles:
    """브이월드 한 겹 — 중계를 켰으면 이 서버 주소로, 껐으면 공급자 주소로.

    겉으로 내보내는 주소를 짓는 일은 이 모듈 몫이라(머리말) `tiles` 는 뒷부분만
    내놓고 앞부분은 여기서 붙인다.
    """
    source = tiles.SOURCES[layer]
    if tiles.enabled():
        url = base_url() + tiles.PATH_TEMPLATE.replace("{layer}", layer)
    else:
        url = source.template.format(
            key=env.read("VWORLD_API_KEY"), z="{z}", x="{x}", y="{y}"
        )
    return Tiles(url=url, attribution=credit, max_native_zoom=source.max_native_zoom)


@functools.lru_cache(maxsize=1)
def icons() -> dict[str, Icon]:
    """마커 그림을 파일에서 읽어 `data:` 로 굽는다. 파일이 없으면 그 갈래는 뺀다.

    **주소로 걸지 않고 통째로 박아 넣는다.** 내보낸 지도는 이 서버보다 오래 산다 —
    주소로 걸어 두면 서버가 내려간 날 지도마다 깨진 그림 자리가 생긴다. 그림은
    `scripts/build_icons.py` 가 마커 크기로 줄여 둔 것이라 셋을 합쳐 18KB 다.

    없으면 없는 대로 둔다. 그림을 아직 안 구웠다고 지도가 안 나오면 곤란하고,
    `mapview` 는 그림이 없는 갈래를 색 동그라미와 글자로 그린다.
    """
    at = path.ICONS / "anchor.json"
    anchors = json.loads(at.read_text(encoding="utf-8")) if at.exists() else {}
    out: dict[str, Icon] = {}
    for f in sorted(path.ICONS.glob("*.png")):
        blob = base64.b64encode(f.read_bytes()).decode("ascii")
        ax, ay = anchors.get(f.stem, (0.5, 0.5))
        out[f.stem] = Icon(
            url=f"data:image/png;base64,{blob}",
            anchor=(float(ax), float(ay)),
        )
    return out


def overlay() -> Tiles | None:
    """위성 위에 얹을 도로·지명 겹. 없으면 None.

    **국내 도로는 국내 공급자에게서만 온다.** Esri 의 레퍼런스 겹(World_Transportation·
    World_Boundaries_and_Places)은 한국 위에서 875바이트짜리 투명 타일만 준다 — 국내
    지도 데이터 반출 제한이라 위성사진과 달리 채워지지 않는다. 그래서 키가 없으면
    얹을 것이 없고, 얹는 시늉을 하느니 안 얹는다.

    브이월드 `Hybrid` 는 위성 배경과 **같은 키·같은 공급자**다. 위성이 키 때문에
    죽는 날 이 겹도 같이 죽는데, 그건 화면이 알아서 내린다(`mapview` 의 tileerror).
    """
    if not env.read("VWORLD_API_KEY"):
        return None
    return _vworld("hybrid", "도로·지명 &copy; 국토교통부 브이월드")


def write(
    title: str,
    markers: list[Marker],
    walk_segments: list[Walk] | None = None,
    items: list[Item] | None = None,
) -> str | None:
    """지도를 파일로 떨어뜨리고 주소를 돌려준다. 그릴 것이 없으면 None.

    같은 내용이면 같은 주소가 나온다(이름이 내용 해시라서). 이미 있으면 다시 쓰지
    않는다 — 추천을 두 번 물어도 파일이 두 개 생기지 않는다.
    """
    sat = satellite()
    document = render(
        title=title,
        satellite=sat,
        # 키가 필요한 공급자를 쓸 때만 갈아탈 자리를 함께 실어 보낸다. 키는 언젠가
        # 만료되거나 등록에서 빠지고, 그때 이미 나간 지도들은 배경 없이 열린다.
        fallback=None if sat is DEFAULT_SATELLITE else DEFAULT_SATELLITE,
        markers=markers,
        overlay=overlay(),
        walk_segments=walk_segments,
        items=items,
        icons=icons(),
    )
    if not document:
        return None

    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()[:DIGEST_LEN]
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
