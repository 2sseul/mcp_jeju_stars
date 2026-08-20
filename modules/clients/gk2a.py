"""천리안 2A(GK2A) 위성 기상산출물 경량화 조회 클라이언트.

기상청 API허브 `위성자료 경량화 조회서비스(기상산출물)` CloudSatlitInfoService의
한반도조회 계열을 감싼다.

배치 위치: modules/clients/gk2a.py  (네트워크 계층)

사양 근거: "9_위성자료 기상산출물 경량화 조회서비스 API 활용가이드(241008).docx"
  * dateTime 기준시각: KST (가이드 1-1)
  * 구름탐지/구름분석은 2분 간격, 안개는 10분 간격 (가이드 1-1)
  * 격자: Lambert Conformal Conic, Re=6371.00877km, 표준위도 30/60,
    기준점 126E/38N, 격자간격 2km. 기준점 X/Y는 가이드가 "변경될 수 있음"이라
    명시하므로 하드코딩하지 않고 응답의 x0/y0을 쓴다 (가이드 2-3)
  * value 배열: row-major, y가 느린 축 (가이드 2-2 변환코드 예시)
  * y는 북쪽으로 증가 -> 배열 0행 = 최남단, 0열 = 최서단
    (map_conv의 y = ro - ra*cos(theta) + yo 에서 ra가 위도에 대해 단조감소)
  * 결측: -9999 (가이드 CER 샘플데이터 "81,-9999,78..n")

문서와 실제가 다른 부분:
  가이드는 "데이터 갱신주기: 수시(3일 전 ~ 6시간 전까지 조회가능)"이라고 적어
  두었으나 2026-08 실측에서는 현재 시각 조회가 정상 동작했다. 문서화되지 않은
  동작이라 언제든 막힐 수 있으므로 fetch_latest()의 lookback으로 대비한다.
"""

from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import numpy as np
import requests

__all__ = [
    "KST",
    "MISSING",
    "PRODUCTS",
    "Gk2aError",
    "GridSpec",
    "GridField",
    "fetch",
    "fetch_latest",
]

KST = timezone(timedelta(hours=9))

_BASE = "https://apihub.kma.go.kr/api/typ02/openApi/CloudSatlitInfoService"

Product = Literal["cld", "cla", "fog"]

#: 산출물 -> (오퍼레이션, resultType, 생산주기(분))
PRODUCTS: dict[str, tuple[str, str, int]] = {
    "cld": ("getGk2acldAll", "cld", 2),   # 구름탐지
    "cla": ("getGk2aclaAll", "ca", 2),    # 구름분석 - 운량
    "fog": ("getGk2afogAll", "fog", 10),  # 안개
}

#: 결측 표준값. 원본 -9999 및 기타 음수를 전부 여기로 모은다.
MISSING = -1

# --- 구름탐지(CLD) 코드값 (가이드 1-2) -------------------------------------
CLD_CLOUD_CONFIDENT = 0  # cloud (Confidence)
CLD_CLOUD_LOW = 1        # cloud (Low Confidence)
CLD_CLEAR = 2            # clear (Confidence)
CLD_TBD = 3              # 정의 없음 -> 결측 취급

#: CLD에서 결측으로 돌릴 코드값
CLD_UNUSABLE: tuple[int, ...] = (CLD_TBD,)


class Gk2aError(RuntimeError):
    """API가 정상 응답을 주지 못했을 때."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class GridSpec:
    """응답이 알려준 격자 정의. 위경도 <-> 배열 인덱스 변환을 담당한다.

    가이드 2-3의 C 예제(map_conv)를 옮긴 것이다. 별첨 엑셀 없이 이 클래스만으로
    임의 좌표를 격자 인덱스로 바꿀 수 있다.
    """

    grid_km: float
    x0: float
    y0: float
    xdim: int
    ydim: int
    earth_radius_km: float = 6371.00877
    slat1: float = 30.0
    slat2: float = 60.0
    olon: float = 126.0
    olat: float = 38.0

    def _params(self) -> tuple[float, float, float, float, float]:
        d = math.pi / 180.0
        re = self.earth_radius_km / self.grid_km
        s1, s2 = self.slat1 * d, self.slat2 * d
        sn = math.log(math.cos(s1) / math.cos(s2)) / math.log(
            math.tan(math.pi * 0.25 + s2 * 0.5) / math.tan(math.pi * 0.25 + s1 * 0.5)
        )
        sf = math.tan(math.pi * 0.25 + s1 * 0.5)
        sf = (sf**sn) * math.cos(s1) / sn
        ro = math.tan(math.pi * 0.25 + self.olat * d * 0.5)
        ro = re * sf / (ro**sn)
        return d, re, sn, sf, ro

    def latlon_to_xy(self, lon: float, lat: float) -> tuple[float, float]:
        """위경도 -> 실수 격자좌표 (x=동쪽 증가, y=북쪽 증가)."""
        d, re, sn, sf, ro = self._params()
        ra = math.tan(math.pi * 0.25 + lat * d * 0.5)
        ra = re * sf / (ra**sn)
        theta = (lon - self.olon) * d
        if theta > math.pi:
            theta -= 2.0 * math.pi
        if theta < -math.pi:
            theta += 2.0 * math.pi
        theta *= sn
        return ra * math.sin(theta) + self.x0, ro - ra * math.cos(theta) + self.y0

    def xy_to_latlon(self, x: float, y: float) -> tuple[float, float]:
        """격자좌표 -> (lon, lat). 검산용 역변환."""
        d, re, sn, sf, ro = self._params()
        xn = x - self.x0
        yn = ro - y + self.y0
        ra = math.hypot(xn, yn)
        if sn < 0.0:
            ra = -ra
        alat = 2.0 * math.atan((re * sf / ra) ** (1.0 / sn)) - math.pi * 0.5
        if abs(xn) <= 0.0:
            theta = 0.0
        elif abs(yn) <= 0.0:
            theta = math.copysign(math.pi * 0.5, xn)
        else:
            theta = math.atan2(xn, yn)
        return (theta / sn) / d + self.olon, alat / d

    def index_of(self, lon: float, lat: float) -> tuple[int, int]:
        """위경도 -> 배열 인덱스 (iy, ix). 최근접 격자로 반올림."""
        x, y = self.latlon_to_xy(lon, lat)
        iy, ix = int(round(y)), int(round(x))
        if not (0 <= iy < self.ydim and 0 <= ix < self.xdim):
            raise IndexError(
                f"({lon}, {lat})는 격자 범위 밖 -> (iy={iy}, ix={ix}), "
                f"허용: iy<{self.ydim}, ix<{self.xdim}"
            )
        return iy, ix

    def bbox_indices(
        self, lon0: float, lat0: float, lon1: float, lat1: float, *, pad: int = 3
    ) -> tuple[int, int, int, int]:
        """위경도 사각형을 감싸는 인덱스 범위 (iy0, iy1, ix0, ix1), 끝은 exclusive.

        pad는 창 계산(5x5면 2칸)과 투영 왜곡을 흡수할 여유분이다.
        """
        corners = [self.latlon_to_xy(lo, la) for lo in (lon0, lon1) for la in (lat0, lat1)]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return (
            max(int(math.floor(min(ys))) - pad, 0),
            min(int(math.ceil(max(ys))) + pad, self.ydim),
            max(int(math.floor(min(xs))) - pad, 0),
            min(int(math.ceil(max(xs))) + pad, self.xdim),
        )


@dataclass(frozen=True, slots=True)
class GridField:
    """한반도 격자 한 장.

    values는 (ydim, xdim) 배열이고 0행이 최남단, 0열이 최서단이다.
    화면에 그릴 때만 np.flipud로 뒤집을 것.
    """

    product: str
    observed_at: str
    spec: GridSpec
    values: np.ndarray

    def at(self, lon: float, lat: float) -> int:
        iy, ix = self.spec.index_of(lon, lat)
        return int(self.values[iy, ix])

    def histogram(self) -> dict[int, int]:
        vals, counts = np.unique(self.values, return_counts=True)
        return {int(v): int(c) for v, c in zip(vals, counts)}

    def crop(self, iy0: int, iy1: int, ix0: int, ix1: int) -> np.ndarray:
        return np.array(self.values[iy0:iy1, ix0:ix1], copy=True)


def _floor_to_slot(when: datetime, minutes: int) -> datetime:
    return when.replace(minute=(when.minute // minutes) * minutes, second=0, microsecond=0)


def _find(node: ET.Element, tag: str) -> str | None:
    el = node.find(tag)
    return None if el is None or el.text is None else el.text.strip()


def _require(node: ET.Element, tag: str) -> str:
    text = _find(node, tag)
    if not text:
        raise Gk2aError(f"응답에 <{tag}> 값이 없습니다")
    return text


def _parse(xml_text: str, *, product: str) -> GridField:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise Gk2aError(f"XML 파싱 실패: {exc}. 본문 앞부분: {xml_text[:200]!r}") from exc

    header = root.find("header")
    if header is not None:
        code = _find(header, "resultCode")
        if code not in (None, "00"):
            raise Gk2aError(
                f"API 오류 resultCode={code} resultMsg={_find(header, 'resultMsg')}",
                code=code,
            )

    item = root.find("./body/items/item")
    if item is None:
        raise Gk2aError("응답에 <item>이 없습니다 (해당 시각 자료 미생산)")

    xdim = int(float(_require(item, "xdim")))
    ydim = int(float(_require(item, "ydim")))
    flat = np.array(_require(item, "value").split(","), dtype=np.int32)
    if flat.size != xdim * ydim:
        raise Gk2aError(f"value 길이 불일치: {flat.size}개 != xdim*ydim={xdim * ydim}개")

    grid = np.ascontiguousarray(flat.reshape(ydim, xdim))
    grid[grid < 0] = MISSING  # -9999 등
    if product == "cld":
        grid[np.isin(grid, CLD_UNUSABLE)] = MISSING  # 3=TBD

    return GridField(
        product=product,
        observed_at=_find(item, "dateTime") or "",
        spec=GridSpec(
            grid_km=float(_require(item, "gridKm")),
            x0=float(_require(item, "x0")),
            y0=float(_require(item, "y0")),
            xdim=xdim,
            ydim=ydim,
        ),
        values=grid.astype(np.int16),
    )


def fetch(
    when: datetime,
    *,
    product: Product = "cld",
    auth_key: str | None = None,
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> GridField:
    """한반도 격자 한 장을 받아온다. when은 aware datetime, 내부에서 KST로 변환."""
    if product not in PRODUCTS:
        raise ValueError(f"알 수 없는 산출물: {product!r} (가능: {sorted(PRODUCTS)})")
    key = auth_key or os.environ.get("KMA_API_KEY")
    if not key:
        raise Gk2aError("인증키가 없습니다. auth_key 인자나 KMA_API_KEY 환경변수를 설정하세요")
    if when.tzinfo is None:
        raise ValueError("naive datetime은 받지 않습니다. tzinfo를 붙여 넘기세요")

    operation, result_type, slot = PRODUCTS[product]
    stamp = _floor_to_slot(when.astimezone(KST), slot).strftime("%Y%m%d%H%M")

    response = (session or requests).get(
        f"{_BASE}/{operation}",
        params={
            "pageNo": 1,
            "numOfRows": 1,
            "dataType": "XML",
            "dateTime": stamp,
            "resultType": result_type,
            "authKey": key,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return _parse(response.text, product=product)


def fetch_latest(
    *,
    product: Product = "cld",
    now: datetime | None = None,
    max_lookback_minutes: int = 60,
    **kwargs,
) -> GridField:
    """생산 지연을 감안해 2분(안개는 10분)씩 거슬러 올라가며 최근 격자를 찾는다."""
    slot = PRODUCTS[product][2]
    cursor = _floor_to_slot((now or datetime.now(KST)).astimezone(KST), slot)
    last: Exception | None = None
    for _ in range(max_lookback_minutes // slot + 1):
        try:
            return fetch(cursor, product=product, **kwargs)
        except Gk2aError as exc:
            last = exc
            cursor -= timedelta(minutes=slot)
    raise Gk2aError(f"최근 {max_lookback_minutes}분 내 자료 없음. 마지막 오류: {last}")