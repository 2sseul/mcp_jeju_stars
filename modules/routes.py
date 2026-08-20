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
        description="출발지 지명·주소 문자열. 예: '제주공항' · '애월읍' · '서귀포시청'. "
                    "max_drive_minutes 를 쓰려면 이 값이나 origin_lat/lon 이 있어야 한다.",
    )
    origin_lat: Optional[float] = Field(
        default=None,
        description="출발지 위도(십진수, 제주 33.19~33.57). "
                    "origin_lon 과 함께 줄 때만 유효하다.",
    )
    origin_lon: Optional[float] = Field(
        default=None, description="출발지 경도(십진수, 제주 126.14~126.98)."
    )
    max_drive_minutes: Optional[float] = Field(
        default=None,
        description="이 분 안에 도착하는 곳만. 양수(예: 30·40·60). 출발지가 있어야 "
                    "동작한다. 야간 자유주행 기준으로 정체는 반영하지 않는다.",
    )
    region: Optional[str] = Field(
        default=None,
        description="허용값은 '동'·'서'·'남'·'북'·'중산간' 다섯뿐. '동쪽'·'제주 동부'는 "
                    "'동'. 그 밖의 지명(예: '애월')은 여기 넣지 말고 origin 으로 넘긴다.",
    )
    no_climb: bool = Field(
        default=False,
        description="True 면 오르막 산행이 필요한 곳을 뺀다. "
                    "'등산 없이'·'안 올라가도 되는' → True. 기본 False.",
    )
    max_walk_minutes: Optional[float] = Field(
        default=None,
        description="주차 지점→관측 지점 편도 도보 상한(분). 0 이면 "
                    "'주차하고 바로 보는 곳'. 예: 0 · 5 · 10.",
    )
    parking_required: bool = Field(
        default=False,
        description="True 면 주차장이 확인된 곳만. '주차되는 곳' → True. 기본 False.",
    )
    pets: bool = Field(
        default=False,
        description="True 면 반려동물 동반 가능한 곳만. '강아지'·'반려견' → True. "
                    "기본 False.",
    )
    date: Optional[str] = Field(
        default=None,
        description="형식 YYYY-MM-DD (예: 2026-08-20). 생략하면 오늘.",
    )
    time: Optional[str] = Field(
        default=None,
        description="형식 HH:MM 24시간 KST (예: 22:00). 생략하면 22:00. "
                    "'밤 10시'→'22:00'.",
    )
    limit: int = Field(
        default=3, ge=1, le=10,
        description="돌려줄 곳 수. 정수 1~10, 기본 3. '세 군데'→3, '5곳'→5.",
    )


class EvaluatePlaceRequest(BaseModel):
    query: Optional[str] = Field(
        default=None,
        description="장소 이름·주소 문자열. 예: '새별오름' · '1100고지' · "
                    "'협재해수욕장'. lat/lon 과 택일 — 둘 중 하나는 반드시 있어야 한다.",
    )
    lat: Optional[float] = Field(
        default=None,
        description="위도(십진수, 제주 33.19~33.57). lon 과 함께 줄 때만 유효.",
    )
    lon: Optional[float] = Field(
        default=None, description="경도(십진수, 제주 126.14~126.98)."
    )
    origin: Optional[str] = Field(
        default=None,
        description="출발지 지명·주소. 주면 주행시간을 함께 답한다. "
                    "질문에 출발지가 있을 때만 넣는다. 예: '제주공항'.",
    )
    origin_lat: Optional[float] = Field(
        default=None, description="출발지 위도. origin_lon 과 함께 줄 때만."
    )
    origin_lon: Optional[float] = Field(default=None, description="출발지 경도.")
    date: Optional[str] = Field(
        default=None,
        description="형식 YYYY-MM-DD (예: 2026-08-20). 생략하면 오늘. '내일'이면 "
                    "오늘에 하루를 더한다. 구름 예보 지평은 약 7일이다.",
    )
    time: Optional[str] = Field(
        default=None,
        description="형식 HH:MM 24시간 KST (예: 22:00). scope='moment' 에서만 쓰인다 "
                    "(date·time 모두 생략 시 현재). '밤 10시'→'22:00', "
                    "'새벽 1시'→'01:00'. scope='night' 이면 무시.",
    )
    scope: str = Field(
        default="moment",
        description="'moment' 또는 'night' 둘 중 하나. 기본 'moment'. 한 시각을 "
                    "물으면 moment, 밤 전체 시간 수를 물으면 night.",
    )


class SpotDetailsRequest(BaseModel):
    name: str = Field(
        ...,
        description="관측지 이름(필수). 검증된 62곳 중 하나. 예: '새별오름' · "
                    "'매오름' · '1100고지 휴게소' · '천아계곡' · '관음사 야영장'. "
                    "띄어쓰기는 달라도 된다.",
    )
    origin: Optional[str] = Field(
        default=None,
        description="출발지 지명·주소. 주면 주행시간을 함께 답한다. "
                    "질문에 출발지가 있을 때만 넣는다.",
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
        summary="제주도 안의 별 관측지를 여러 곳 골라 추천한다 "
                "(검증된 62곳 중에서 · \"어디로 갈까\")",
    )
    def recommend_spots(
        request: RecommendSpotsRequest = RecommendSpotsRequest(),
    ) -> Dict[str, Any]:
        """제주도 안의 별 관측지를 여러 곳 골라 추천한다 — 추천·찾기·고르기·
        어디로 갈까·명소·관측지 목록 (recommend · find · where).

        [언제] 사용자가 장소를 **지목하지 않고** "어디로 갈까"를 물을 때.
               사람이 확인한 62곳에서 고른다.
        [다른 도구와] 한 장소를 지목해 "거기 별 보여?" → evaluate_place.
                     정해진 곳의 주차·화장실·반려견만 → spot_details.
        [사전 조건] 없다. **인자를 하나도 안 줘도 부를 수 있다** — 조건이 없으면
                   오늘 밤 22시 기준 상위 3곳이 나온다. 출발지나 조건을 되묻지 말고
                   아는 것만 채워 일단 부른다.
        [다음] 고른 곳의 접근성은 spot_details(name), 하늘 판정은 evaluate_place(query).

        출발지를 주면 **실제 도로를 따라간 주행시간**으로 자르고 순위에 반영한다
        (직선거리가 아니다 — 제주는 가운데가 한라산이라 직선거리로 자르면 산 반대편을
        추천하게 된다). 정체는 반영하지 않는 야간 자유주행 기준이다.

        [오류 대처]
        - max_drive_minutes 는 origin(또는 origin_lat+origin_lon)이 있어야 동작한다.
        - spots 가 비면 조건이 너무 좁은 것 → 조건을 하나 풀어 다시 부른다.
          지어내서 채우지 않는다.
        - verdict 가 "주소 확인 실패" 면 출발지를 못 찾은 것 → 좌표로 다시 부른다.

        [부르지 않는 경우]
        - **제주도 밖**의 장소·날씨(서울·부산·남산타워 등) → 부르지 말고 "제주 밖이라
          답할 수 없다"고 답한다. 이 서버는 제주도(위도 33.19~33.57 ·
          경도 126.14~126.98)만 다룬다.
        - 별 관측과 무관한 질문(맛집·숙소·렌터카·항공권·일반 상식·용어 설명).
        - 위 두 경우는 도구를 부르면 **틀린 답**이 된다.

        [예시]
        "제주공항에서 40분 안에 갈 만한 곳 3군데"
          → {"origin":"제주공항","max_drive_minutes":40,"limit":3}
        "제주 동쪽에서 별 보기 좋은 데" → {"region":"동"}
        "등산 안 하고 강아지랑 갈 수 있는 곳" → {"no_climb":true,"pets":true}

        추천 목록은 `spots` 배열에 있고 각 항목에 주행시간(`drive`)·도보
        (`walk_minutes`)·야간 출입(`night_access`)이 들어 있다. 답에 쓰는 값은
        결과에서 그대로 가져오고, 결과의 `map_url` 도 함께 옮긴다.
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
        summary="제주도 안에서 지목한 한 장소에 별이 보이는지 판정한다 "
                "(\"별 보여?\" · \"관측 가능?\")",
    )
    def evaluate_place(
        request: EvaluatePlaceRequest = EvaluatePlaceRequest(),
    ) -> Dict[str, Any]:
        """제주도 안에서 지목한 한 장소에 별이 보이는지 판정한다 — 별 보여?·
        관측 가능?·어때?·괜찮아?·볼 수 있어? (evaluate · check · visibility).

        [언제] 장소를 하나 지목했을 때. 이름(`query`) 또는 좌표(`lat`+`lon`) 중
               하나로 준다 — 둘 중 하나는 반드시 있어야 한다. 되묻지 말고 질문에서
               뽑아 넣는다.
        [다른 도구와] 장소를 지목하지 않은 "어디로 갈까" → recommend_spots.
                     하늘 말고 주차·화장실·반려견·야간 출입만 → spot_details.

        [부르지 않는 경우]
        - **제주도 밖**의 장소·날씨(서울·부산·남산타워 등) → 부르지 말고 "제주 밖이라
          답할 수 없다"고 답한다. 제주 범위(위도 33.19~33.57 · 경도 126.14~126.98)
          밖은 판정하지 않는다.
        - 별 관측과 무관한 질문(맛집·숙소·렌터카·일반 상식·용어 설명).
        - 위 두 경우는 도구를 부르면 **틀린 답**이 된다.

        [오류 대처] `verdict` 가 "주소 확인 실패" 면 지명을 못 찾은 것 →
        좌표(`lat`·`lon`)로, 또는 더 구체적인 지명으로 다시 부른다. 지어내서
        답하지 않는다.

        [예시]
        "오늘 밤 10시에 새별오름에서 별 보여?"
          → {"query":"새별오름","time":"22:00","scope":"moment"}
        "오늘 밤 1100고지 몇 시간이나 볼 수 있어?" → {"query":"1100고지","scope":"night"}
        "위도 33.46, 경도 126.83 지점 지금 어때?" → {"lat":33.46,"lon":126.83}

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
        `numbers.drive` 에 주행시간·거리가 실린다. 답에 쓰는 값은 결과에서 그대로
        가져오고, 결과의 `map_url` 도 함께 옮긴다 — 미등록 장소여서 "확인되지
        않았다"고 답할 때도 지도 주소는 옮긴다.
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
        summary="제주도 안의 검증된 관측지 한 곳의 주차·도보·야간 출입·반려동물·"
                "화장실·주의사항을 조회한다",
    )
    def spot_details(request: SpotDetailsRequest) -> Dict[str, Any]:
        """제주도 안의 검증된 관측지 한 곳의 **접근성·편의**를 조회한다 — 주차·화장실·
        반려견·강아지·야간 출입·도보·등산 난이도·입장료 (details · parking · pets).

        [언제] 이미 이름이 정해진 곳의 시설·접근성을 물을 때.
        [다른 도구와] **하늘 상태(구름·별 보이는지)는 답하지 않는다** →
                     그건 `evaluate_place` 소관이다. 장소를 고르는 것은
                     `recommend_spots` 소관이다.
        [사전 조건] `name` 이 검증된 62곳 목록에 있어야 한다(띄어쓰기는 달라도 된다).
                   이름을 모르면 `recommend_spots` 로 먼저 이름을 받는다.

        출발지를 주면 그곳까지의 주행시간도 함께 답한다.

        [오류 대처]
        - 이름을 못 찾으면 목록에 없는 곳이다 → `recommend_spots` 로 정확한 이름을
          받아 다시 부르거나, 하늘만 필요하면 `evaluate_place` 로 넘어간다.
        - 값이 "확인불가"·빈 값이면 **모르는 것이다.** 답에도 "확인되지 않았다"고
          쓴다. `pets` 가 "반려견 동반 불가능" 이면 가능하다고 답하지 않는다.

        [부르지 않는 경우] 제주도 밖의 장소, 별 관측과 무관한 질문(맛집·숙소 등).

        [예시]
        "매오름 많이 걸어야 해?" → {"name":"매오름"}
        "1100고지 휴게소 강아지 데려가도 돼?" → {"name":"1100고지 휴게소"}
        "제주공항에서 관음사 야영장까지 얼마나 걸려?"
          → {"name":"관음사 야영장","origin":"제주공항"}

        상세는 `spots` 배열의 한 항목에 전부 들어 있다. 답에 쓰는 값은 결과에서
        그대로 가져오고, 결과의 `map_url` 도 함께 옮긴다.
        """
        return tools.spot_details(
            name=request.name,
            origin=request.origin,
            origin_lat=request.origin_lat,
            origin_lon=request.origin_lon,
        )
