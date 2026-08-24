"""배경 타일 중계와 그 사본 — 브라우저와 공급자 사이에 한 겹.

왜 중계하나
--------------------------------------------------------------------------
브이월드(국토지리정보원 항공사진)는 CDN 이 아니라 **단일 origin** 이고 HTTP/1.1 이다.
타일 한 장의 TTFB 가 0.8~1.5초인데 브라우저는 한 호스트에 연결을 여섯 개까지만 여니,
한 화면치 서른 장이 여섯 줄로 줄을 선다 — 배경이 다 차기까지 십수 초다.

그런데 **같은 장면을 여러 번 본다.** 제주는 좁고 관측지는 정해진 63곳이라, 추천을
다시 물으면 대개 같은 타일을 다시 받는다. 브라우저 캐시는 그 사람 그 브라우저
안에서만 듣는다 — 다른 사람이 열면, 창을 갈면, 사본이 밀려나면 공급자를 또 때린다.
사본을 **서버가** 쥐면 두 번째부터는 디스크에서 바로 나간다(1초 → 1밀리초 아래).

덤으로 키가 지도에서 빠진다. 지금까지 VWorld 키는 지도 HTML 에 그대로 실려 나갔다
— 클라이언트가 직접 타일을 받는 방식이라 피할 수 없었다. 중계하면 키는 서버에만 있다.

중계 주소는 이 서버를 가리킨다
--------------------------------------------------------------------------
서버가 없는 자리에서 옛 지도를 열면 배경이 안 온다. 지도 파일이 서버보다 오래 산다는
전제(`maps.icons` 가 그림을 박아 넣는 이유)와 부딪치는 지점이라 그냥 두지 않는다 —
그 고장은 **이미 화면이 받는다.** 넉 장이 실패하면 키가 필요 없는 공급자(Esri)로
갈아탄다(`core/mapview.py` 의 tileerror). 배경 없이 열리는 지도는 생기지 않는다.

`MAP_TILE_PROXY=0` 이면 중계를 끄고 예전처럼 공급자 주소를 그대로 싣는다.

무엇을 사본으로 남기지 않는가
--------------------------------------------------------------------------
**그림이 아닌 응답은 남기지 않는다.** 브이월드는 키가 막혀도 404 를 주지 않고 200 에
오류 문서를 실어 보낸다. 그것을 사본으로 굳히면 키를 고친 뒤에도 깨진 배경이
캐시가 비워질 때까지 계속 나간다. 그래서 매직 바이트로 그림인지 보고 나서 쓴다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter

from modules import env, path

#: 지도 HTML 이 쓰는 중계 주소의 **뒷부분**. 앞부분은 `maps.base_url()` 이 붙인다 —
#: 겉으로 내보내는 주소를 정하는 곳은 한 군데여야 한다(`maps.py` 머리말).
PATH_TEMPLATE = "/tiles/{layer}/{z}/{x}/{y}"

#: 중계한 타일에 붙이는 브라우저 캐시 수명(초). 공급자가 스스로 붙이는 3일보다 길게
#: 잡는다 — 항공사진은 몇 해 단위로 바뀌고, 서버에 사본이 있으니 만료돼도 싸다.
MAX_AGE = 7 * 24 * 3600

#: 한 장을 받는 데 이보다 오래 걸리면 포기한다. 브라우저는 그 자리를 비워 두었다가
#: 다음 이동에서 다시 요청하고, 넉 장이 밀리면 화면이 다른 공급자로 갈아탄다.
TIMEOUT_S = 20


@dataclass(frozen=True)
class Source:
    """중계할 공급자 한 겹 — 원본 주소·사본 확장자·실사진 최대 줌."""

    #: `{key}`·`{z}`·`{x}`·`{y}` 자리표시자를 가진 원본 주소.
    template: str
    ext: str
    content_type: str
    #: 실제 사진이 있는 가장 큰 줌. 이보다 큰 줌은 요청조차 하지 않는다.
    max_native_zoom: int


#: 중계하는 겹들. **여기 있는 이름만** 주소로 받아들인다 — 층 이름이 파일 경로의 한
#: 조각이 되므로, 자유 문자열을 그대로 쓰면 `../` 로 캐시 밖이 열린다. 목록 대조가
#: 그 자체로 경로 탈출 방어다(`maps.NAME_RE` 가 지도 이름에 하는 것과 같은 일).
SOURCES: dict[str, Source] = {
    "sat": Source(
        template="https://api.vworld.kr/req/wmts/1.0.0/{key}/Satellite/{z}/{y}/{x}.jpeg",
        ext="jpg",
        content_type="image/jpeg",
        max_native_zoom=19,
    ),
    "hybrid": Source(
        template="https://api.vworld.kr/req/wmts/1.0.0/{key}/Hybrid/{z}/{y}/{x}.png",
        ext="png",
        content_type="image/png",
        max_native_zoom=19,
    ),
}

#: 그림인지 가리는 첫 바이트들. 오류 문서(HTML·JSON)를 사본으로 굳히지 않으려는 것.
_MAGIC = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}

#: 공급자와의 연결을 이어 쓴다. 한 장마다 TLS 손을 새로 잡으면 0.70초인데 연결을
#: 재사용하면 0.27초다 — 한 화면 서른 장이면 그 차이가 그대로 쌓인다. 브이월드가
#: 단일 origin 이라 손 잡는 값이 특히 비싸다.
#:
#: 풀은 브라우저가 우리에게 여는 연결 수(여섯)보다 넉넉히 잡는다. 모자라면 초과분은
#: 연결을 새로 잡아 버려 이 최적화가 조용히 사라진다.
_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=0),
)

#: 같은 타일을 동시에 두 번 받아 오지 않게 하는 자물쇠. 브라우저가 여는 연결 여섯
#: 개가 같은 장을 두고 겹치는 일은 드물지만, 지도 두 장이 같은 자리를 그리면 겹친다.
_locks: dict[tuple[str, int, int, int], threading.Lock] = {}
_locks_guard = threading.Lock()


def enabled() -> bool:
    """중계를 켤 것인가 — 키가 있고, 끄라고 하지 않았을 때."""
    if env.read("MAP_TILE_PROXY").lower() in ("0", "off", "false", "no"):
        return False
    return bool(env.read("VWORLD_API_KEY"))


def _valid(layer: str, z: int, x: int, y: int) -> Source | None:
    """받아들일 요청인가. 아니면 None — 여기서 걸러야 파일 경로가 안전하다."""
    source = SOURCES.get(layer)
    if source is None:
        return None
    if not 0 <= z <= source.max_native_zoom:
        return None
    span = 1 << z
    if not (0 <= x < span and 0 <= y < span):
        return None
    return source


def _cached(layer: str, source: Source, z: int, x: int, y: int):
    """사본이 놓이는 자리. 줌·x 로 디렉터리를 갈라 한 곳에 파일이 몰리지 않게 한다."""
    return path.TILE_CACHE / layer / str(z) / str(x) / f"{y}.{source.ext}"


def _download(source: Source, z: int, x: int, y: int) -> bytes | None:
    """공급자에게서 한 장. 그림이 아니면 None — 오류 문서를 그림으로 넘기지 않는다."""
    url = source.template.format(key=env.read("VWORLD_API_KEY"), z=z, x=x, y=y)
    try:
        response = _session.get(url, timeout=TIMEOUT_S)
        blob = response.content
    except (requests.RequestException, OSError):
        return None
    if not blob.startswith(_MAGIC[source.content_type]):
        return None
    return blob


def fetch(layer: str, z: int, x: int, y: int) -> tuple[bytes, str] | None:
    """타일 한 장과 그 종류. 사본이 있으면 디스크에서, 없으면 받아서 남기고.

    **막는 호출이다.** 서빙하는 쪽(`app.py`)이 스레드로 빼서 부른다 — 한 장에 1초가
    걸릴 수 있고, 그동안 이벤트 루프가 멈추면 같은 화면의 나머지 다섯 장도 함께 선다.

    Returns:
        (그림 바이트, content-type). 받지 못했거나 받아들일 수 없는 요청이면 None.
    """
    source = _valid(layer, z, x, y)
    if source is None:
        return None

    target = _cached(layer, source, z, x, y)
    if target.is_file():
        return target.read_bytes(), source.content_type

    key = (layer, z, x, y)
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    try:
        with lock:
            # 자물쇠를 기다리는 동안 앞사람이 받아 두었을 수 있다.
            if target.is_file():
                return target.read_bytes(), source.content_type
            blob = _download(source, z, x, y)
            if blob is None:
                return None
            # 임시 이름으로 쓰고 옮긴다. 쓰다 만 파일이 사본으로 남으면 그 자리는
            # 캐시를 비울 때까지 계속 깨진 그림을 낸다.
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = target.with_suffix(target.suffix + ".part")
            staging.write_bytes(blob)
            staging.replace(target)
            return blob, source.content_type
    finally:
        # 자물쇠를 남겨 두면 타일 하나에 하나씩 쌓인다. 제주 한 섬이라도 z19 까지
        # 세면 수만 개다. 기다리던 쪽은 이미 이 객체를 쥐고 있으므로 지워도 된다.
        with _locks_guard:
            _locks.pop(key, None)
