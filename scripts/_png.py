"""PNG 8비트 RGBA 읽기·쓰기와 넓이평균 축소 — 외부 의존 없이 numpy 와 zlib 만.

마커 아이콘을 만드는 데만 쓴다. Pillow 를 끌어오지 않는 이유는 이것이 **한 번 돌리고
마는 도구**라서다 — 실행에 쓰이지 않는 것을 requirements 에 얹지 않는다.
"""
from __future__ import annotations

import struct
import zlib

import numpy as np


def read(path: str) -> np.ndarray:
    """8비트 RGBA·비인터레이스 PNG 를 (H, W, 4) uint8 로. 그 밖의 모양은 거절한다."""
    raw = open(path, "rb").read()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", path
    idat, w, h, pos = bytearray(), 0, 0, 8
    while pos < len(raw):
        n, tag = struct.unpack(">I4s", raw[pos:pos + 8])
        body = raw[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert (depth, color, interlace) == (8, 6, 0), (path, depth, color, interlace)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + n

    data = np.frombuffer(zlib.decompress(bytes(idat)), dtype=np.uint8)
    stride = w * 4
    rows = data.reshape(h, stride + 1)
    out = np.zeros((h, stride), dtype=np.uint8)
    # 스캔라인 필터를 푼다. 앞 픽셀(a)·윗줄(b)·왼쪽위(c) 를 참조하므로 줄 단위로 순서대로.
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(h):
        ft = rows[y, 0]
        cur = rows[y, 1:].astype(np.int32)
        if ft == 0:
            line = cur
        elif ft == 2:                                   # Up
            line = (cur + prev) & 255
        else:                                           # Sub·Average·Paeth 는 픽셀 순차
            line = cur.copy()
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                b = prev[i]
                c = prev[i - 4] if i >= 4 else 0
                if ft == 1:
                    line[i] = (line[i] + a) & 255
                elif ft == 3:
                    line[i] = (line[i] + (a + b) // 2) & 255
                elif ft == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[i] = (line[i] + pred) & 255
                else:
                    raise AssertionError(f"모르는 필터 {ft}")
        out[y] = line.astype(np.uint8)
        prev = line
    return out.reshape(h, w, 4)


def write(path: str, img: np.ndarray) -> int:
    """(H, W, 4) uint8 을 PNG 로. 필터는 쓰지 않는다(0) — 작은 그림이라 이득이 없다."""
    h, w = img.shape[:2]
    body = np.concatenate(
        [np.zeros((h, 1, 4), np.uint8)[:, :, :1], img.reshape(h, w * 4, 1)], axis=1
    ).reshape(h, -1)[:, : w * 4 + 1]
    flat = np.zeros((h, w * 4 + 1), np.uint8)
    flat[:, 1:] = img.reshape(h, w * 4)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(flat.tobytes(), 9))
            + chunk(b"IEND", b""))
    open(path, "wb").write(blob)
    return len(blob)


def trim(img: np.ndarray, thresh: int = 8) -> np.ndarray:
    """투명한 여백을 잘라낸다. 아이콘마다 여백이 달라 그대로 두면 크기가 제각각이다."""
    ys, xs = np.where(img[:, :, 3] > thresh)
    if not len(ys):
        return img
    return img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def fit(img: np.ndarray, side: int) -> np.ndarray:
    """가로세로 비를 지키며 `side` 정사각 안에 넣는다 — 넓이평균으로 줄인다.

    가장 가까운 픽셀을 집으면(nearest) 1500px 을 50px 로 줄일 때 30픽셀 중 하나만
    남아 가장자리가 톱니처럼 부서진다. 덮는 넓이만큼 섞어야 형태가 남는다.
    """
    h, w = img.shape[:2]
    scale = side / max(h, w)
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    src = img.astype(np.float64)
    # 알파를 곱해 두고 섞는다. 안 그러면 투명한 픽셀의 (아무 값이나 들어 있는) 색이
    # 가장자리로 배어 나와 검은 테두리가 생긴다.
    src[:, :, :3] *= src[:, :, 3:4] / 255.0

    ys = (np.arange(nh + 1) * h / nh)
    xs = (np.arange(nw + 1) * w / nw)
    out = np.zeros((nh, nw, 4))
    for y in range(nh):
        y0, y1 = int(ys[y]), max(int(ys[y]) + 1, int(np.ceil(ys[y + 1])))
        band = src[y0:y1]
        for x in range(nw):
            x0, x1 = int(xs[x]), max(int(xs[x]) + 1, int(np.ceil(xs[x + 1])))
            out[y, x] = band[:, x0:x1].reshape(-1, 4).mean(axis=0)

    a = out[:, :, 3:4]
    out[:, :, :3] = np.divide(out[:, :, :3] * 255.0, a, out=np.zeros_like(out[:, :, :3]),
                              where=a > 0.5)
    canvas = np.zeros((side, side, 4))
    oy, ox = (side - nh) // 2, (side - nw) // 2
    canvas[oy:oy + nh, ox:ox + nw] = out
    return np.clip(canvas, 0, 255).astype(np.uint8)


def pad(img: np.ndarray, side: int) -> np.ndarray:
    """더 큰 정사각 한가운데로 옮긴다. 테두리를 두를 여백을 내주려고 쓴다."""
    h, w = img.shape[:2]
    out = np.zeros((side, side, 4), np.uint8)
    oy, ox = (side - h) // 2, (side - w) // 2
    out[oy:oy + h, ox:ox + w] = img
    return out


def outline(img: np.ndarray, radius: float = 3.0,
            color: tuple[int, int, int] = (255, 255, 255)) -> np.ndarray:
    """그림의 실루엣을 따라 테두리를 두른다 — 알파를 부풀려 그 밑에 색을 깐다.

    사각 상자를 두르지 않는 이유는 별·물방울의 **윤곽이 곧 그 아이콘**이라서다.
    위성사진 위에서 밝은 그림은 밝은 자리에, 어두운 그림은 어두운 자리에 묻히는데,
    실루엣을 따라가는 흰 테두리는 어느 배경에서도 그림을 떼어 놓는다.

    CSS 로 그리지 않고 **파일에 굽는다.** `drop-shadow` 를 여러 겹 쌓아 흉내 낼 수는
    있지만 마커 하나마다 매 프레임 다시 그려지고, 결과는 여기서 한 번 계산해 두면
    그만인 것이다.
    """
    a = img[:, :, 3].astype(np.float64) / 255.0
    grown = np.zeros_like(a)
    r = int(np.ceil(radius))
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            m = np.roll(np.roll(a, dy, axis=0), dx, axis=1)
            # `roll` 은 반대쪽 끝에서 감아 온다. 감겨 들어온 자리를 지운다.
            if dy > 0:
                m[:dy] = 0
            elif dy < 0:
                m[dy:] = 0
            if dx > 0:
                m[:, :dx] = 0
            elif dx < 0:
                m[:, dx:] = 0
            grown = np.maximum(grown, m)

    # 테두리(아래) 위에 원본(위)을 얹는다 — 곧은 알파 합성.
    base = np.zeros_like(img, dtype=np.float64)
    base[:, :, :3] = color
    out_a = a + grown * (1 - a)
    rgb = (img[:, :, :3].astype(np.float64) * a[:, :, None]
           + base[:, :, :3] * (grown * (1 - a))[:, :, None])
    with np.errstate(invalid="ignore", divide="ignore"):
        rgb = np.where(out_a[:, :, None] > 1e-6, rgb / np.maximum(out_a[:, :, None], 1e-6), 0)
    return np.concatenate(
        [np.clip(rgb, 0, 255), np.clip(out_a * 255, 0, 255)[:, :, None]], axis=2
    ).astype(np.uint8)


def tip(img: np.ndarray) -> tuple[float, float]:
    """그림에서 '그 자리'가 어디인가 — 아래 끝 가운데를 가로세로 **비율**로.

    물방울 표지의 뾰족한 끝을 찾는 데 쓴다. 픽셀 수로 적어 두면 아이콘 크기를 바꿀
    때마다 어긋나므로 비율로 답한다.
    """
    ys, xs = np.where(img[:, :, 3] > 24)
    bottom = ys.max()
    span = xs[ys == bottom]
    return (float(span.mean() + 0.5) / img.shape[1],
            float(bottom + 1) / img.shape[0])
