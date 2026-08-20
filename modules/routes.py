"""도구 라우트 — FastAPI 라우트 1개가 MCP 도구 1개다.

`FastMCP.from_fastapi` 가 이 앱의 OpenAPI 문서를 읽어 도구 스키마를 만든다. 그래서
**외부 LLM 이 읽는 계약이 이 파일에 있다**:

    operation_id        → 도구 이름
    summary             → 도구를 쓸지 말지 판단하는 한 줄
    엔드포인트 docstring → 도구 설명(언제 쓰는가·무엇을 답하는가)
    Field(description=) → 인자 설명(무엇을 넣어야 하는가)

판정은 여기 없다. `modules/tools.py` 의 순수 함수를 부르기만 한다 — 계약(설명)과
판정(계산)을 가르면 설명을 고치느라 계산을 건드릴 일이 없다.

도구는 **사용자 질문의 목적**으로 셋이다 (입력 형태가 아니다)
--------------------------------------------------------------------------
    recommend_spots  "어디로 갈까"   — 조건에 맞는 관측지를 골라 준다
    evaluate_place   "여기 별 보여?" — 지목한 장소 하나를 판정한다
    spot_details     "거기 어때?"    — 검증된 관측지의 접근성·편의를 답한다

좌표를 받느냐 지명을 받느냐로 가르지 않는다. 그건 **입력 형태**일 뿐이고 사용자의
질문 목적이 아니다 — `evaluate_place` 하나가 둘 다 받는다(`query` 또는 `lat`·`lon`).

요청 모델의 필드 이름은 `tools.py` 함수의 인자 이름과 **같아야 한다**. 아래에서
이름을 하나씩 적어 넘기므로, 어긋나면 서버가 뜨는 순간이 아니라 그 도구를 처음
부르는 순간 `TypeError` 로 드러난다.
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from modules import tools


class RecommendSpotsRequest(BaseModel):
    origin: Optional[str] = Field(
        default=None,
        description="출발지 지명·주소 (예: '제주공항', '애월읍'). origin_lat/lon 과 택일.",
    )
    origin_lat: Optional[float] = Field(
        default=None,
        description="출발지 위도. origin_lon 과 함께 줄 때만 쓴다(현재 위치 등).",
    )
    origin_lon: Optional[float] = Field(default=None, description="출발지 경도.")
    max_drive_minutes: Optional[float] = Field(
        default=None,
        description="이 시간 안에 갈 수 있는 곳만. 출발지가 있어야 동작한다.",
    )
    region: Optional[str] = Field(
        default=None,
        description="'동'·'서'·'남'·'북'·'중산간' 중 하나로 지역을 좁힌다.",
    )
    no_climb: bool = Field(
        default=False,
        description="True 면 오르막 산행이 필요한 곳을 뺀다('등산 없는 곳').",
    )
    max_walk_minutes: Optional[float] = Field(
        default=None,
        description="주차 지점에서 관측 지점까지 편도 도보가 이 시간 이하인 곳만. "
                    "0 을 주면 '주차하고 바로 보는 곳'에 가깝다.",
    )
    parking_required: bool = Field(
        default=False, description="True 면 주차장이 확인된 곳만."
    )
    pets: bool = Field(
        default=False, description="True 면 반려동물 동반이 가능한 곳만."
    )
    date: Optional[str] = Field(
        default=None, description="판정 기준 날짜 YYYY-MM-DD (생략 시 오늘)."
    )
    time: Optional[str] = Field(
        default=None,
        description="판정 기준 시각 HH:MM 24시간 KST (생략 시 22:00).",
    )
    limit: int = Field(
        default=3, ge=1, le=10, description="돌려줄 곳 수. 기본 3, 최대 10."
    )


class EvaluatePlaceRequest(BaseModel):
    query: Optional[str] = Field(
        default=None,
        description="장소 이름·주소 (예: '1100고지', '새별오름', '제주시 애월읍').",
    )
    lat: Optional[float] = Field(
        default=None,
        description="위도. lon 과 함께 줄 때만 쓴다. query 대신 좌표로 물을 때.",
    )
    lon: Optional[float] = Field(default=None, description="경도.")
    origin: Optional[str] = Field(
        default=None,
        description="출발지 지명·주소 (예: '제주공항'). 주행시간을 함께 받고 싶을 때.",
    )
    origin_lat: Optional[float] = Field(
        default=None,
        description="출발지 위도. origin_lon 과 함께 줄 때만 쓴다(현재 위치 등).",
    )
    origin_lon: Optional[float] = Field(default=None, description="출발지 경도.")
    date: Optional[str] = Field(
        default=None,
        description="YYYY-MM-DD (생략 시 오늘). 미래 날짜 가능(구름은 예보 지평 ~7일 안).",
    )
    time: Optional[str] = Field(
        default=None,
        description="HH:MM 24시간 KST. scope='moment' 에서만(생략 시 22:00; "
                    "date·time 모두 생략 시 현재). scope='night' 이면 무시.",
    )
    scope: str = Field(
        default="moment",
        description="'moment'(한 시각) | 'night'(밤 전체 시간 수·등급 분포). 기본 'moment'.",
    )


class SpotDetailsRequest(BaseModel):
    name: str = Field(
        ...,
        description="관측지 이름 (예: '새별오름', '매오름'). 띄어쓰기는 달라도 된다.",
    )
    origin: Optional[str] = Field(
        default=None, description="출발지 지명·주소. 주행시간을 함께 받고 싶을 때."
    )
    origin_lat: Optional[float] = Field(
        default=None, description="출발지 위도 (origin_lon 과 함께)."
    )
    origin_lon: Optional[float] = Field(default=None, description="출발지 경도.")


def register_routes(app: FastAPI) -> None:
    """도구 셋의 라우트를 FastAPI 앱에 등록한다."""

    @app.post(
        "/recommend-spots",
        operation_id="recommend_spots",
        summary="조건에 맞는 제주 별 관측지를 추천한다 (검증된 62곳 중에서)",
    )
    def recommend_spots(
        request: RecommendSpotsRequest = RecommendSpotsRequest(),
    ) -> Dict[str, Any]:
        """조건에 맞는 제주 별 관측지를 추천한다 (검증된 62곳 중에서).

        "지금 근처에서 별 보기 좋은 곳", "제주 동쪽에서 추천", "30분 안에 갈 수 있는 곳",
        "주차장에서 바로 보는 곳", "등산 없는 곳" 같은 질의를 처리한다.

        **인자는 전부 선택이다.** "별 관측지 알려줘"처럼 조건이 하나도 없으면 인자 없이
        부르면 된다 — 오늘 밤 22시 기준으로 전체에서 상위 3곳을 돌려준다. 출발지나
        조건을 사용자에게 되묻지 말고, 아는 것만 채워 일단 부른다.

        출발지를 주면 **실제 도로를 따라간 주행시간**으로 자르고 순위에 반영한다
        (직선거리가 아니다 — 제주는 가운데가 한라산이라 직선거리로 자르면 산 반대편을
        추천하게 된다). 정체는 반영하지 않는 야간 자유주행 기준이다.

        추천 목록은 `spots` 배열에 있고 각 항목에 주행시간(`drive`)·도보
        (`walk_minutes`)·야간 출입(`night_access`)이 들어 있다.
        """
        # 본문 자체를 선택으로 둔다. 인자가 전부 Optional 이라 MCP 스키마는
        # `required: []` 로 나가는데, 본문이 필수면 `{}` 로 부른 호출이 422 로 튕긴다
        # — 스키마가 허락한 호출을 서버가 거절하는 꼴이다. "별 관측지 알려줘"처럼
        # 조건 없는 질의가 정확히 그 호출을 만든다.
        return tools.recommend_spots(
            origin=request.origin,
            origin_lat=request.origin_lat,
            origin_lon=request.origin_lon,
            max_drive_minutes=request.max_drive_minutes,
            region=request.region,
            no_climb=request.no_climb,
            max_walk_minutes=request.max_walk_minutes,
            parking_required=request.parking_required,
            pets=request.pets,
            date=request.date,
            time=request.time,
            limit=request.limit,
        )

    @app.post(
        "/evaluate-place",
        operation_id="evaluate_place",
        summary="지목한 제주 장소에서 별이 보이는지 판정한다",
    )
    def evaluate_place(
        request: EvaluatePlaceRequest = EvaluatePlaceRequest(),
    ) -> Dict[str, Any]:
        """지목한 제주 장소에서 별이 보이는지 판정한다.

        "오늘 1100고지에서 별 보여?", "지금 새별오름 가면 별 잘 보일까?" 같은 질의.
        장소는 이름(`query`)으로 주거나 좌표(`lat`·`lon`)로 준다 — 둘 중 하나면 된다.

        **등록되지 않은 장소도 판정한다.** 좌표만 알면 날씨·광공해·천문 조건은 똑같이
        계산된다. 다만 주차·야간 출입·도보 난이도는 검증된 관측지 62곳에만 있으므로,
        미등록 장소는 그 정보가 **확인되지 않았음을 응답에 명시**한다. 접근성까지 알고
        싶으면 `recommend_spots` 로 등록된 곳을 받거나 `spot_details` 로 조회한다.

        **출발지(현재 위치)를 주면 거기서 몇 분 걸리는지 함께 답한다.** 등록 여부와
        무관하다 — 주행시간은 좌표만 있으면 도로 그래프로 계산되기 때문이다. 미등록
        장소에서 답할 수 있는 접근성은 이 주행시간까지이고, 주차·야간 출입은 여전히
        모른다. 실제 도로 기준이며 정체는 반영하지 않는다(야간 자유주행).

        **무엇을 묻는지는 `scope` 로 가른다.** "지금 보여?"처럼 한 시각을 물으면
        `scope="moment"`(기본), "오늘 밤 어때?"처럼 밤 전체를 물으면
        `scope="night"` — 박명 포함 밤을 시간별로 판정해 관측 가능 시간 수·등급
        분포·연속으로 트인 창을 집계한다(`scope="night"` 이면 `time` 은 무시된다).

        등록된 관측지면 `spots` 에 그 곳의 접근성 요약이 실리고, 출발지를 줬으면
        `numbers.drive` 에 주행시간·거리가 실린다.
        """
        # 여기도 같은 이유로 본문을 선택으로 둔다. `{}` 로 부르면 422 가 아니라
        # "평가할 장소를 알려주세요" 라는 고정 스키마 응답이 나가야 한다 —
        # 프로토콜 오류보다 프롬프트형 응답이 모델이 회복할 수 있는 형태다.
        return tools.evaluate_place(
            query=request.query,
            lat=request.lat,
            lon=request.lon,
            origin=request.origin,
            origin_lat=request.origin_lat,
            origin_lon=request.origin_lon,
            date=request.date,
            time=request.time,
            scope=request.scope,
        )

    @app.post(
        "/spot-details",
        operation_id="spot_details",
        summary="검증된 관측지의 주차·도보·야간 출입·반려동물·화장실·주의사항을 조회한다",
    )
    def spot_details(request: SpotDetailsRequest) -> Dict[str, Any]:
        """검증된 관측지의 주차·도보·야간 출입·반려동물·화장실·주의사항을 조회한다.

        "매오름 많이 걸어야 해?", "강아지랑 갈 수 있어?", "새별오름 밤에 들어갈 수 있어?",
        "천아계곡까지 가기 어려워?" 같은 질의를 처리한다. 하늘 상태는 답하지 않는다 —
        그건 `evaluate_place` 소관이다.

        출발지를 주면 그곳까지의 주행시간도 함께 답한다.

        상세는 `spots` 배열의 한 항목에 전부 들어 있다.
        """
        return tools.spot_details(
            name=request.name,
            origin=request.origin,
            origin_lat=request.origin_lat,
            origin_lon=request.origin_lon,
        )
