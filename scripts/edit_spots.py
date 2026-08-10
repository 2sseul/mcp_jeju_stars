"""관측지 데이터 편집 도구 — 지도에서 보고, 그 자리에서 채운다.

`data/jeju_spots.json` 은 106곳인데 **대부분의 칸이 비어 있다**. 주차 좌표·도보
시간·야간 개방·화장실·주의사항은 로드뷰 데스크 검증(`plan.md` P9)에서 채우기로 해
둔 것이고, 그 작업대가 이 도구다.

`review_parking.py` 가 "이 자리를 후보로 넣을까"를 판단하는 도구라면, 이쪽은 **이미
목록에 든 곳의 칸을 채우는** 도구다. 그래서 지도에 뿌리는 것도, 화면이 묻는 것도
다르다 — 저쪽은 주차장 1,557곳과 가로등 8만 개, 이쪽은 관측지 106곳과 **그 한 곳의
주변**(200m 화장실 · 1km 주차 후보 · 1km 가로등)이다.

한 화면에서 하는 일
--------------------------------------------------------------------------
    광공해   `core.darkness.assess_site` 세 신호를 그대로 — 리포트·판정과 같은 숫자
    화장실   `core.toilet` 반경 200m. 없으면 가장 가까운 곳까지의 거리를 말한다.
             쓸 만한 곳이 여럿이면 **여럿 지정한다**(아래)
    주차     `core.parking`(공영) + `core.places`(카카오) 1km 안 후보 — 눌러서 지정.
             들머리가 여럿이면 여럿 지정하고, 요금은 **자리마다** 적는다
    도보     주차 지점 → 관측 자리 경로를 **지도에서 직접 찍는다**(아래)
    로드뷰   지표로 안 잡히는 것(진입로·시야·조명)
    편집     위 칸들을 그 자리에서 적어 **바로 `jeju_spots.json` 에 쓴다**

도보 경로는 손으로 찍는 수밖에 없다
--------------------------------------------------------------------------
`data/road/jeju_road_darkness.npz` 는 63,662 세그먼트 전부가 차 다니는 길이다 —
`footway`·`path`·`steps` 가 **한 조각도 없다**(`core.road.NOT_DRIVABLE` 에 이름은
올라 있지만 수집되지 않았다). 지도 서비스도 오름 탐방로의 야간 도보 경로를 주지
않는다. 그래서 주차 지점에서 관측 자리까지 가는 선은 **사람이 위성·로드뷰를 보고
찍은 것**이 유일한 출처이고, 이 도구가 그 작업대다.

찍는 방식은 하나뿐이다 — **켠 뒤 지도를 우클릭한 순서가 곧 경로다**(켜는 것은 지도
우클릭 메뉴의 [경로 그리기] 나 오른쪽 `경로` 칸의 [그리기], 둘 중 아무거나). 찍는
동안에는 우클릭 메뉴가 뜨지 않는다 — 점마다 메뉴를 한 번 더 누르는 것은 20~30곳을
찍는 일에 그대로 손해다.

**양 끝은 코드가 놓는다.** 경로는 정의상 주차 자리에서 시작해 관측 자리에서 끝나고
두 좌표는 이미 지정돼 있으므로, 같은 자리를 눈대중으로 다시 찍게 하면 몇 m 씩
어긋난 시작·끝점만 쌓인다. 그래서 첫 점은 켤 때 주차 지점에 자동으로 놓이고(주차
지점이 아직 없으면 첫 우클릭이 첫 점이다), 끝낼 때는 **지도의 관측지 점을 누르거나**
`경로` 칸의 [관측 자리에서 끝내기] 를 누른다 — 관측 좌표가 마지막 점으로 들어가고
찍기가 꺼진다. 아직 다 못 찍었으면 [멈추기] 로 점은 그대로 두고 끄면 된다.

찍힌 것은 오른쪽 `경로` 칸이 순서대로 되짚어 준다 — 몇 번째 점이 어느 위·경도이고
앞 점에서 몇 m 인지. 잘못 찍은 점은 지도보다 이 목록에서 먼저 드러난다(겹쳐 보이는
두 점도 여기서는 +4m 로 보이고, 엉뚱한 데를 눌렀으면 +900m 로 튄다).

길은 여럿일 수 있고, 한 길은 구간으로 나뉜다
--------------------------------------------------------------------------
오르는 길이 하나뿐이라는 법이 없다 — 다랑쉬오름은 오른쪽으로 돌면 빨리 닿지만
가파르고, 왼쪽으로 돌면 오래 걸리지만 완만하다. 그 둘은 같은 경로의 변형이 아니라
**고를 수 있는 다른 길**이라 `walk_routes` 에 나란히 담는다(둘 이상이면 이름을
받는다 — 이름 없이는 고를 수가 없다). 길마다 길이·경사·구간이 따로 나오고, 그래서
탐방로 등급도 따로 나온다. 그게 길을 여럿 두는 이유다.

한 길 안에서도 밟는 것이 달라진다(데크계단 → 흙길 → 능선 돌길). 그것을 적는 자리가
길마다 하나씩 있는 **[상세설정]** 이다 — 구간을 두고 노면상태·암릉암반·특색을 적고,
등급 배점표를 고르는 지형도 여기서 고른다. [+ 구간] 을 한 번 누르면 길 전체가 한
구간이 되고, 밟는 것이 바뀌는 자리에서 하나 더 두면 그 점부터 다음 구간이다.

구간은 **자르는 자리**로만 잡는다 — `from` 은 그 구간이 시작하는 점 번호이고 끝은
다음 구간이 시작하기 직전이다. 구간마다 시작·끝을 따로 적게 하면 틈과 겹침이
생기고, 점을 하나 빼는 순간 둘이 어긋난다. 지도는 구간마다 노면 색으로 끊어 그린다.

점 목록은 **찍은 것을 되짚는 자리**로만 둔다(좌표와 앞 점에서의 거리, 그리고 잘못
찍은 점을 빼는 [빼기]). 한때 그 목록의 [나누기] 가 노면을 적는 유일한 입구였는데,
노면을 적으려고 점을 자른다는 것이 화면만 보고는 무슨 일인지 알 수가 없었다 —
자르는 것은 상세를 적다 보니 따라오는 결과이지 목적이 아니다.

데스크에서 그린 선이라 현장 미검증이다. **도보 시간은 적지 않는다** — 길이를 걸음
속도로 나눈 분은 계단·오르막에서 실제와 크게 벌어지는데 여기 그리는 선은 대부분
오름 등반로이고, 사람이 손으로 적어도 그건 눈대중이다. 힘든 정도를 말하는 것은
경사·거리·노면·암릉으로 내는 **탐방로 등급**이지 분이 아니다.

구간에 받는 것은 국립공원공단 탐방로 등급제의 두 항목(`surface`·`rock`)과 특색
한 줄이다. 한때 난이도 3단(쉬움·보통·어려움)이 함께 있었는데 뺐다 — 걷는 길의
'보통'은 적는 사람마다 다른 말이라 손으로 채울 수가 없었다. 노면과 암릉은 위성·
로드뷰로 **보이는 것**이라 누가 적어도 같은 답이 나온다.
경위는 `docs/decisions.md` §2.16 · §2.17.

노면이 관측지가 아니라 **구간에 붙는** 이유는, 한 길에서 그것이 바뀌기 때문이다 —
야자매트로 오르다 데크계단이 나오고 능선은 맨 흙길이다. 관측지에 한 값으로 적으면
그 길에서 제일 나쁜 자리 하나만 남고 어디서 그런지는 사라진다.

한 자리로 적을 수 없는 것들 — 주차 · 화장실
--------------------------------------------------------------------------
주차 지점(`parking`)과 화장실(`toilet`)은 **목록**이다. 이유는 서로 다르다.

주차는 오름 하나에 들머리가 갈리기 때문이고(다랑쉬오름의 남쪽 주차장 / 북동쪽
갓길), 그래서 요금도 자리마다 붙는다. 화장실은 **밤에 열려 있는 곳이 어디일지
모르기 때문**이다 — 주차장 옆 한 곳과 들머리 위 한 곳이 다 있는 자리에서 한 곳만
남기면, 가 보고 잠겨 있을 때 나머지가 파일에 없다. 어느 쪽을 쓸지는 그날 밤에
정할 일이라 여기서는 **본 것을 다 적는다**.

둘 다 `point` 의 세 상태(미확인 · 없음 · 자리)를 그대로 두고 자리만 여럿이 된
것이라, `false` 는 여전히 "가 봤는데 없다"이고 빈 목록이 아니다.

없는 키가 곧 '미확인'이다
--------------------------------------------------------------------------
이 파일의 규약(`meta.fields`)은 **모르는 항목은 키를 만들지 않는다**는 것이다. 그래야
남은 일이 파일에서 그대로 보인다. 그래서 화면에서 칸을 비우면 키를 지우고, 예·아니오
칸은 3단(미확인·예·아니오)이다 — "아니오"와 "아직 안 봤다"는 다른 말이다.

같은 규약이 **한 겹 안쪽에서도** 선다. 편의시설(`amenities`)은 항목마다 3단이라
`{"toilet": false}` 가 "가 봤는데 없다"이고, 키가 아예 없는 것이 "아직 안 봤다"이다 —
한때 '있다'만 적었는데, 그러면 화장실을 확인하러 간 관측지와 아직 안 본 관측지가
파일에서 같아 보인다. 주차 자리의 요금(`유료`·`무료`)도 마찬가지로 없으면 미확인이다.

컬럼을 늘릴 수 있다
--------------------------------------------------------------------------
채우다 보면 미리 정해 둔 칸으로는 모자란다(예: '입장 차단기', '버스 막차'). [+ 컬럼]
으로 키·이름·형식을 정해 추가하면 그 자리에서 입력칸이 생기고, 정의는
`meta.columns` 에 남아 다음에 열 때도 그대로 선다. **값을 적은 관측지에만** 키가
생기므로 규약은 그대로다.

실행 — 카카오 JavaScript 앱키가 필요하다(`review_parking.py` 와 같은 키·같은 포트):

    uv run python -m scripts.edit_spots
    → http://localhost:8765
"""

from __future__ import annotations

import json
import math
import re
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import numpy as np

from scripts import env
from scripts.review_parking import Server, site_fields
from server import path
from server.core import (
    elevation,
    lamps,
    parking,
    places,
    toilet,
    trail,
)

#: 카카오는 **등록된 Web 도메인**에만 SDK 를 내준다. 포트가 다르면 다른 도메인이라
#: 거부되므로 `review_parking.py` 와 같은 포트를 쓴다 — 등록은 한 번이면 된다.
#: (두 도구를 동시에 띄울 수는 없다. `Server` 가 겹치면 실패하고 그렇게 말한다.)
_PORT = 8765

_KEY_VAR = "KAKAO_JAVASCRIPT_API_KEY"

#: 주변 조회 반경. 화장실은 `core.toilet.WALK_M`(걸어서 2~3분), 주차·가로등은 1km —
#: 가로등 집계 반경(`core.lamps.FAR_M`)과 같은 눈금이라 화면과 숫자가 어긋나지 않는다.
_PARKING_M = lamps.FAR_M
_LAMP_M = lamps.FAR_M

#: 가게만 반경이 다르다(3km). 걸어갈 곳이 아니라 **가는 길에 들르는 곳**이라
#: 걷는 거리로 자르면 "근처에 아무것도 없다"만 나온다 — 중산간 관측지는 대부분
#: 1km 안에 가게가 없다.
_STORE_M = 3_000.0

#: 주변 목록에 싣는 최대 개수. 지도에 찍는 가로등도 이만큼에서 끊고, **끊었다는
#: 사실을 화면에 적는다** — 조용히 자르면 "1km 안에 이게 전부"로 읽힌다.
_PARKING_LIMIT = 8
_STORE_LIMIT = 6
_LAMP_LIMIT = 400

#: 같은 주차장이 공영 목록과 카카오 검색에 다 있을 때 뒤엣것을 버리는 거리(m).
_PARKING_DEDUP_M = 30.0

# --- 색 ----------------------------------------------------------------------
#: 관측지 점 색 — 어둡기 등급 상한(`darkness.cap_of`)의 순서형 3단. 어두운 지도
#: 표면 위에서 읽으므로 역방향(어두운 곳일수록 밝은 단계)이다. `review_parking.py`
#: 의 4단 램프와 같은 계열이라 두 도구를 오가도 색이 같은 뜻으로 읽힌다.
_CAP_COLOR = {"최적": "#ffffff", "양호": "#9fe8c8", "밝은 별 한정": "#4fb98a"}
_NO_GRID_COLOR = "#898781"

#: 주변 레이어. 가로등 주황은 `build_light_map.py`·`review_parking.py` 와 같은 값이다.
_TOILET_COLOR = "#6da7ec"
_PARKING_COLOR = "#ffd479"
_STORE_COLOR = "#c98ae0"
_LAMP_COLOR = "#d95926"
_PICK_COLOR = "#4fb98a"
#: 도보 경로 선. 위성 영상 위에 얹히는 유일한 선이라 점 색들과 계열을 달리한다.
#: 노면을 아직 안 적은 구간이 이 색이다.
_ROUTE_COLOR = "#4fd6e0"

#: 구간에 적는 것은 **국립공원공단 탐방로 등급제**의 두 항목이다 — 노면상태와 암릉·암반.
#: 낱말도 배점도 `server/core/trail.py` 가 원문 그대로 들고 있고, 여기서는 화면에 뿌릴
#: 색과 설명만 붙인다. 눈금을 두 곳에 적으면 언젠가 둘이 갈린다.
#:
#: 한때 여기 우리가 만든 3값(정비·계단·맨땅)이 있었는데 걷어냈다 — 근거 있는 눈금이
#: 이미 있는데 자체 눈금을 쓸 이유가 없고, 실제로 그 3값은 공식 축과 어긋나 있었다
#: (공식 노면 축에는 돌길이 있고 계단이 없다). 경위는 `docs/decisions.md` §2.17.
#:
#: 색은 위성 영상 위에서 읽혀야 하므로 다섯 다 밝은 값이다. 노면은 포장 → 흙 → 돌로
#: **순서형**이라 색도 순서형으로 둔다(연녹 → 흙색 → 연빨강).
_SURFACE_COLOR = dict(zip(
    trail.SURFACE,
    ("#6fe3a0", "#cfe07a", "#e0c15c", "#e09a5c", "#ff7a6b"),
))

#: 낱말이 무엇을 가리키는지 — 원문 표의 설명을 그대로 옮긴다. 화면이 단추에 붙인다.
#: '비교적'이 50~80% 라는 것은 눌러 보고 알 것이 아니다.
_SURFACE_HELP = dict(zip(trail.SURFACE, (
    "단단·매끈한 포장 — 목재데크, 콘크리트, 아스콘, 보도블럭 등",
    "거의 대부분 흙으로 노면이 이루어진 길 (흙으로 정비된 길 포함)",
    "비교적 흙으로 노면이 이루어진 길 (50~80%)",
    "비교적 돌로 노면이 이루어진 길 (50~80%)",
    "거의 대부분 돌로 노면이 이루어진 길 — 너덜길, 계곡돌길 등",
)))

#: 암릉·암반 설명. 원문 표 그대로다.
_ROCK_HELP = dict(zip(trail.ROCK, (
    "암릉·암반 없음",
    "약간의 암반이 있을 수 있음",
    "목재계단이 설치된 암릉·암반",
    "로프, 사다리 등이 설치된 암릉·암반",
    "손을 이용해서 오르내리는 암릉·암반",
)))

#: 지형 설명. 경사도·거리 배점표가 이것으로 갈린다 — 같은 1km 가 둘레길에서는 1점,
#: 사면부에서는 3점이다. 오름 등반로는 대개 사면부지만 코드가 짐작하지 않는다.
_TERRAIN_HELP = {
    trail.RIDGE: "봉우리와 봉우리를 잇는 길, 또는 산기슭을 도는 둘레길",
    trail.SLOPE_SIDE: "산비탈을 곧장 오르는 길 — 오름 등반로는 대개 이쪽",
}

#: 주차 자리마다 받는 요금. 액수가 아니라 **돈을 받는가**만 둔다 — 밤에 대는 자리라
#: 요금표가 있어도 무인정산이 도는지는 로드뷰로 알 수 없고, 계획이 갈리는 것은
#: '현금을 챙겨야 하는가'까지다. 액수를 아는 자리는 `요금` 칸에 적는다.
#: 없으면 미확인이다(이 파일의 규약 — 없는 키가 곧 '아직 안 봤다').
PARKING_FEE = ("무료", "유료")


# --- 컬럼 --------------------------------------------------------------------

@dataclass(frozen=True)
class Column:
    """편집 화면의 칸 하나.

    type 은 화면이 무엇을 그릴지와 서버가 값을 어떻게 받을지를 함께 정한다.

        text·textarea  문자열              choice  문자열(기존 값 추천, 자유 입력)
        number         숫자                bool    3단(미확인·예·아니오)
        list           문자열 목록(줄 단위) flags   {이름: 3단} 묶음(편의시설)
        point          {name, lat, lon}    coords  관측지 자신의 lat·lon
        points         자리 여럿 — `point` 의 세 상태 그대로에 좌표만 여럿(화장실)
        parking        주차 자리 여럿 — `points` 에 자리마다 요금이 더 붙는다
        routes         도보 경로 묶음        — 지도에서 찍는 선(아래)
    """

    key: str
    label: str
    type: str
    help: str = ""
    #: `choice` 칸에서 코드가 미리 아는 보기. 화면은 여기에 **파일에 이미 쓰인 값**을
    #: 합쳐 추천한다 — 새로 만든 칸은 파일에 값이 없어 추천이 비기 때문이다.
    #: 자유 입력은 그대로 열려 있다.
    options: tuple[str, ...] = ()


#: 미리 정해 둔 칸. 이미 파일에 쓰이고 있는 키들이라 형식도 거기서 왔다.
#: 사람이 늘린 칸은 여기가 아니라 `meta.columns` 에 남는다 — 코드가 아는 것과
#: 데이터가 늘린 것을 섞지 않는다.
_BUILTIN: tuple[Column, ...] = (
    Column("coords", "관측 좌표", "coords", "지도 우클릭 → [관측 좌표로] 로 옮긴다"),
    Column("coord_confidence", "좌표 신뢰도", "choice", "high · medium · low"),
    Column("name_ko", "이름", "text"),
    Column("name_en", "영문 이름", "text"),
    Column("region", "지역", "choice"),
    Column("type", "유형", "choice"),
    Column("why", "선정 이유", "textarea", "추천 문구에 그대로 나갈 한 문장"),
    Column("notes", "비고", "textarea", "좌표 근거·정성적 광공해 서술 등"),
    Column("elevation_m", "해발높이(m)", "number",
           "이 좌표 지점의 값 — 오름 공표 표고가 아니다. "
           "scripts/fetch_elevation.py 가 채운다"),
    Column("slope_deg", "경사도(°)", "number",
           "주변 90m 격자의 경사. 삼각대·주차 자리가 비탈인지"),
    Column("access", "접근", "text", "차로 어디까지 들어가나"),
    Column("parking", "주차 지점", "parking",
           "주차 후보에서 [지정] · 지도 우클릭 → [주차 지점으로] · 없으면 [없음]. "
           "들머리가 갈리면 여럿 지정하고 요금은 자리마다 적는다"),
    Column("walk_routes", "도보 경로", "routes",
           "위 [경로] 칸에서 찍는다 — 우클릭한 순서가 곧 경로이고, "
           "첫 점은 주차 지점, 끝 점은 관측 자리에 코드가 놓는다. "
           "길이 갈리면 경로를 여러 개 둔다"),
    Column("walk_type", "도보 유형", "choice", "주차 지점에서 관측 자리까지의 오르내림",
           options=("평지", "등반", "차량")),
    Column("toilet", "화장실 위치", "points",
           "쓸 만한 곳을 다 적는다 — 밤에 어느 쪽이 열려 있을지는 여기서 알 수 없다. "
           "목록에 없으면 지도 우클릭으로 찍고, 가 봤는데 없으면 [없음]"),
    Column("store", "가게 위치", "point",
           "밤에 들를 가게. 목록에 없으면 지도 우클릭으로 찍고, 없으면 [없음]"),
    Column("amenities", "편의시설", "flags",
           "좌표까지는 모르고 '있다'만 아는 것. 자리를 특정했으면 위 두 칸에 적는다"),
    Column("hours", "운영시간", "text"),
    Column("fee", "요금", "text"),
    Column("night_access", "야간 개방", "text", "제한이 있으면 그 내용과 출처"),
    Column("rest_year", "자연휴식년제", "bool",
           "해당하면 기간·고시 출처를 야간 개방 칸에 함께 적는다"),
    Column("pets", "반려동물", "choice", "출입 가부",
           options=("가능", "불가", "목줄 착용 시 가능")),
    Column("campsite", "야영 가능", "bool"),
    Column("cautions", "주의사항", "list", "한 줄에 하나"),
    Column("sources", "출처 URL", "list", "한 줄에 하나"),
)

#: 화면에서 만들 수 있는 칸 형식. 구조가 걸린 것(point·coords·flags)은 뺀다 —
#: 그건 화면과 서버가 짝으로 알아야 하는 것이라 데이터로 늘릴 수 없다.
ADDABLE = ("text", "textarea", "number", "choice", "bool", "list")

#: 새 컬럼 키의 형식. 이 파일의 다른 키들과 같은 모양(snake_case, ASCII)이어야
#: 나중에 파이썬에서 `spot["key"]` 로 꺼낼 때 눈에 걸리는 것이 없다.
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,29}$")

#: 편집하지 않는 키 — 자동 발굴 표식은 사람이 지우거나 붙일 것이 아니다.
_READONLY = ("discovery",)

#: 좌표 허용 범위. 파일 자신이 적어 둔 제주 경계(`meta.jeju_bounds`)에 여유를 준 값 —
#: `core.lamps`·`core.parking`·`core.toilet` 과 같은 경계다.
_BOUNDS = {"lat_min": 33.0, "lat_max": 33.7, "lon_min": 126.0, "lon_max": 127.1}

#: 기록 시각에 쓰는 표준시.
KST = timezone(timedelta(hours=9))


# --- 데이터셋 -----------------------------------------------------------------

class Spots:
    """`data/jeju_spots.json` 한 벌. 누를 때마다 통째로 다시 쓴다(106곳이라 괜찮다).

    임시 파일에 쓴 뒤 바꿔치기해서, 중간에 끊겨도 반쪽짜리 JSON 이 남지 않게 한다.
    들여쓰기 2칸·`ensure_ascii=False` 는 원본과 같은 서식이라 저장해도 diff 가
    **고친 줄에만** 난다.
    """

    def __init__(self, file):
        self._file = file
        self._doc = json.loads(file.read_text(encoding="utf-8"))

    @property
    def spots(self) -> list[dict]:
        return self._doc["spots"]

    @property
    def meta(self) -> dict:
        return self._doc["meta"]

    def columns(self) -> list[Column]:
        """코드가 아는 칸 + 사람이 늘린 칸."""
        extra = [
            Column(c["key"], c["label"], c["type"], c.get("help", ""))
            for c in self._doc["meta"].get("columns", [])
        ]
        return [*_BUILTIN, *extra]

    def add_column(self, key: str, label: str, type_: str, help_: str) -> Column:
        column = Column(key, label, type_, help_)
        self._doc["meta"].setdefault("columns", []).append(
            {"key": key, "label": label, "type": type_, "help": help_}
        )
        self.flush()
        return column

    def flush(self) -> None:
        tmp = self._file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._doc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._file)


# --- 값 받기 ------------------------------------------------------------------

def _text(value) -> str:
    return str(value).strip() if value is not None else ""


def coerce(column: Column, value):
    """화면이 보낸 값 → 파일에 넣을 값. 비었으면 None(= 키를 지운다).

    화면을 믿지 않는다. 형식이 어긋나면 `ValueError` 로 되돌려 **저장 자체를**
    막는다 — 반쯤 이상한 값이 들어간 파일이 제일 나쁘다.
    """
    if column.type in ("text", "textarea", "choice"):
        return _text(value) or None

    if column.type == "number":
        text = _text(value)
        if not text:
            return None
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError(f"{column.label}: '{text}' 은 숫자가 아닙니다") from exc
        return int(number) if number.is_integer() else number

    if column.type == "bool":
        if value is None or value == "":
            return None
        if not isinstance(value, bool):
            raise ValueError(f"{column.label}: 예·아니오가 아닙니다")
        return value

    if column.type == "list":
        items = [line.strip() for line in (value or []) if str(line).strip()]
        return items or None

    if column.type == "flags":
        # 항목마다 세 상태다 — 키 없음(미확인) · true(있다) · false(가 봤는데 없다).
        # 이 파일의 "없는 키가 곧 미확인"이 사전 한 겹 안쪽에서도 그대로 선다.
        # 한때 true 만 남기고 false 를 버렸는데, 그러면 확인하러 간 관측지와 아직
        # 안 본 관측지가 파일에서 같아 보인다.
        flags = {}
        for name, flag in (value or {}).items():
            if flag is None or flag == "":
                continue
            if not isinstance(flag, bool):
                raise ValueError(f"{column.label} {name}: 예·아니오가 아닙니다")
            flags[name] = flag
        return flags or None

    if column.type in ("points", "parking"):
        # `point` 의 세 상태에 **여럿**이 더해진 것 — 키 없음(미확인) ·
        # false(확인했고 없다) · 자리 목록. 빈 목록은 값이 아니라 미확인이다.
        if value is False:
            return False
        items = list(value or [])
        if not items:
            return None
        one = _parking if column.type == "parking" else _place
        return [one(item, f"{column.label} {i}") for i, item in enumerate(items, 1)]

    if column.type == "point":
        # 세 상태다 — 키 없음(미확인) · false(확인했고 없다) · 좌표(여기 있다).
        # "없다"를 못 적으면 다 본 관측지와 아직 안 본 관측지가 파일에서 같아 보인다.
        if value is False:
            return False
        if not value:
            return None
        return _place(value, column.label)

    if column.type == "coords":
        lat, lon = _coord(
            (value or {}).get("lat"), (value or {}).get("lon"), column.label
        )
        return {"lat": lat, "lon": lon}

    if column.type == "routes":
        # 비면 키를 지운다(= 아직 안 그렸다).
        routes = list(value or [])
        if not routes:
            return None
        # 길이 갈리면(다랑쉬오름의 급경사길·완만한 길) 이름 없이는 고를 수가 없다.
        # 하나뿐이면 부를 일이 없으므로 이름도 묻지 않는다.
        named = len(routes) > 1
        out = [_route(r, f"{column.label} {i}", named) for i, r in enumerate(routes, 1)]
        names = [r.get("name") for r in out if r.get("name")]
        if len(set(names)) != len(names):
            raise ValueError(f"{column.label}: 경로 이름이 겹칩니다")
        return out

    raise ValueError(f"{column.label}: 모르는 형식 {column.type}")


def _place(value, label: str) -> dict:
    """자리 하나 — 이름과 좌표. `point` · `points` · `parking` 이 함께 쓴다.

    이름이 비는 것은 막지 않는다. 지도에서 찍은 갓길·간이화장실은 부를 이름이
    없는 경우가 있고, 그때 필요한 것은 좌표다.
    """
    value = value or {}
    lat, lon = _coord(value.get("lat"), value.get("lon"), label)
    return {"name": _text(value.get("name")), "lat": lat, "lon": lon}


def _parking(value, label: str) -> dict:
    """주차 자리 하나 — 어디이고, 돈을 받는가.

    자리가 여럿인 이유는 오름 하나에 들머리가 여럿이기 때문이다(다랑쉬오름은
    남쪽 주차장과 북동쪽 갓길로 갈린다). 그 둘은 같은 자리의 이표기가 아니라
    **고를 수 있는 다른 들머리**이고, 요금도 따로 붙는다 — 한쪽만 유료인 경우가
    있어서 관측지에 요금 한 값을 적으면 어느 자리 말인지 알 수 없다.

    화장실(`points`)이 요금 없이 같은 모양인 것은, 여럿인 이유가 달라서다 —
    거기서는 **밤에 어느 곳이 열려 있을지 모르는 것**이 이유다(모듈 설명 참고).
    """
    lot = _place(value, label)
    fee = _text((value or {}).get("fee"))
    if fee:
        if fee not in PARKING_FEE:
            raise ValueError(
                f"{label}: 모르는 요금 '{fee}' — {' · '.join(PARKING_FEE)}"
            )
        lot["fee"] = fee
    return lot


def _route(value, label: str, named: bool) -> dict:
    """도보 경로 하나 — 점들과, 그 위를 자른 구간들.

    한 점짜리 선은 없으므로 두 점 미만은 화면이 잘못 보낸 것이라 보고 저장을 막는다
    — 반쪽 경로가 파일에 남으면 지도에는 그려지는데 갈 수는 없는 선이 된다.
    """
    value = value or {}
    name = _text(value.get("name"))
    if named and not name:
        raise ValueError(f"{label}: 경로가 둘 이상이면 이름이 있어야 합니다")

    points = list(value.get("points") or [])
    if len(points) < 2:
        raise ValueError(f"{label}: 점이 둘은 있어야 합니다")
    route: dict = {}
    if name:
        route["name"] = name
    route["points"] = []
    for i, point in enumerate(points, 1):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"{label}: {i}번째 점이 [위도, 경도] 가 아닙니다")
        lat, lon = _coord(point[0], point[1], f"{label} {i}번째 점")
        route["points"].append([lat, lon])

    terrain = _text(value.get("terrain"))
    if terrain:
        if terrain not in trail.TERRAIN:
            raise ValueError(
                f"{label}: 모르는 지형 '{terrain}' — {' · '.join(trail.TERRAIN)}"
            )
        route["terrain"] = terrain

    segments = _segments(value.get("segments"), len(route["points"]), label)
    if segments:
        route["segments"] = segments
    _measure(route)
    return route


#: 배치가 아니라 **저장할 때 그 자리에서** 잰다. 표고 격자가 파일 하나라
#: (`core/elevation.py`) 네트워크가 없고, 그래서 값이 선보다 늦을 일이 없다.
#:
#:     climb_m    출발점 → 도착점 순 고도차(m). 오르막이면 양수
#:     slope_deg  그 고도차를 경로 길이로 나눈 전체 평균 경사(도)
#:     over_m     경로 길이(m)
#:
#: 잴 수 없으면(격자 두 칸보다 짧거나 격자 밖) **키를 만들지 않는다** — 이 파일의
#: 규약대로 없는 키가 곧 '못 쟀다'이고, 0 으로 채우면 '평평하다'로 읽힌다.
_MEASURED = ("climb_m", "slope_deg", "over_m")


def _measure(route: dict) -> None:
    """경로와 그 구간들의 잰 값을 채운다. 사람이 적는 값이 아니다."""
    points = route["points"]
    for key in _MEASURED:
        route.pop(key, None)

    climb = elevation.climb_m(points)
    slope = elevation.slope_deg(points)
    if climb is not None and slope is not None:
        route["climb_m"] = climb
        route["slope_deg"] = slope
        route["over_m"] = round(elevation.length_m(points), 1)

    # 구간마다의 경사. 짧은 구간은 못 재고, 못 잰 것은 비워 둔다 — 어디가 가파른지가
    # 여기서 보여야 사람이 구간을 어디서 끊을지 정할 수 있다.
    segments = route.get("segments") or []
    for i, segment in enumerate(segments):
        start = segment["from"]
        end = segments[i + 1]["from"] if i + 1 < len(segments) else len(points) - 1
        piece = points[start:end + 1]
        segment.pop("slope_deg", None)
        segment.pop("over_m", None)
        got = elevation.slope_deg(piece)
        if got is not None:
            segment["slope_deg"] = got
            segment["over_m"] = round(elevation.length_m(piece), 1)


#: 구간이 **무언가를 말하고 있다**고 볼 키들. 자른 자리(`from`)만 있는 구간은
#: 아무것도 말하지 않으므로 세지 않는다.
_SAID = frozenset(("surface", "rock", "note"))


def _segments(value, count: int, label: str) -> list[dict]:
    """경로를 자른 구간들. 구간은 **자르는 자리**로만 잡는다.

    `from` 은 그 구간이 시작하는 점 번호(0부터)다. 끝은 다음 구간이 시작하기 직전,
    마지막 구간은 경로 끝이다 — 구간마다 시작·끝을 따로 적게 하면 틈과 겹침이
    생기고, 점을 하나 빼는 순간 둘이 어긋난다.

    노면도 설명도 없는 구간은 버린다. 자른 자리만 남으면 그건 아무것도 말하지
    않는 구분이라, 파일에도 화면에도 남길 것이 없다.
    """
    segments = list(value or [])
    if not segments:
        return []

    out = []
    previous = -1
    for i, raw in enumerate(segments, 1):
        raw = raw or {}
        try:
            start = int(raw.get("from"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}: {i}번째 구간의 시작 점이 없습니다") from exc
        if not 0 <= start < count:
            raise ValueError(
                f"{label}: {i}번째 구간이 없는 점({start + 1}번)에서 시작합니다"
            )
        if start <= previous:
            raise ValueError(f"{label}: 구간이 찍은 순서대로 있지 않습니다")
        previous = start

        surface = _text(raw.get("surface"))
        if surface and surface not in trail.SURFACE:
            raise ValueError(
                f"{label}: 모르는 노면 '{surface}' — {' · '.join(trail.SURFACE)}"
            )
        rock = _text(raw.get("rock"))
        if rock and rock not in trail.ROCK:
            raise ValueError(
                f"{label}: 모르는 암릉·암반 '{rock}' — {' · '.join(trail.ROCK)}"
            )
        segment = {"from": start}
        if surface:
            segment["surface"] = surface
        if rock:
            segment["rock"] = rock
        note = _text(raw.get("note"))
        if note:
            segment["note"] = note
        out.append(segment)

    if out[0]["from"] != 0:
        raise ValueError(f"{label}: 첫 구간은 경로 첫 점에서 시작해야 합니다")
    # 아무것도 안 적힌 구간만 남았으면 자른 적이 없는 것과 같다.
    if not any(_SAID & s.keys() for s in out):
        return []
    return out


def _coord(lat, lon, label: str) -> tuple[float, float]:
    """좌표를 숫자로 바꾸고 제주 범위 안인지 본다.

    범위 밖 좌표를 받아 두면 그 관측지는 어둡기 격자 밖으로 나가 **판정이 조용히
    사라진다**. 화면에서 잘못 찍은 것을 여기서 막는다.
    """
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: 좌표가 숫자가 아닙니다") from exc
    if not (_BOUNDS["lat_min"] <= lat <= _BOUNDS["lat_max"]):
        raise ValueError(f"{label}: 위도 {lat} 는 제주 밖입니다")
    if not (_BOUNDS["lon_min"] <= lon <= _BOUNDS["lon_max"]):
        raise ValueError(f"{label}: 경도 {lon} 는 제주 밖입니다")
    return lat, lon


def apply(spot: dict, columns: list[Column], values: dict) -> None:
    """받은 값들을 관측지 하나에 반영한다. 빈 값은 **키를 지운다**."""
    by_key = {c.key: c for c in columns}
    for key, raw in values.items():
        column = by_key.get(key)
        if column is None:
            raise ValueError(f"모르는 칸: {key}")
        if key in _READONLY:
            raise ValueError(f"{column.label} 은 고칠 수 없습니다")

        value = coerce(column, raw)
        if column.type == "coords":
            spot["lat"], spot["lon"] = value["lat"], value["lon"]
        elif value is None:
            spot.pop(key, None)
        else:
            spot[key] = value


# --- 주변 --------------------------------------------------------------------

def _distance_m(lat: float, lon: float, lat2: float, lon2: float) -> float:
    """등거리 평면 근사(`core.lamps._distances_m` 와 같은 근사). 1km 규모면 충분하다."""
    dy = (lat2 - lat) * lamps.KM_PER_DEG
    dx = (lon2 - lon) * lamps.KM_PER_DEG * math.cos(math.radians(lat))
    return math.hypot(dx, dy) * 1000.0


def toilets_near(lat: float, lon: float) -> dict:
    """반경 200m 화장실. 없으면 **가장 가까운 곳까지의 거리**를 대신 말한다.

    "없음"과 "300m 밖에 있음"은 관측 계획이 달라지므로 둘을 같은 답으로 두지 않는다.
    """
    near = toilet.near(lat, lon)
    nearest = toilet.nearest(lat, lon)
    return {
        "radiusM": toilet.WALK_M,
        "list": [
            {
                "name": n.toilet.name,
                "kind": n.toilet.kind,
                "lat": n.toilet.lat,
                "lon": n.toilet.lon,
                "distanceM": round(n.distance_m),
                "hours": n.toilet.hours,
                "bell": n.toilet.bell,
                "phone": n.toilet.phone,
                "address": n.toilet.address,
            }
            for n in near
        ],
        "nearest": None if nearest is None else {
            "name": nearest.toilet.name,
            "distanceM": round(nearest.distance_m),
            "hours": nearest.toilet.hours,
        },
    }


def parking_near(lat: float, lon: float) -> dict:
    """1km 안 주차 후보 — 공영주차장(원본)과 카카오 검색 장소를 한 목록으로.

    같은 주차장이 두 출처에 다 있기도 해서(예: 1100고지휴게소 주차장), 가까운 것부터
    담으며 **30m 안에 이미 담은 것이 있으면 버린다** — 지도에 같은 자리가 두 번
    찍히면 사람이 같은 곳을 두 번 판단하게 된다.
    """
    found = []
    for lot in parking.lots():
        distance = _distance_m(lat, lon, lot.lat, lot.lon)
        if distance <= _PARKING_M:
            found.append(
                {
                    "name": lot.name,
                    "lat": lot.lat,
                    "lon": lot.lon,
                    "distanceM": round(distance),
                    "source": "공영",
                    "detail": f"{lot.kind} · {lot.slots:,}면 · {lot.fee}",
                    "url": "",
                }
            )
    for place in places.places():
        if place.source != "parking":
            continue
        distance = _distance_m(lat, lon, place.lat, place.lon)
        if distance <= _PARKING_M:
            found.append(
                {
                    "name": place.name,
                    "lat": place.lat,
                    "lon": place.lon,
                    "distanceM": round(distance),
                    "source": "카카오",
                    "detail": place.category,
                    "url": place.url,
                }
            )

    found.sort(key=lambda row: row["distanceM"])
    kept: list[dict] = []
    for row in found:
        if any(
            _distance_m(row["lat"], row["lon"], k["lat"], k["lon"]) <= _PARKING_DEDUP_M
            for k in kept
        ):
            continue
        kept.append(row)
    return {"total": len(kept), "list": kept[:_PARKING_LIMIT], "radiusM": _PARKING_M}


def stores_near(lat: float, lon: float) -> dict:
    """3km 안 편의점 — 가까운 순.

    화장실과 달리 **걸어갈 곳이 아니다**. 관측 전에 들러 뭘 사 오는 곳이라 거리
    기준이 다르고, 그래서 반경도 목록도 따로 둔다. 야간 영업 여부는 카카오가
    주지 않으므로 적지 않는다 — 모르는 것을 아는 척하지 않는다.
    """
    found = [
        {
            "name": place.name,
            "lat": place.lat,
            "lon": place.lon,
            "distanceM": round(_distance_m(lat, lon, place.lat, place.lon)),
            "address": place.address,
            "url": place.url,
        }
        for place in places.places()
        if place.source == "store"
        and _distance_m(lat, lon, place.lat, place.lon) <= _STORE_M
    ]
    found.sort(key=lambda row: row["distanceM"])
    return {"total": len(found), "list": found[:_STORE_LIMIT], "radiusM": _STORE_M}


def lamps_near(lat: float, lon: float) -> dict:
    """1km 안 가로등 좌표. 지도에 찍을 것이라 개수를 끊고, 끊었다는 사실을 함께 낸다."""
    lamp_lat, lamp_lon = lamps.points()
    dy = (lamp_lat - lat) * lamps.KM_PER_DEG
    dx = (lamp_lon - lon) * lamps.KM_PER_DEG * math.cos(math.radians(lat))
    distance = np.hypot(dx, dy) * 1000.0
    hit = np.flatnonzero(distance <= _LAMP_M)
    order = hit[np.argsort(distance[hit])][:_LAMP_LIMIT]
    return {
        "total": int(hit.size),
        "points": [
            [round(float(lamp_lat[i]), 6), round(float(lamp_lon[i]), 6)] for i in order
        ],
    }


def context(lat: float, lon: float) -> dict:
    """한 지점의 광공해 + 주변 전부. 관측지를 고르거나 지도를 우클릭할 때 부른다.

    도로는 싣지 않는다. 한때 도착 전 1km 의 길을 잰 값(`core.road`)으로 늘어놓고
    사람이 `도로 상태` 칸에 옮겨 적게 했는데, 그 칸을 걷어내면서 함께 뺐다 —
    **밤에 초행으로 갈 수 있는지는 출발지가 있어야 나오는 답**이고, 관측지 한 곳에
    한 줄로 적어 둘 것이 아니다. 그 판단은 출발지를 받는 별도 도구가 맡는다.
    """
    return {
        "site": site_fields(lat, lon),
        "toilets": toilets_near(lat, lon),
        "parking": parking_near(lat, lon),
        "stores": stores_near(lat, lon),
        "lamps": lamps_near(lat, lon),
    }


# --- 화면에 실어 보낼 것 --------------------------------------------------------

def choices(spots: list[dict], columns: list[Column]) -> dict[str, list[str]]:
    """`choice` 칸의 추천 목록 — **파일에 이미 있는 값**에서 뽑는다.

    분류 체계를 코드에 박아 두면 데이터가 늘 때마다 코드를 고쳐야 하고, 그러다
    화면에 없는 값이 파일에만 있는 상태가 된다. 자유 입력은 그대로 열어 둔다.
    사람이 늘린 `choice` 칸도 같은 규칙으로 자란다 — 처음엔 비어 있다가 한 곳에
    적으면 다음부터 추천에 뜬다.
    """
    out: dict[str, list[str]] = {}
    for column in columns:
        if column.type != "choice":
            continue
        values = {
            spot[column.key] for spot in spots
            if isinstance(spot.get(column.key), str)
        }
        # 코드가 아는 보기를 앞에, 파일에서 자란 값을 뒤에. 새 칸도 처음부터
        # 고를 것이 있고, 사람이 새로 적은 말은 다음부터 추천에 낀다.
        extra = sorted(values - set(column.options))
        out[column.key] = [*column.options, *extra]
    return out


def flag_keys(spots: list[dict]) -> list[str]:
    """편의시설(`amenities`)에 쓰인 항목 이름들. 화면이 이만큼 칸을 세운다."""
    found: set[str] = set()
    for spot in spots:
        value = spot.get("amenities")
        if isinstance(value, dict):
            found.update(value)
    return sorted(found)


def spot_row(index: int, spot: dict) -> dict:
    """지도·목록이 쓰는 한 줄. 값 전체를 그대로 싣고 어둡기는 여기서 잰다."""
    site = site_fields(spot["lat"], spot["lon"])
    return {"index": index, "values": spot, "site": site}


# --- HTML ---------------------------------------------------------------------

_HTML = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>제주 관측지 편집</title>
<style>
  :root {
    --panel: rgba(20, 20, 19, 0.93);
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --ink-muted: #898781;
    --hairline: rgba(255, 255, 255, 0.12);
    --save: #4fb98a;
    --warn: #ffd479;
    --danger: #d9534f;
    --link: #9ec5f4;
  }
  html, body { margin: 0; height: 100%; background: #0d0d0d; overflow: hidden; }
  body {
    font: 13px/1.5 system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
    color: var(--ink);
  }
  #map { position: absolute; inset: 0; z-index: 0; background: #0d0d0d; }

  .panel {
    background: var(--panel); border: 1px solid var(--hairline);
    border-radius: 10px; padding: 12px 14px;
    backdrop-filter: blur(6px); box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
  }
  .rail {
    position: absolute; top: 12px; bottom: 12px; z-index: 10;
    display: flex; flex-direction: column; gap: 10px;
  }
  .rail.left { left: 12px; width: 286px; }
  .rail.right { right: 12px; width: 340px; }

  h2 { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: var(--ink-muted);
       text-transform: uppercase; letter-spacing: 0.04em; }
  h3 { margin: 0 0 2px; font-size: 15px; }
  .sub { color: var(--ink-muted); font-size: 11px; }

  /* --- 왼쪽: 목록 --- */
  .list-panel { flex: 1 1 auto; display: flex; flex-direction: column;
                overflow: hidden; min-height: 0; }
  .filters { display: grid; gap: 6px; margin-bottom: 8px; }
  .filters .row { display: flex; gap: 6px; }
  .filters input[type=search], .filters select {
    flex: 1; min-width: 0; font: inherit; font-size: 12px; padding: 5px 7px;
    background: rgba(255,255,255,0.06); color: var(--ink);
    border: 1px solid var(--hairline); border-radius: 6px;
  }
  .filters label { display: flex; align-items: center; gap: 6px; font-size: 11.5px;
                   color: var(--ink-2); cursor: pointer; }
  .filters input[type=checkbox] { accent-color: #6da7ec; margin: 0; }
  .list { flex: 1 1 auto; overflow-y: auto; margin-right: -6px; padding-right: 4px;
          scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.22) transparent; }
  .item { display: block; width: 100%; text-align: left; font: inherit;
          cursor: pointer; background: rgba(255,255,255,0.05); color: var(--ink);
          border: 1px solid transparent; border-left: 2px solid transparent;
          border-radius: 6px; padding: 6px 8px; margin-bottom: 5px; }
  .item.on { background: rgba(110,167,236,0.18); border-color: #6da7ec; }
  .item .nm { display: block; font-size: 12.5px; white-space: nowrap;
              overflow: hidden; text-overflow: ellipsis; }
  .item .mt { display: block; font-size: 11px; color: var(--ink-muted);
              font-variant-numeric: tabular-nums; }
  .item .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
               margin-right: 5px; vertical-align: 0; }
  .fill { display: inline-block; width: 34px; height: 3px; border-radius: 2px;
          background: rgba(255,255,255,0.14); vertical-align: 2px; margin-left: 6px; }
  .fill i { display: block; height: 100%; border-radius: 2px; background: var(--save); }

  /* --- 오른쪽: 상세·편집 --- */
  .detail { flex: 1 1 auto; overflow-y: auto; min-height: 0;
            scrollbar-width: thin;
            scrollbar-color: rgba(255,255,255,0.22) transparent; }
  #rv { height: 150px; border-radius: 7px; overflow: hidden; margin: 9px 0;
        background: #16161a; }
  #rv.none { display: grid; place-items: center; color: var(--ink-muted);
             font-size: 12px; }
  dl { margin: 0 0 10px; display: grid; grid-template-columns: auto 1fr;
       gap: 2px 12px; font-size: 12px; }
  dt { color: var(--ink-muted); }
  dd { margin: 0; font-variant-numeric: tabular-nums; }
  .cap { color: var(--ink-muted); }
  section { border-top: 1px solid var(--hairline); padding-top: 10px;
            margin-top: 12px; }
  section > h2 { display: flex; justify-content: space-between; align-items: baseline; }

  .near { list-style: none; margin: 0; padding: 0; }
  .near li { display: flex; gap: 8px; align-items: baseline; padding: 4px 0;
             border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 12px; }
  .near li:last-child { border-bottom: 0; }
  .near .d { color: var(--ink-2); font-variant-numeric: tabular-nums;
             flex: 0 0 auto; width: 5ch; text-align: right; }
  .near .t { flex: 1 1 auto; min-width: 0; }
  .near .t b { font-weight: 600; }
  .near .t span { display: block; color: var(--ink-muted); font-size: 11px; }
  /* 이름 옆에 붙는 꼬리표(경로의 시작·끝)는 줄을 바꾸지 않는다. */
  .near .t .cap { display: inline; }
  .near button { font: inherit; font-size: 11px; padding: 2px 7px; cursor: pointer;
                 background: transparent; color: var(--ink-2); flex: 0 0 auto;
                 border: 1px solid var(--hairline); border-radius: 5px; }
  .near button:hover { color: var(--ink); border-color: var(--save); }
  .empty { color: var(--ink-muted); font-size: 12px; }

  /* --- 경로 갈래 고르기 · 구간 머리 --- */
  .routes { display: grid; gap: 5px; margin-bottom: 8px; }
  .routes .one { display: block; width: 100%; text-align: left; font: inherit;
                 cursor: pointer; background: rgba(255,255,255,0.05); color: var(--ink);
                 border: 1px solid transparent; border-left: 2px solid transparent;
                 border-radius: 6px; padding: 5px 8px; }
  .routes .one.on { background: rgba(79,214,224,0.16); border-color: #4fd6e0; }
  .routes .one .nm { display: block; font-size: 12.5px; }
  .routes .one .mt { display: block; font-size: 11px; color: var(--ink-muted);
                     font-variant-numeric: tabular-nums; }
  .routes .one.add { color: var(--ink-2); font-size: 11.5px; text-align: center;
                     background: transparent; border: 1px dashed var(--hairline); }
  .routes .one.add:hover { color: var(--ink); border-color: var(--save); }
  #route > input[type=text] { width: 100%; box-sizing: border-box; font: inherit;
    font-size: 12px; margin-bottom: 7px; background: rgba(255,255,255,0.06);
    color: var(--ink); border: 1px solid var(--hairline); border-radius: 6px;
    padding: 5px 7px; }
  /* 구간 한 덩이. [상세설정] 안에 줄줄이 서는 것이라 점 줄과 다르게 보여야 한다. */
  .near li.seghead { display: block; padding: 8px 0 6px; border-bottom: 0; }
  .seghead .hd { display: flex; gap: 7px; align-items: baseline; margin-bottom: 4px; }
  .seghead .hd b { font-size: 12px; }
  .seghead .hd .cap { flex: 1 1 auto; font-size: 11px; }
  .seghead .hd button { font: inherit; font-size: 10.5px; padding: 1px 6px;
                        cursor: pointer; background: transparent; color: var(--ink-2);
                        border: 1px solid var(--hairline); border-radius: 5px; }
  .seghead .hd button.danger { color: var(--danger); border-color: var(--danger); }
  /* 구간이 어느 점에서 시작하는지를 고르는 자리. 줄 안에 끼는 것이라 아래 입력칸과
     달리 글자만큼만 차지한다. */
  .seghead .hd select { flex: 0 0 auto; font: inherit; font-size: 10.5px;
                        padding: 1px 4px; background: rgba(255,255,255,0.06);
                        color: var(--ink); border: 1px solid var(--hairline);
                        border-radius: 5px; }
  .seghead .seg { margin-bottom: 4px; }
  .seghead .seg button { font-size: 11px; }
  .seghead input { width: 100%; box-sizing: border-box; font: inherit;
                   font-size: 11.5px; background: rgba(255,255,255,0.06);
                   color: var(--ink); border: 1px solid var(--hairline);
                   border-radius: 6px; padding: 4px 7px; }
  /* [상세설정] 을 펼친 덩이. 점 목록과 이어져 보이면 어디까지가 '찍은 것'이고
     어디부터가 '적은 것'인지 흐려지므로 점선으로 가른다. */
  .detbox { margin-top: 8px; padding-top: 8px;
            border-top: 1px dashed var(--hairline); }
  .detbox .addseg { width: 100%; font: inherit; font-size: 11.5px; padding: 4px 0;
                    cursor: pointer; background: transparent; color: var(--ink-2);
                    border: 1px dashed var(--hairline); border-radius: 6px; }
  .detbox .addseg:hover { color: var(--ink); border-color: var(--save); }
  .detbox .clearseg { width: 100%; margin-top: 5px; font: inherit; font-size: 11px;
                      padding: 3px 0; cursor: pointer; background: transparent;
                      color: var(--danger); border: 1px solid var(--danger);
                      border-radius: 6px; }
  /* 코드가 낸 값(탐방로 등급). 사람이 적은 값이 아니라는 것이 보여야 해서
     저장된 칸들과 달리 점선으로 두른다. */
  .draft { margin-top: 10px; padding: 8px 10px; font-size: 12px;
           border: 1px dashed var(--hairline); border-radius: 7px; }

  .field { margin-bottom: 9px; }
  .field > label { display: block; font-size: 11.5px; color: var(--ink-muted);
                   margin-bottom: 3px; }
  /* 칸 밖(오른쪽 [경로] 칸)에서도 같은 작은 글씨를 쓴다. */
  .hint { font-size: 10.5px; color: var(--ink-muted); margin-top: 2px; }
  .field input[type=text], .field input[type=number], .field textarea,
  .field select {
    width: 100%; box-sizing: border-box; font: inherit; font-size: 12px;
    background: rgba(255,255,255,0.06); color: var(--ink);
    border: 1px solid var(--hairline); border-radius: 6px; padding: 5px 7px;
  }
  .field textarea { resize: vertical; min-height: 48px; }
  .field.dirty > label { color: var(--warn); }
  .seg { display: flex; gap: 4px; }
  .seg button { flex: 1; font: inherit; font-size: 11.5px; padding: 4px 0;
                cursor: pointer; background: transparent; color: var(--ink-2);
                border: 1px solid var(--hairline); border-radius: 6px; }
  .seg button.on { background: #256abf; color: #fff; border-color: #256abf; }
  .point { display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
           font-size: 12px; }
  .point .val { flex: 1 1 auto; min-width: 0; overflow: hidden;
                text-overflow: ellipsis; white-space: nowrap; }
  .point button { font: inherit; font-size: 11px; padding: 2px 7px; cursor: pointer;
                  background: transparent; color: var(--ink-2);
                  border: 1px solid var(--hairline); border-radius: 5px; }
  .point button.on { color: var(--ink); border-color: var(--save); }
  .point button.danger { color: var(--danger); border-color: var(--danger); }
  .flags { display: grid; gap: 5px; }
  .flags .one { display: flex; align-items: center; gap: 8px; font-size: 12px; }
  .flags .one .nm { flex: 1 1 auto; }
  .flags .one .seg { flex: 0 0 auto; width: 132px; }
  /* 여러 자리를 담는 칸(주차·화장실). 주차는 자리마다 요금 3단이 붙어 편의시설과
     같은 줄 모양이고, 화장실은 그 자리가 비어 이름과 [빼기] 만 선다. 이름이
     길어질 수 있어(카카오 검색 이름) 넘치면 자른다. */
  .parks { display: grid; gap: 7px; }
  .parks .one { display: flex; align-items: center; gap: 6px; font-size: 12px; }
  .parks .one .nm { flex: 1 1 auto; min-width: 0; overflow: hidden;
                    text-overflow: ellipsis; white-space: nowrap; }
  .parks .one .seg { flex: 0 0 auto; width: 126px; }
  /* `>` 로 [빼기] 만 잡는다 — 자식까지 잡으면 요금 3단 단추도 함께 걸려서,
     `.seg button.on` 과 같은 무게(클래스 2·요소 1)인데 뒤에 서므로 **고른 요금이
     파랗게 서지 않는다**. 지정은 되는데 화면이 그대로라 안 된 것처럼 보인다.
     빨간 hover(=지우는 단추 표시)까지 요금 단추에 붙는 것도 같은 이유였다. */
  .parks .one > button { font: inherit; font-size: 11px; padding: 2px 7px;
                         cursor: pointer; background: transparent;
                         color: var(--ink-2); flex: 0 0 auto;
                         border: 1px solid var(--hairline); border-radius: 5px; }
  .parks .one > button:hover { color: var(--danger); border-color: var(--danger); }

  .acts { display: flex; gap: 6px; margin-top: 10px; }
  .acts button { flex: 1; font: inherit; font-size: 12px; font-weight: 600;
                 padding: 7px 0; cursor: pointer; border-radius: 7px;
                 border: 1px solid var(--hairline); background: transparent;
                 color: var(--ink-2); }
  .acts button.primary { background: var(--save); border-color: var(--save);
                         color: #07231a; }
  .acts button:disabled { opacity: 0.45; cursor: default; }
  /* 지우기는 되돌릴 수 없는 유일한 단추다. 나란히 두되 눈에 다르게 걸려야 해서
     테두리에만 위험색을 주고, 너비는 글자만큼만 차지하게 둔다 — [저장]과 같은
     크기로 두면 손이 미끄러진다. */
  .acts button.danger { flex: 0 0 auto; padding: 7px 12px;
                        border-color: var(--danger); color: var(--danger); }
  .status { font-size: 11px; color: var(--ink-muted); margin-top: 6px;
            min-height: 1.4em; }
  .status.bad { color: var(--danger); }
  .status.good { color: var(--save); }

  dialog { background: var(--panel); color: var(--ink);
           border: 1px solid var(--hairline);
           border-radius: 10px; padding: 16px 18px; width: 320px; }
  dialog::backdrop { background: rgba(0, 0, 0, 0.55); }
  dialog .field { margin-bottom: 10px; }

  /* 지도 종류 전환 — 좌우 세로줄 사이 가운데 위. 카카오 기본 컨트롤을 쓰지 않는
     이유는 그것이 오른쪽 위에 붙는데 그 자리를 상세 패널이 이미 쓰기 때문이다. */
  #maptype { position: absolute; top: 12px; left: 50%; transform: translateX(-50%);
             z-index: 10; padding: 6px; }
  #maptype .seg button { padding: 4px 12px; }

  /* 지도 위 우클릭 메뉴 — 이 좌표로 무엇을 할지 두 가지뿐이라 목록으로 세운다. */
  #menu { position: absolute; z-index: 20; display: none; padding: 6px; }
  #menu button { display: block; width: 100%; text-align: left; font: inherit;
                 font-size: 12px; padding: 5px 9px; cursor: pointer;
                 background: transparent; color: var(--ink); border: 0;
                 border-radius: 5px; white-space: nowrap; }
  #menu button:hover { background: rgba(255,255,255,0.1); }
  #menu .co { font-size: 11px; color: var(--ink-muted); padding: 2px 9px 6px; }

  .legend { font-size: 11.5px; }
  .legend .row { display: flex; align-items: center; gap: 7px; margin: 4px 0;
                 color: var(--ink-2); }
  .legend .sw { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto;
                border: 1px solid rgba(0,0,0,0.55); }
  a { color: var(--link); }
  .fail { position: absolute; inset: 0; display: grid; place-items: center;
          color: var(--ink-2); font-size: 13px; text-align: center; padding: 24px; }
</style>
<div id="map"></div>
<div id="maptype" class="panel">
  <div class="seg">
    <button type="button" data-map="ROADMAP">지도</button>
    <button type="button" data-map="HYBRID">위성+도로</button>
    <button type="button" data-map="SKYVIEW">위성</button>
  </div>
</div>
<div id="menu" class="panel"></div>

<aside class="rail left">
  <div class="panel list-panel">
    <h2>관측지 <span id="listCount"></span></h2>
    <div class="filters">
      <input type="search" id="q" placeholder="이름·비고 검색">
      <div class="row">
        <select id="fRegion"></select>
        <select id="fType"></select>
      </div>
      <label><input type="checkbox" id="fTodo"> 빈 칸이 있는 곳만</label>
      <label><input type="checkbox" id="fToilet"> 200m 안에 화장실이 있는 곳만</label>
    </div>
    <div class="list" id="list"></div>
  </div>
  <div class="panel legend" id="legend"></div>
</aside>

<aside class="rail right">
  <div class="panel detail" id="detail"></div>
</aside>

<dialog id="colDialog">
  <h3>컬럼 추가</h3>
  <p class="sub" style="margin:2px 0 12px">
    모든 관측지의 입력칸에 생긴다. <b>값을 적은 곳에만</b> 키가 붙는다.</p>
  <div class="field">
    <label>키 (영문 소문자·숫자·_)</label>
    <input type="text" id="colKey" placeholder="bus_last">
  </div>
  <div class="field">
    <label>이름</label>
    <input type="text" id="colLabel" placeholder="버스 막차">
  </div>
  <div class="field">
    <label>형식</label>
    <select id="colType"></select>
  </div>
  <div class="field">
    <label>설명 (선택)</label>
    <input type="text" id="colHelp" placeholder="화면에 작은 글씨로 붙는다">
  </div>
  <div class="status" id="colStatus"></div>
  <div class="acts">
    <button class="primary" id="colAdd">추가</button>
    <button id="colCancel">취소</button>
  </div>
</dialog>

<script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey=/*__KEY__*/&autoload=false"></script>
<script>
const DATA = /*__DATA__*/;

const MILKY = { visible: '보임', degraded: '흐릿함', lost: '보기 어려움' };

function esc(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}
function el(id) { return document.getElementById(id); }

if (typeof kakao === 'undefined' || !kakao.maps) {
  document.body.innerHTML =
    '<div class="fail">카카오 지도 SDK 를 불러오지 못했습니다.<br>'
    + 'JavaScript 앱키와 <b>플랫폼 → Web 사이트 도메인</b> 등록을 확인하세요.<br>'
    + '이 페이지 주소(http://localhost:8765)가 등록돼 있어야 합니다.</div>';
} else {
  kakao.maps.load(init);
}

function init() {
  const b = DATA.view.bounds;
  const map = new kakao.maps.Map(el('map'), {
    center: new kakao.maps.LatLng((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), level: 11
  });
  map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.BOTTOM);
  map.setBounds(new kakao.maps.LatLngBounds(
    new kakao.maps.LatLng(b[0], b[1]), new kakao.maps.LatLng(b[2], b[3])));

  let selected = -1;        /* 열려 있는 관측지 index */
  let ctx = null;           /* 그 자리의 주변(화장실·주차·가로등) */
  let draft = {};           /* 아직 저장 안 한 값 — key → 화면 값 */
  let picking = null;       /* 우클릭 메뉴가 연 좌표 */
  let drawing = false;      /* 도보 경로를 찍는 중인가 */
  let active = 0;           /* 여러 길 중 지금 손대는 것 (화면 상태 — 저장 안 한다) */
  let detailOpen = null;    /* [상세설정] 을 폈나. null 은 '아직 안 건드렸다' */
  const overlays = [];      /* 주변 레이어 — 고를 때마다 걷어낸다 */
  const marks = {};         /* index → 관측지 마커 */
  let rvClient = null, roadview = null, radius = null;

  /* --- 지도 위 점 -----------------------------------------------------------
     106곳이라 캔버스로 내려갈 이유가 없다(그건 8만 개짜리 `review_parking.py`
     쪽 이야기다). 오버레이 하나가 곧 관측지 하나라 클릭·강조가 그대로 붙는다. */
  function spotDot(row) {
    const site = row.site;
    const color = site.cap ? DATA.colors.cap[site.cap] : DATA.colors.noGrid;
    const node = document.createElement('div');
    node.style.cssText = 'width:13px;height:13px;border-radius:50%;cursor:pointer;'
      + 'background:' + color + ';border:1.5px solid rgba(8,8,8,.85);'
      + 'box-shadow:0 0 0 1px rgba(255,255,255,.18)';
    node.title = row.values.name_ko;
    node.onclick = function () {
      /* 경로를 찍는 중에 **지금 열어 둔 관측지의 점**을 누르면 그것이 곧 "여기서
         끝"이다 — 도착점을 그 점 옆에 눈대중으로 한 번 더 찍게 하지 않는다.
         다른 관측지를 누르는 것은 평소대로 자리를 옮기는 일이다. */
      if (drawing && row.index === selected) { finishDraw(); return; }
      select(row.index);
    };
    return node;
  }

  DATA.spots.forEach(function (row) {
    const ov = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(row.values.lat, row.values.lon),
      content: spotDot(row), zIndex: 2
    });
    ov.setMap(map);
    marks[row.index] = ov;
  });

  function highlight() {
    DATA.spots.forEach(function (row) {
      const node = marks[row.index].getContent();
      const on = row.index === selected;
      node.style.transform = on ? 'scale(1.55)' : '';
      node.style.boxShadow = on
        ? '0 0 0 2px #ffffff' : '0 0 0 1px rgba(255,255,255,.18)';
    });
  }

  /* --- 주변 레이어 --------------------------------------------------------- */
  function clearNear() {
    while (overlays.length) overlays.pop().setMap(null);
    if (radius) { radius.setMap(null); radius = null; }
  }

  function pin(lat, lon, color, size, title, onclick) {
    const node = document.createElement('div');
    node.style.cssText = 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;'
      + 'background:' + color + ';border:1px solid rgba(8,8,8,.8);'
      + (onclick ? 'cursor:pointer;' : 'pointer-events:none;');
    if (title) node.title = title;
    if (onclick) node.onclick = onclick;
    const ov = new kakao.maps.CustomOverlay({
      position: new kakao.maps.LatLng(lat, lon), content: node, zIndex: 1
    });
    ov.setMap(map);
    overlays.push(ov);
  }

  function drawNear(r) {
    clearNear();
    if (!r || !ctx) return;
    /* 경로를 찍는 동안에는 후보 점을 누를 수 없게 둔다 — 지도를 누르는 손이
       주차 후보 위를 지나면 경로 대신 주차 지점이 조용히 바뀐다. */
    const tap = function (fn) { return drawing ? null : fn; };
    ctx.lamps.points.forEach(function (p) {
      pin(p[0], p[1], DATA.colors.lamp, 5, '가로등');
    });
    ctx.parking.list.forEach(function (p) {
      pin(p.lat, p.lon, DATA.colors.parking, 10,
        p.name + ' · ' + p.distanceM + 'm',
        tap(function () { addPlace('parking', p); }));
    });
    ctx.stores.list.forEach(function (s) {
      pin(s.lat, s.lon, DATA.colors.store, 9,
        s.name + ' · ' + fmtDist(s.distanceM),
        tap(function () { setPoint('store', s); }));
    });
    ctx.toilets.list.forEach(function (t) {
      pin(t.lat, t.lon, DATA.colors.toilet, 10,
        t.name + ' · ' + t.distanceM + 'm · ' + (t.hours || '개방시간 미상'),
        tap(function () { addPlace('toilet', t); }));
    });
    /* 지정해 둔 자리는 후보 위에 겹쳐 크게 찍는다 — 무엇을 이미 골랐는지가
       목록을 다시 읽지 않아도 지도에서 바로 보여야 한다. 주차·화장실은 여럿일 수
       있어 몇 번째인지를 함께 적고, 주차는 요금이 자리마다 다르므로 그것도 적는다. */
    lots().forEach(function (p, i) {
      pin(p.lat, p.lon, DATA.colors.pick, 12,
        '지정 주차 ' + (i + 1) + ': ' + (p.name || '이름 없음')
        + ' · ' + (p.fee || '요금 미확인'));
    });
    places('toilet').forEach(function (p, i) {
      pin(p.lat, p.lon, DATA.colors.pick, 12,
        '지정 화장실 ' + (i + 1) + ': ' + (p.name || '이름 없음'));
    });
    const store = value('store');
    if (store) {
      pin(store.lat, store.lon, DATA.colors.pick, 12,
        '지정 가게: ' + (store.name || '이름 없음'));
    }
    /* 도보 경로는 이 화면에서 유일한 선이다. 길이 여럿이면 전부 그리되 지금 손대는
       길만 굵고 진하게 둔다 — 나머지는 "여기 다른 길이 있다"만 말하면 된다.
       구간을 나눠 뒀으면 구간마다 난이도 색으로 끊어 그린다. 경계 점은 양쪽 선이
       함께 써야 사이가 끊겨 보이지 않는다. */
    routes().forEach(function (r, ri) {
      const pts = points(r);
      const on = ri === active;
      const segs = segments(r);
      const spans = segs.length
        ? segs.map(function (s, i) {
            return [s.from, i + 1 < segs.length ? segs[i + 1].from : pts.length - 1,
                    segColor(s)];
          })
        : [[0, pts.length - 1, DATA.colors.route]];
      if (pts.length > 1) {
        spans.forEach(function (span) {
          const line = new kakao.maps.Polyline({
            path: pts.slice(span[0], span[1] + 1).map(function (p) {
              return new kakao.maps.LatLng(p[0], p[1]);
            }),
            strokeWeight: on ? 4 : 2, strokeColor: span[2],
            strokeOpacity: on ? 0.95 : 0.45, strokeStyle: 'solid'
          });
          line.setMap(map);
          overlays.push(line);
        });
      }
      /* 점은 지금 손대는 길만 찍는다. 여러 길의 점이 겹쳐 찍히면 [빼기] 가 어느
         점을 가리키는지 지도에서 알 수 없다. */
      if (!on) return;
      /* 양 끝은 크게 찍는다 — 그 둘만 코드가 놓는 점이고, 경로가 관측 자리에서
         끝났는지가 지도에서도 보여야 한다. */
      const last = endsAtSite(pts) ? pts.length - 1 : -1;
      const head = {};
      segs.forEach(function (s, i) { head[s.from] = i; });
      pts.forEach(function (p, i) {
        const end = i === 0 || i === last;
        const at = head[i];
        pin(p[0], p[1],
          at === undefined ? DATA.colors.route : segColor(segs[at]),
          end || at !== undefined ? 9 : 7,
          (i + 1) + '/' + pts.length
          + (i === 0 ? ' · 시작' : (i === last ? ' · 끝' : ''))
          + (at === undefined ? '' : ' · 구간 ' + (at + 1) + ' 시작'));
      });
    });
    radius = new kakao.maps.Circle({
      center: new kakao.maps.LatLng(r.values.lat, r.values.lon),
      radius: ctx.toilets.radiusM, strokeWeight: 1, strokeColor: DATA.colors.toilet,
      strokeOpacity: 0.75, strokeStyle: 'shortdash', fillOpacity: 0
    });
    radius.setMap(map);
  }

  /* --- 값 ------------------------------------------------------------------
     화면이 보는 값은 **저장 전 초안(draft) 우선**이다. 저장하면 초안을 비우고
     서버가 돌려준 관측지로 갈아 끼운다 — 화면과 파일이 어긋난 채로 남지 않게. */
  function row() { return selected < 0 ? null : DATA.spots[selected]; }

  function stored(key) {
    const r = row();
    if (!r) return undefined;
    if (key === 'coords') return { lat: r.values.lat, lon: r.values.lon };
    return r.values[key];
  }

  function value(key) {
    return Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : stored(key);
  }

  function setValue(key, v) {
    draft[key] = v;
    renderActions();
    const field = document.querySelector('[data-field="' + key + '"]');
    if (field) field.classList.add('dirty');
  }

  function dirty() { return Object.keys(draft).length > 0; }

  /* --- 여러 자리를 담는 칸(주차 · 화장실) ---------------------------------------
     길이 여럿일 수 있는 것과 같은 이유로 자리도 여럿일 수 있다 — 주차는 오름
     하나에 들머리가 갈려서(그때 한쪽만 유료인 경우가 있다), 화장실은 밤에 어느
     곳이 열려 있을지 몰라서다. 이유는 달라도 화면이 하는 일은 같아서 한 벌로 둔다.
     `false` 는 "확인했고 없다"라서 목록이 아니다(그때는 빈 목록으로 본다). */
  function places(key) {
    const v = value(key);
    return Array.isArray(v) ? v : [];
  }

  function setPlaces(key, list) {
    setValue(key, list.length ? list : null);
  }

  /* 후보를 누르면 **더한다**(갈아 끼우지 않는다). 이미 같은 자리가 있으면 아무 일도
     하지 않는다 — 같은 자리가 후보 목록과 지도 양쪽에 있어서 두 번 누르기 쉽고,
     그러면 한 자리가 둘로 늘어 주차는 요금 3단이 어느 쪽이 값인지 흐려진다.
     요금은 여기서 묻지 않는다 — 지도를 보고 아는 것이 아니라 출처를 봐야 아는
     것이라 [기입] 칸에서 적는다. */
  function addPlace(key, p) {
    const list = places(key);
    const same = list.some(function (x) {
      return metersBetween([x.lat, x.lon], [p.lat, p.lon]) < 1;
    });
    if (!same) setPlaces(key, list.concat([{ name: p.name, lat: p.lat, lon: p.lon }]));
    renderForm();
  }

  function dropPlace(key, i) {
    setPlaces(key, places(key).filter(function (_, j) { return j !== i; }));
    renderForm();
  }

  /* 주차 자리는 경로가 시작하는 자리이기도 해서 아래 경로 코드가 자주 부른다. */
  function lots() { return places('parking'); }

  /* --- 도보 경로 ------------------------------------------------------------
     찍을 때마다 다시 재는 값이라 서버에 묻지 않는다. 거리 식은
     `core.lamps._distances_m` 와 같은 등거리 평면 근사다 — 수백 m 규모에서
     화면과 서버가 다른 길이를 말하면 안 된다. */
  function metersBetween(a, b) {
    const dy = (b[0] - a[0]) * DATA.kmPerDeg;
    const dx = (b[1] - a[1]) * DATA.kmPerDeg * Math.cos(a[0] * Math.PI / 180);
    return Math.sqrt(dx * dx + dy * dy) * 1000;
  }

  function routeLength(pts) {
    let m = 0;
    for (let i = 1; i < pts.length; i++) m += metersBetween(pts[i - 1], pts[i]);
    return m;
  }

  /* 도보 경로는 정의상 **주차 자리에서 시작해 관측 자리에서 끝난다**. 두 좌표는
     화면이 이미 알고 있으므로 양 끝은 코드가 놓는다 — 같은 자리를 눈대중으로 다시
     찍게 하면 몇 m 씩 어긋난 시작·끝점만 쌓인다. 그래서 "끝났다"는 목록이 지어내는
     말이 아니라 **마지막 점이 관측 좌표와 같은 점인가**로 판별한다(관측 좌표를 뒤에
     옮기면 그 순간 다시 '안 끝난 경로'가 된다 — 그게 사실이기 때문이다). */
  function isSite(p) {
    const c = value('coords');
    return !!p && p[0] === c.lat && p[1] === c.lon;
  }

  function endsAtSite(pts) {
    return pts.length > 1 && isSite(pts[pts.length - 1]);
  }

  /* --- 여러 갈래 --------------------------------------------------------------
     한 관측지에 오르는 길이 하나뿐이라는 법이 없다. 다랑쉬오름은 오른쪽으로 돌면
     빨리 닿지만 가파르고, 왼쪽으로 돌면 오래 걸리지만 완만하다 — 그 둘은 같은
     경로의 변형이 아니라 **고를 수 있는 다른 길**이라 나란히 담는다.

     `active` 는 지금 손대고 있는 길이다. 저장되지 않는 화면 상태다 — 파일에는
     길들이 나란히 있을 뿐 '고른 길'이라는 것이 없다. */
  function routes() { return value('walk_routes') || []; }

  function activeRoute() { return routes()[active] || null; }

  function points(r) { return (r && r.points) || []; }

  function setRoutes(list) {
    setValue('walk_routes', list.length ? list : null);
    if (active >= list.length) active = Math.max(0, list.length - 1);
  }

  /* 길 하나만 갈아 끼운다. 나머지는 손대지 않는다 — 한 길을 고치다 옆 길이 조용히
     바뀌는 일이 없어야 한다. */
  function editRoute(i, patch) {
    setRoutes(routes().map(function (r, j) {
      return j === i ? Object.assign({}, r, patch) : r;
    }));
  }

  function routeName(r, i) {
    return r.name || (routes().length > 1 ? (i + 1) + '번 길' : '도보 경로');
  }

  /* --- 구간 -------------------------------------------------------------------
     구간은 **자르는 자리**로만 잡는다. `from` 은 그 구간이 시작하는 점 번호이고,
     끝은 다음 구간이 시작하기 직전이다 — 구간마다 시작·끝을 따로 적게 하면 틈과
     겹침이 생기고, 점을 하나 빼는 순간 둘이 어긋난다.

     선을 그릴 때만 경계 점을 양쪽이 함께 쓴다(안 그러면 구간 사이가 끊겨 보인다). */
  function segments(r) { return (r && r.segments) || []; }

  function segEnd(r, i) {
    const segs = segments(r);
    return i + 1 < segs.length ? segs[i + 1].from - 1 : points(r).length - 1;
  }

  /* 노면을 아직 안 적은 구간은 경로 기본색으로 둔다 — 색이 없는 것과 '정비'는
     다른 말이다. */
  function segColor(s) {
    return (s && s.surface && DATA.colors.surface[s.surface]) || DATA.colors.route;
  }

  /* 구간 머리로 아직 안 쓰인 점들. [+ 구간] 과 시작점 고르기가 이 목록에서 고른다 —
     한 점에 구간 둘이 걸리면 앞엣것은 길이 0 이 되어 아무것도 말하지 않는다.
     구간이 하나도 없으면 첫 구간뿐이고, 첫 구간은 언제나 경로 첫 점에서 시작한다. */
  function freePoints(r) {
    if (!segments(r).length) return [0];
    const used = {};
    segments(r).forEach(function (s) { used[s.from] = true; });
    const out = [];
    for (let i = 1; i < points(r).length; i++) if (!used[i]) out.push(i);
    return out;
  }

  function byFrom(a, b) { return a.from - b.from; }

  function addSegment(from) {
    editRoute(active, {
      segments: segments(activeRoute()).concat([{ from: from }]).sort(byFrom)
    });
  }

  /* 시작점을 옮기면 순서가 바뀔 수 있다 — 서버는 찍은 순서대로가 아닌 구간을 받지
     않으므로 여기서 다시 세운다. */
  function moveSegment(i, from) {
    editRoute(active, {
      segments: segments(activeRoute()).map(function (s, j) {
        return j === i ? Object.assign({}, s, { from: from }) : s;
      }).sort(byFrom)
    });
  }

  /* 구간을 지우면 그 자리는 앞 구간이 물려받는다. 첫 구간을 지웠으면 다음 구간이
     경로 첫 점으로 내려온다 — 첫 점에서 시작하지 않는 구간표를 서버가 받지 않기
     때문이고, 그게 사실이기도 하다(앞이 비면 그 앞은 아무 구간도 아니다). */
  function dropSegment(i) {
    const segs = segments(activeRoute()).filter(function (_, j) { return j !== i; });
    if (segs.length) segs[0] = Object.assign({}, segs[0], { from: 0 });
    /* 남은 것이 아무것도 말하지 않으면 자른 적 없는 것과 같다. 서버의 `_SAID` 와
       같은 목록이다 — 둘이 갈리면 화면에서 지운 구간이 저장에서 되살아나거나,
       화면에만 있던 값이 저장에서 조용히 사라진다. */
    const said = segs.some(function (s) { return s.surface || s.rock || s.note; });
    editRoute(active, { segments: said ? segs : [] });
  }

  function editSegment(i, patch) {
    editRoute(active, {
      segments: segments(activeRoute()).map(function (s, j) {
        return j === i ? Object.assign({}, s, patch) : s;
      })
    });
  }

  /* --- 목록 -------------------------------------------------------------------
     찍은 점을 오른쪽에서 되짚어 본다. 위·경도를 그대로 적는 이유는 이 목록이
     저장될 값 자체이기 때문이고, 앞 점에서의 거리를 함께 두는 이유는 잘못 찍은
     점이 거리로 먼저 드러나기 때문이다 — 지도에서는 겹쳐 보이는 두 점도 목록에서는
     +4m 로 보이고, 엉뚱한 데를 눌렀으면 +900m 로 튄다. */
  function routeListHtml(r) {
    const pts = points(r);
    if (!pts.length) return '';
    const segs = segments(r);
    const head = {};
    segs.forEach(function (s, i) { head[s.from] = i; });
    const done = endsAtSite(pts);

    return '<ul class="near">' + pts.map(function (p, i) {
      const tag = i === 0 ? ' <span class="cap">· 시작</span>'
        : (done && i === pts.length - 1 ? ' <span class="cap">· 끝</span>' : '');
      /* 구간 경계는 여기서 **말만 한다**. 자르고 적는 일은 [상세설정] 이 맡는다 —
         한 줄이 좌표 확인과 구간 편집의 입구를 겸하면, 노면을 적으려고 점을
         자른다는 것이 무슨 일인지 화면만 보고는 알 수가 없다. */
      const at = head[i] === undefined ? ''
        : ' <span class="cap">· 구간 ' + (head[i] + 1) + ' 시작</span>';
      return '<li><span class="d">'
        + (i ? '+' + fmtDist(Math.round(metersBetween(pts[i - 1], p))) : '시작')
        + '</span><span class="t"><b>' + (i + 1) + '번</b>' + tag + at
        + '<span>' + p[0].toFixed(6) + ', ' + p[1].toFixed(6) + '</span></span>'
        + '<button data-drop="' + i + '">빼기</button></li>';
    }).join('') + '</ul>';
  }

  /* --- 상세설정 ---------------------------------------------------------------
     노면상태·암릉암반·특색·지형은 전부 **길 하나에 딸린 것**이라 길 단위로 한자리에
     모은다. 구간은 그 안에서 "여기부터 밟는 것이 바뀐다"를 적다가 생기는 것이지,
     구간을 만드는 것 자체가 목적인 적은 없다.

     편 상태는 저장하지 않는다. `null` 은 '아직 사람이 안 건드렸다'라서, 이미 적어
     둔 것이 있으면 펴진 채로 시작한다 — 값이 있는데 접혀 있으면 없는 것처럼 읽힌다. */
  function detailOn(r) {
    if (detailOpen !== null) return detailOpen;
    return segments(r).length > 0 || !!(r && r.terrain);
  }

  function detailHtml(r) {
    if (points(r).length < 2 || !detailOn(r)) return '';
    const segs = segments(r);
    const free = freePoints(r);
    return '<div class="detbox">'
      + (segs.length
          ? '<ul class="near">' + segs.map(function (_, i) {
              return segmentHtml(r, i);
            }).join('') + '</ul>'
          : '<div class="empty">아직 구간이 없다 — [+ 구간] 을 한 번 누르면 길 '
            + '전체가 한 구간이 되고, 거기에 노면상태·암릉암반을 적는다. 밟는 것이 '
            + '바뀌는 자리에서 구간을 하나 더 두면 그 점부터 다음 구간이다.</div>')
      + (free.length
          ? '<button class="addseg" data-addseg="' + free[0] + '">+ 구간</button>'
          : '<div class="hint">점마다 구간이 하나씩이라 더 둘 자리가 없다</div>')
      /* 구간을 하나씩 지우는 것으로는 감당이 안 되는 경우가 있다 — 점마다 구간이
         하나씩 박힌 길이 그렇다(옛 [나누기] 가 점 목록에 있던 시절의 잔해다).
         구간 하나짜리는 [지우기] 가 곧 이것이므로 두 번 묻지 않는다. */
      + (segs.length > 1
          ? '<button class="clearseg" data-clearseg="1">구간 전부 지우기</button>'
          : '')
      + terrainHtml(r)
      + '</div>';
  }

  /* 구간 한 덩이 — 어디부터 어디까지이고, 거기서 밟는 것이 무엇인가. */
  function segmentHtml(r, i) {
    const s = segments(r)[i];
    const to = segEnd(r, i);
    return '<li class="seghead">'
      + '<div class="hd"><b>구간 ' + (i + 1) + '</b>'
      /* 첫 구간은 언제나 경로 첫 점에서 시작한다 — 앞이 비면 그 앞은 아무 구간도
         아니다. 그래서 고를 것이 없고, 고르는 자리도 두지 않는다. */
      + (i ? startPickHtml(r, i) : '')
      + '<span class="cap">' + (s.from + 1) + '~' + (to + 1) + '번 · '
      + fmtDist(Math.round(routeLength(points(r).slice(s.from, to + 1))))
      /* 경사는 저장할 때 표고 격자에서 잰 값이다(`core/elevation.py`). 격자 두 칸
         보다 짧은 구간은 못 재고, 못 잰 것은 못 쟀다고 적는다 — 0° 로 두면
         '평평하다'로 읽힌다. */
      + (s.slope_deg === undefined
          ? ' · <span title="구간이 격자 두 칸(약 62m)보다 짧다">경사 —</span>'
          : ' · 경사 ' + (s.slope_deg > 0 ? '+' : '') + s.slope_deg + '°')
      + '</span>'
      + '<button class="danger" data-segdel="' + i + '">지우기</button>'
      + '</div>'
      + '<span class="cap sgl">노면상태</span>'
      + chipsHtml('sf_' + i, DATA.trail.surface, DATA.trail.surfaceHelp,
                  s.surface, DATA.colors.surface)
      + '<span class="cap sgl">암릉·암반</span>'
      + chipsHtml('rk_' + i, DATA.trail.rock, DATA.trail.rockHelp, s.rock, null)
      + '<input type="text" data-snote="' + i + '" value="' + esc(s.note || '')
      + '" placeholder="이 구간의 특색 — 경사·쉴 곳·시야">'
      + '</li>';
  }

  /* 구간이 어느 점에서 시작하는지. 예전 [나누기] 가 하던 일이 이 자리로 왔다 —
     자를 자리를 점 목록에서 고르는 대신, 구간이 자기 시작점을 들고 있는다. */
  function startPickHtml(r, i) {
    const at = segments(r)[i].from;
    const pick = freePoints(r).concat([at]).sort(function (a, b) { return a - b; });
    return '<select data-sfrom="' + i + '" title="이 구간이 시작하는 점">'
      + pick.map(function (n) {
          return '<option value="' + n + '"' + (n === at ? ' selected' : '') + '>'
            + (n + 1) + '번부터</option>';
        }).join('')
      + '</select>';
  }

  /* 낱말 고르는 단추 한 줄. 무엇을 뜻하는지는 눌러 보고 알 것이 아니라서 원문 설명을
     title 로 붙인다. `colors` 를 주면 단추 테두리가 지도 선과 **같은 색**이 되어,
     지도에서 어느 구간이 무엇이었는지를 여기서 되짚을 수 있다. */
  function chipsHtml(id, values, help, chosen, colors) {
    const opts = [['', '미지정', '아직 안 봤다']].concat(
      values.map(function (v) { return [v, v, help[v]]; }));
    return '<div class="seg" id="' + id + '">' + opts.map(function (o) {
      return '<button type="button" data-v="' + esc(o[0]) + '"'
        + ' title="' + esc(o[2]) + '"'
        + (o[0] === (chosen || '') ? ' class="on"' : '')
        + (o[0] && colors ? ' style="border-color:' + colors[o[0]] + '55"' : '')
        + '>' + esc(o[1]) + '</button>';
    }).join('') + '</div>';
  }

  /* --- 오른쪽 [경로] 칸 전체 -------------------------------------------------- */
  function routeHtml() {
    const list = routes();
    const r = activeRoute();
    const pts = points(r);

    /* 길이 둘 이상이면 먼저 고르게 한다. 하나뿐이어도 같은 줄을 세운다 — 여기에
       [+ 다른 길] 이 붙어 있어야 "길을 더 둘 수 있다"는 것이 보인다. */
    const chooser = '<div class="routes">' + list.map(function (x, i) {
      const p = points(x);
      return '<button class="one' + (i === active ? ' on' : '')
        + '" data-pickroute="' + i + '">'
        + '<span class="nm">' + esc(routeName(x, i)) + '</span>'
        + '<span class="mt">'
        + (p.length ? p.length + '점 · ' + fmtDist(Math.round(routeLength(p)))
                    : '아직 안 찍었다')
        + (segments(x).length ? ' · 구간 ' + segments(x).length : '')
        + '</span></button>';
    }).join('')
      + '<button class="one add" data-addroute="1">+ 다른 길</button></div>';

    if (!r) {
      return chooser + '<div class="empty" style="margin-top:8px">아직 그리지 '
        + '않았다 — [+ 다른 길] 로 길을 하나 만들고 지도를 우클릭한다. 첫 점은 '
        + '주차 자리에 놓인다' + (lots().length > 1 ? '(어느 자리인지 고른다)' : '')
        + '.</div>';
    }

    return chooser
      + (list.length > 1
          ? '<input type="text" data-rname="' + active + '" value="'
            + esc(r.name || '') + '" placeholder="이 길의 이름 — 오른쪽 급경사길">'
          : '')
      + '<div class="point">'
      + (drawing
          ? '<button data-finish="1">관측 자리에서 끝내기</button>'
            + '<button data-stop="1">멈추기</button>'
          : drawStartHtml(pts))
      /* 노면을 적는 입구는 여기 하나다. 점 목록에는 두지 않는다. */
      + (pts.length > 1
          ? '<button data-detail="1"' + (detailOn(r) ? ' class="on"' : '')
            + ' title="이 길의 구간·노면·암릉·지형">상세설정</button>'
          : '')
      + '<button class="danger" data-delroute="' + active + '">이 길 지우기</button>'
      /* 길이 하나뿐이면 [이 길 지우기] 가 곧 전부 지우기라 두 번 묻지 않는다. */
      + (list.length > 1
          ? '<button class="danger" data-delall="1" title="이 관측지의 길 '
            + list.length + '개를 모두">전부 지우기</button>'
          : '')
      + '</div>'
      + (drawing
          ? '<div class="hint" style="margin-top:6px">지도를 <b>우클릭</b>한 순서가 '
            + '곧 경로다. 찍는 동안 우클릭 메뉴는 뜨지 않는다. 끝점은 손으로 찍지 '
            + '않는다 — <b>관측지 점을 누르거나</b> [관측 자리에서 끝내기] 를 누르면 '
            + '관측 좌표를 마지막 점으로 놓고 끝낸다.</div>'
          : '')
      + (pts.length
          ? routeListHtml(r)
          : '<div class="empty" style="margin-top:8px">'
            + (lots().length > 1
                ? '어느 주차 자리에서 오르는 길인지 위에서 고른다 — 그 자리가 첫 '
                  + '점이 되고, 이어서 지도를 우클릭한다.'
                : '[그리기] 를 누르고 지도를 우클릭한다. 첫 점은 주차 자리에 '
                  + '놓인다.')
            + '</div>')
      + (pts.length === 1
          ? '<div class="empty" style="margin-top:6px">점이 하나다 — 두 점부터 '
            + '경로다.</div>' : '')
      + (pts.length > 1 && !endsAtSite(pts)
          ? '<div class="empty" style="margin-top:6px">아직 <b>관측 자리</b>에서 '
            + '끝나지 않았다.</div>' : '')
      + detailHtml(r)
      /* 도보 시간은 내지 않는다. 길이 ÷ 걸음속도로 낸 분은 계단·오르막에서 실제와
         크게 벌어지는데, 이 도구가 그리는 선은 대부분 오름 등반로다 — 틀린 수를
         내놓느니 안 내놓는다. 힘든 정도는 아래 탐방로 등급이 말한다. */
      + gradeHtml(r);
  }

  /* 찍기를 켜는 단추. 주차 자리가 둘 이상이고 아직 한 점도 안 찍었으면 **자리마다**
     세운다 — 길은 정의상 주차 자리에서 시작하는데 그 자리가 여럿이면 어느 쪽인지는
     코드가 알 수 없고, 짐작해서 놓은 첫 점은 나중에 아무도 틀린 줄 모른다.
     이어 찍는 중이면 시작점은 이미 정해졌으므로 묻지 않는다. */
  function drawStartHtml(pts) {
    const list = lots();
    if (pts.length || list.length < 2) {
      return '<button data-draw="-1">' + (pts.length ? '이어 찍기' : '그리기')
        + '</button>';
    }
    return list.map(function (p, i) {
      return '<button data-draw="' + i + '" title="' + esc(p.name || '이름 없음')
        + ' 에서 시작">' + esc(p.name || (i + 1) + '번 자리') + '에서</button>';
    }).join('');
  }

  /* 지형은 **등급 배점표를 고르는 값**이다 — 같은 1km 가 둘레길에서 1점, 사면부에서
     3점이다. 코드가 짐작하지 않는다(오름이니 사면부겠지) — 안 고르면 등급을
     내지 않는다. 길 하나에 하나뿐인 값이라 [상세설정] 안에 있다. */
  function terrainHtml(r) {
    if (points(r).length < 2) return '';
    return '<div class="field" style="margin:8px 0 0"><label>지형</label>'
      + chipsHtml('tr_' + active, DATA.trail.terrain, DATA.trail.terrainHelp,
                  r.terrain, null)
      + '<div class="hint">경사도·거리 배점표가 이것으로 갈린다</div></div>';
  }

  /* 등급 — 국립공원공단 탐방로 등급제. 항목 점수를 함께 띄운다: 무엇 때문에 이 등급인지
     보이지 않으면 사람이 값을 고칠 수가 없다. 못 낸 이유도 그대로 적는다. */
  function gradeHtml(r) {
    if (points(r).length < 2) return '';
    const why = [];
    if (r.slope_deg === undefined) why.push('경사(경로가 너무 짧다)');
    if (!r.terrain) why.push('지형');
    const worst = worstSegment(r);
    if (!worst.surface) why.push('노면상태');
    if (!worst.rock) why.push('암릉·암반');
    if (why.length) {
      return '<div class="empty" style="margin-top:8px">탐방로 등급 — 아직 '
        + esc(why.join(' · ')) + ' 이(가) 없다'
        + (r.slope_deg === undefined && why.length === 1
            ? '' : ' <span class="cap">· [상세설정] 에서 적는다</span>')
        + '</div>';
    }

    const pct = Math.abs(r.climb_m) / r.over_m * 100;
    const point = {
      slope: bandPoint(pct, DATA.trail.slopePct[r.terrain]),
      distance: bandPoint(r.over_m, DATA.trail.distanceM[r.terrain]),
      rock: DATA.trail.rock.indexOf(worst.rock) + 1,
      surface: DATA.trail.surface.indexOf(worst.surface) + 1
    };
    let sum = 0, total = 0;
    Object.keys(DATA.trail.weight).forEach(function (k) {
      sum += DATA.trail.weight[k] * point[k];
      total += DATA.trail.weight[k];
    });
    const score = sum / total;
    let grade = DATA.trail.hardest;
    for (let i = 0; i < DATA.trail.grades.length; i++) {
      if (score < DATA.trail.grades[i][0]) { grade = DATA.trail.grades[i][1]; break; }
    }
    return '<div class="field" style="margin:8px 0 0"><label>탐방로 등급</label>'
      + '<div class="draft"><b>' + esc(grade) + '</b> · ' + score.toFixed(2) + '점'
      + '<div class="hint">경사 ' + point.slope + '점(' + pct.toFixed(1) + '%)'
      + ' · 거리 ' + point.distance + '점(' + fmtDist(Math.round(r.over_m)) + ')'
      + ' · 암릉 ' + point.rock + '점 · 노면 ' + point.surface + '점'
      + '<br>' + esc(DATA.trail.source)
      + '<br>' + esc(DATA.demSource)
      + ' — 소요시간 항목(가중치 ' + DATA.trail.omitted['소요시간'] + ')은 원문에 '
      + '배점표가 없어 뺐다. 노면·암릉은 구간 중 <b>가장 나쁜 값</b>을 쓴다'
      + '</div></div></div>';
  }

  /* 등급은 길 하나에 하나다. 구간마다 내려면 구간마다의 경사가 있어야 하는데 90m
     DEM 으로는 못 잰다. 그래서 노면·암릉은 **가장 나쁜 구간**으로 대표한다 —
     편한 데를 말해 놓고 힘든 데서 막히는 것이 반대보다 나쁘다. */
  function worstSegment(r) {
    const out = { surface: '', rock: '' };
    segments(r).forEach(function (s) {
      if (s.surface && DATA.trail.surface.indexOf(s.surface)
          > DATA.trail.surface.indexOf(out.surface)) out.surface = s.surface;
      if (s.rock && DATA.trail.rock.indexOf(s.rock)
          > DATA.trail.rock.indexOf(out.rock)) out.rock = s.rock;
    });
    return out;
  }

  /* (상한, 점수) 표에서 점수를 찾는다. 상한을 넘으면 5점.
     `core.trail._score` 와 같은 셈이다. */
  function bandPoint(value, table) {
    for (let i = 0; i < table.length; i++) {
      if (value <= table[i][0]) return table[i][1];
    }
    return 5;
  }

  /* --- 칸 그리기 ------------------------------------------------------------ */
  function fieldHtml(col) {
    const v = value(col.key);
    const id = 'f_' + col.key;
    let body = '';

    if (col.type === 'text' || col.type === 'number') {
      body = '<input type="' + (col.type === 'number' ? 'number' : 'text')
        + '" id="' + id + '" value="' + esc(v === undefined || v === null ? '' : v)
        + '">';
    } else if (col.type === 'textarea') {
      body = '<textarea id="' + id + '">' + esc(v || '') + '</textarea>';
    } else if (col.type === 'choice') {
      const opts = (DATA.choices[col.key] || []).slice();
      if (v && opts.indexOf(v) < 0) opts.push(v);
      body = '<input type="text" id="' + id + '" list="dl_' + col.key + '" value="'
        + esc(v || '') + '"><datalist id="dl_' + col.key + '">'
        + opts.map(function (o) { return '<option value="' + esc(o) + '">'; }).join('')
        + '</datalist>';
    } else if (col.type === 'list') {
      body = '<textarea id="' + id + '">' + esc((v || []).join('\\n')) + '</textarea>';
    } else if (col.type === 'bool') {
      body = segHtml(id, v);
    } else if (col.type === 'flags') {
      /* 항목마다 3단이다 — 이 파일의 "없는 키가 곧 미확인"이 `amenities` 사전
         안쪽에서도 그대로 서기 때문이다: 키 없음(미확인) · true(있다) ·
         false(가 봤는데 없다). 한때 '있다'만 적었는데, 그러면 화장실을 확인하러
         간 관측지와 아직 안 본 관측지가 파일에서 같아 보인다. */
      body = '<div class="flags" id="' + id + '">'
        + DATA.flagKeys.map(function (k) {
            const f = v ? v[k] : undefined;
            return '<div class="one"><span class="nm">' + esc(k) + '</span>'
              + segHtml(id + '_' + k, typeof f === 'boolean' ? f : undefined,
                        [['', '미확인'], ['yes', '있음'], ['no', '없음']])
              + '</div>';
          }).join('')
        + '</div>';
    } else if (col.type === 'parking' || col.type === 'points') {
      body = placesFieldHtml(col, v);
    } else if (col.type === 'point') {
      /* 세 상태 — 미확인 · 없음 · 좌표. 상태마다 다음에 할 일이 하나뿐이라
         버튼도 하나씩만 세운다(3단 토글은 좌표를 만들어 내지 못한다). */
      if (v === false) {
        body = '<div class="point"><span class="val">확인함 · <b>없음</b></span>'
          + '<button data-unknown="' + col.key + '">미확인으로</button></div>';
      } else if (v) {
        body = '<div class="point"><span class="val">' + esc(v.name || '이름 없음')
          + ' <span class="cap">' + v.lat.toFixed(5) + ', ' + v.lon.toFixed(5)
          + '</span></span>'
          + '<button data-clear="' + col.key + '">비우기</button></div>';
      } else {
        body = '<div class="point"><span class="val cap">미확인</span>'
          + '<button data-none="' + col.key + '">없음</button></div>';
      }
    } else if (col.type === 'coords') {
      body = '<div class="point"><span class="val">' + v.lat.toFixed(6) + ', '
        + v.lon.toFixed(6) + '</span>'
        + '<button data-copy="' + v.lat.toFixed(6) + ', ' + v.lon.toFixed(6)
        + '">복사</button></div>';
    } else if (col.type === 'routes') {
      /* 찍는 것도 되짚는 것도 위 [경로] 칸에서 한다. 여기서는 지금 값이 무엇인지만
         말한다 — 같은 목록을 두 군데 그리면 어느 쪽이 값인지 흐려진다. */
      const list = v || [];
      body = '<div class="point"><span class="val' + (list.length ? '' : ' cap')
        + '">' + (list.length
            ? list.map(function (x, i) {
                return esc(routeName(x, i)) + ' ' + points(x).length + '점'
                  + (endsAtSite(points(x)) ? '' : ' <span class="cap">· 안 끝났다'
                     + '</span>');
              }).join(' <span class="cap">·</span> ')
            : '미확인')
        + '</span>'
        + '<button data-goroute="1">경로 칸으로</button></div>';
    }

    const filled = v !== undefined && v !== null && v !== ''
      && !(Array.isArray(v) && !v.length);
    return '<div class="field" data-field="' + col.key + '">'
      + '<label for="' + id + '">' + esc(col.label)
      + (filled ? '' : ' <span class="cap">· 미확인</span>') + '</label>'
      + body
      + (col.help ? '<div class="hint">' + esc(col.help) + '</div>' : '')
      + '</div>';
  }

  /* 자리 여럿을 담는 칸(`points`·`parking`). `point` 와 같은 세 상태(미확인 ·
     없음 · 좌표)인데 좌표가 **여럿**이다 — 주차는 들머리가 갈려서, 화장실은 밤에
     어느 곳이 열려 있을지 몰라서 여럿이 된다.

     요금은 주차에만 붙는다. 한쪽 들머리만 유료인 경우가 있어 관측지에 한 값으로
     적을 수가 없어서인데, 화장실에는 그런 자리마다 갈리는 값이 없다 — 개방시간은
     원본(`core.toilet`)이 들고 있지 사람이 여기 옮겨 적을 것이 아니다. */
  function placesFieldHtml(col, v) {
    const fee = col.type === 'parking';
    if (v === false) {
      return '<div class="point"><span class="val">확인함 · <b>'
        + (fee ? '댈 데 없음' : '없음') + '</b></span>'
        + '<button data-unknown="' + col.key + '">미확인으로</button></div>';
    }
    const list = v || [];
    if (!list.length) {
      return '<div class="point"><span class="val cap">미확인</span>'
        + '<button data-none="' + col.key + '">없음</button></div>';
    }
    const fees = [['', '미확인']].concat(DATA.parkingFee.map(function (f) {
      return [f, f];
    }));
    return '<div class="parks" id="f_' + col.key + '">' + list.map(function (p, i) {
      return '<div class="one"><span class="nm">' + esc(p.name || '이름 없음')
        + ' <span class="cap">' + p.lat.toFixed(5) + ', ' + p.lon.toFixed(5)
        + '</span></span>'
        + (fee ? pickHtml('f_' + col.key + '_fee_' + i, fees, p.fee || '') : '')
        + '<button data-placedrop="' + col.key + ':' + i + '">빼기</button></div>';
    }).join('') + '</div>'
      + '<div class="hint">'
      + (fee
          ? '자리를 더 두려면 [주차 후보] 에서 [지정] 하거나 지도를 우클릭한다. '
            + '자리가 둘 이상이면 <b>경로도 어느 자리에서 시작하는지</b>를 고르게 된다'
          : '더 두려면 위 주변 목록에서 [지정] 하거나 지도를 우클릭한다')
      + '</div>';
  }

  /* 예·아니오는 3단이다 — 파일 규약이 "없는 키가 곧 미확인"이라, 아니오를 적는 것과
     아직 안 본 것을 같은 칸으로 두면 그 구분이 화면에서 사라진다. */
  function segHtml(id, v, opts) {
    opts = opts || [['', '미확인'], ['yes', '예'], ['no', '아니오']];
    return pickHtml(id, opts, v === true ? 'yes' : v === false ? 'no' : '');
  }

  /* 낱말을 그대로 값으로 쓰는 3단(주차 요금). 예·아니오와 모양은 같은데 값이
     true·false 가 아니라서, 고른 것을 문자열로 받는 자리를 따로 둔다. */
  function pickHtml(id, opts, now) {
    return '<div class="seg" id="' + id + '">' + opts.map(function (o) {
      return '<button type="button" data-v="' + esc(o[0]) + '"'
        + (o[0] === now ? ' class="on"' : '') + '>' + esc(o[1]) + '</button>';
    }).join('') + '</div>';
  }

  function bindFields() {
    DATA.columns.forEach(function (col) {
      const node = el('f_' + col.key);
      if (!node) return;

      if (col.type === 'bool') {
        bindSeg(node, function (v) {
          setValue(col.key, v === '' ? null : v === 'yes');
        });
      } else if (col.type === 'flags') {
        DATA.flagKeys.forEach(function (k) {
          bindSeg(el('f_' + col.key + '_' + k), function (v) {
            const now = Object.assign({}, value(col.key) || {});
            /* '미확인'은 키를 지우는 것이다 — 이 파일에서 없는 키가 곧 미확인이라
               false 로 두면 '가 봤는데 없다'가 되어 다른 말이 된다. */
            if (v === '') delete now[k]; else now[k] = v === 'yes';
            setValue(col.key, Object.keys(now).length ? now : null);
          });
        });
      } else if (col.type === 'parking') {
        places(col.key).forEach(function (_, i) {
          bindSeg(el('f_' + col.key + '_fee_' + i), function (fee) {
            setPlaces(col.key, places(col.key).map(function (lot, j) {
              if (j !== i) return lot;
              const next = Object.assign({}, lot);
              if (fee) next.fee = fee; else delete next.fee;
              return next;
            }));
          });
        });
      } else if (col.type === 'list') {
        node.oninput = function () {
          setValue(col.key, node.value.split('\\n'));
        };
      } else if (col.type === 'text' || col.type === 'textarea'
                 || col.type === 'choice' || col.type === 'number') {
        node.oninput = function () { setValue(col.key, node.value); };
      }
    });

    /* 세 상태를 오가는 세 버튼. 비우기·미확인으로는 키를 지우고(= 미확인),
       없음은 false 를 넣는다(= 확인했고 없다). */
    [['clear', null], ['unknown', null], ['none', false]].forEach(function (spec) {
      document.querySelectorAll('[data-' + spec[0] + ']').forEach(function (btn) {
        btn.onclick = function () {
          setValue(btn.dataset[spec[0]], spec[1]);
          renderForm();
        };
      });
    });
    /* 목록에서 자리 하나를 뺀다(`<칸 키>:<번호>` — 경로 점의 [빼기](`data-drop`)와
       이름이 겹치면 한쪽 처리기가 둘 다 잡는다). 목록이 비면 `setPlaces` 가 키를
       지우므로 다시 미확인이 된다 — '확인했고 없다'는 [없음] 으로만 적힌다. */
    document.querySelectorAll('[data-placedrop]').forEach(function (btn) {
      const at = btn.dataset.placedrop.split(':');
      btn.onclick = function () { dropPlace(at[0], Number(at[1])); };
    });
    /* 값이 곧 시작할 주차 자리 번호다(-1 이면 코드가 고른다 — 자리가 하나뿐이거나
       아예 없을 때). 찍는 중에는 이 단추 자리에 [끝내기]·[멈추기] 가 선다. */
    document.querySelectorAll('[data-draw]').forEach(function (btn) {
      btn.onclick = function () { startDraw(Number(btn.dataset.draw)); };
    });
    document.querySelectorAll('[data-goroute]').forEach(function (btn) {
      btn.onclick = scrollToRoute;
    });
    /* 끝내는 길이 둘이다 — 관측 자리에 끝점을 놓고 끝내거나(정상), 아직 다 못
       찍었으니 그냥 멈추거나. 뒤엣것은 점을 건드리지 않으므로 초안도 그대로다. */
    document.querySelectorAll('[data-finish]').forEach(function (btn) {
      btn.onclick = finishDraw;
    });
    document.querySelectorAll('[data-stop]').forEach(function (btn) {
      btn.onclick = function () { drawing = false; renderForm(); };
    });
    /* 잘못 찍은 점 하나를 뺀다 — 마지막 점만이 아니라 가운데도 뺀다. 다시 그리는
       것과 한 점을 무르는 것은 다른 일이다. */
    document.querySelectorAll('[data-drop]').forEach(function (btn) {
      btn.onclick = function () { dropPoint(Number(btn.dataset.drop)); };
    });
    /* [상세설정] — 편 것을 다시 접을 수도 있어야 한다. 경로 칸은 이미 길고, 다 적은
       길의 구간표가 계속 펴져 있으면 아래 칸들이 화면 밖으로 밀린다. */
    document.querySelectorAll('[data-detail]').forEach(function (btn) {
      btn.onclick = function () {
        detailOpen = !detailOn(activeRoute());
        renderForm();
      };
    });
    /* 상세설정 안에서 한 조작은 상세설정을 **열린 채로 붙잡는다**. 자동 펼침은
       '적어 둔 것이 있으면'이라, 마지막 구간을 지우는 순간 그 조건이 무너지면서
       방금까지 손대고 있던 칸이 통째로 사라진다. */
    document.querySelectorAll('[data-addseg]').forEach(function (btn) {
      btn.onclick = function () {
        addSegment(Number(btn.dataset.addseg));
        detailOpen = true;
        renderForm();
      };
    });
    document.querySelectorAll('[data-segdel]').forEach(function (btn) {
      btn.onclick = function () {
        dropSegment(Number(btn.dataset.segdel));
        detailOpen = true;
        renderForm();
      };
    });
    document.querySelectorAll('[data-clearseg]').forEach(function (btn) {
      btn.onclick = function () {
        const n = segments(activeRoute()).length;
        if (!confirm('구간 ' + n + '개를 모두 지울까요?\\n'
                     + '거기 적어 둔 노면상태·암릉암반·특색도 함께 사라집니다.')) {
          return;
        }
        editRoute(active, { segments: [] });
        detailOpen = true;
        renderForm();
      };
    });
    document.querySelectorAll('[data-sfrom]').forEach(function (node) {
      node.onchange = function () {
        moveSegment(Number(node.dataset.sfrom), Number(node.value));
        renderForm();          /* 구간 경계는 지도 선 색이라 곧바로 다시 그린다 */
      };
    });
    /* 길을 지우면 찍는 모드도 함께 끈다 — 점이 하나도 없는 채로 모드만 켜져 있으면
       지도를 눌러도 아무 일이 없어서 고장으로 보인다. */
    document.querySelectorAll('[data-delroute]').forEach(function (btn) {
      btn.onclick = function () {
        const i = Number(btn.dataset.delroute);
        const list = routes();
        if (points(list[i]).length
            && !confirm(routeName(list[i], i) + ' 을 지울까요?')) return;
        setRoutes(list.filter(function (_, j) { return j !== i; }));
        drawing = false;
        detailOpen = null;
        renderForm();
      };
    });
    /* 길을 통째로 비운다. [이 길 지우기] 를 길 수만큼 누르게 하지 않는다 — 갈래가
       셋이면 그것이 곧 세 번의 확인이고, 그 사이 한 번이라도 엉뚱한 길이 골라져
       있으면 남기려던 것을 지운다. */
    document.querySelectorAll('[data-delall]').forEach(function (btn) {
      btn.onclick = function () {
        const list = routes();
        if (!confirm('이 관측지의 길 ' + list.length + '개를 모두 지울까요?\\n'
                     + list.map(function (x, i) { return '· ' + routeName(x, i); })
                       .join('\\n'))) return;
        setRoutes([]);
        drawing = false;
        detailOpen = null;
        renderForm();
      };
    });
    document.querySelectorAll('[data-pickroute]').forEach(function (btn) {
      btn.onclick = function () {
        active = Number(btn.dataset.pickroute);
        drawing = false;
        detailOpen = null;
        renderForm();
      };
    });
    document.querySelectorAll('[data-addroute]').forEach(function (btn) {
      btn.onclick = addRoute;
    });
    /* 글자를 치는 칸들은 다시 그리지 않는다 — 한 글자마다 다시 그리면 커서가
       칸 밖으로 튄다. 대신 위 목록의 이름표만 그 자리에서 바꿔 준다. */
    document.querySelectorAll('[data-rname]').forEach(function (node) {
      node.oninput = function () {
        const i = Number(node.dataset.rname);
        editRoute(i, { name: node.value });
        const nm = document.querySelector('[data-pickroute="' + i + '"] .nm');
        if (nm) nm.textContent = routeName(routes()[i], i);
      };
    });
    bindSeg(el('tr_' + active), function (v) {
      editRoute(active, { terrain: v });
      detailOpen = true;       /* 지형도 상세설정 안에 있다 — 접히면 안 된다 */
      renderForm();            /* 배점표가 바뀌므로 등급을 다시 낸다 */
    });
    document.querySelectorAll('[data-snote]').forEach(function (node) {
      node.oninput = function () {
        editSegment(Number(node.dataset.snote), { note: node.value });
      };
    });
    segments(activeRoute()).forEach(function (_, i) {
      bindSeg(el('sf_' + i), function (v) {
        editSegment(i, { surface: v });
        renderForm();          /* 노면은 지도 선 색이라 곧바로 다시 그린다 */
      });
      bindSeg(el('rk_' + i), function (v) {
        editSegment(i, { rock: v });
        renderForm();          /* 등급이 바뀐다 */
      });
    });
    document.querySelectorAll('[data-copy]').forEach(function (btn) {
      btn.onclick = function () {
        navigator.clipboard.writeText(btn.dataset.copy).then(function () {
          btn.textContent = '복사됨';
          setTimeout(function () { btn.textContent = '복사'; }, 1200);
        });
      };
    });
  }

  function bindSeg(seg, onpick) {
    if (!seg) return;
    seg.querySelectorAll('button').forEach(function (btn) {
      btn.onclick = function () {
        seg.querySelectorAll('button').forEach(function (b) {
          b.classList.toggle('on', b === btn);
        });
        onpick(btn.dataset.v);
      };
    });
  }

  /* --- 상세 화면 ------------------------------------------------------------ */
  function siteRows(s) {
    const num = function (v, digits, unit) {
      return (v === null || v === undefined) ? '—' : v.toFixed(digits) + (unit || '');
    };
    return [
      ['광공해 종합', s.score === null
        ? '<span class="cap">격자 밖 — 판정 없음</span>'
        : s.score.toFixed(3) + ' <span class="cap">· ' + esc(s.cap) + '</span>'],
      ['광공해 등급', s.falchi
        ? 'Falchi ' + s.falchi + ' <span class="cap">· Bortle ' + s.bortle + '</span>'
        : '—'],
      ['하늘 밝기', num(s.sqm, 2, ' SQM')],
      ['은하수', MILKY[s.milkyWay] || '—'],
      ['최근접 가로등', s.nearestM === null ? '1km 안에 없음'
        : s.nearestM.toFixed(0) + ' m'],
      ['가로등 100m/500m/1km', s.lampNear + ' / ' + s.lampMid + ' / ' + s.lampFar],
      ['야간광 1km 최대', num(s.viirsNear, 2)]
    ];
  }

  function dl(rows) {
    return '<dl>' + rows.map(function (r) {
      return '<dt>' + r[0] + '</dt><dd>' + r[1] + '</dd>';
    }).join('') + '</dl>';
  }

  function toiletHtml() {
    if (!ctx) return '<div class="empty">재는 중…</div>';
    const t = ctx.toilets;
    if (!t.list.length) {
      return '<div class="empty">' + t.radiusM + 'm 안에 없다'
        + (t.nearest ? ' · 가장 가까운 곳은 <b>' + esc(t.nearest.name) + '</b> '
                       + fmtDist(t.nearest.distanceM) : '')
        + '</div>';
    }
    return '<ul class="near">' + t.list.map(function (x, i) {
      return '<li><span class="d">' + x.distanceM + 'm</span>'
        + '<span class="t"><b>' + esc(x.name) + '</b>'
        + '<span>' + esc(x.kind) + ' · ' + esc(x.hours || '개방시간 미상')
        + (x.bell ? ' · 비상벨' : '') + '</span></span>'
        + '<button data-toilet="' + i + '">지정</button></li>';
    }).join('') + '</ul>';
  }

  function storeHtml() {
    if (!ctx) return '<div class="empty">재는 중…</div>';
    const s = ctx.stores;
    if (!s.list.length) {
      return '<div class="empty">' + (s.radiusM / 1000)
        + 'km 안에 편의점이 없다 — 오는 길에 들러야 한다.</div>';
    }
    return '<ul class="near">' + s.list.map(function (x, i) {
      return '<li><span class="d">' + fmtDist(x.distanceM) + '</span>'
        + '<span class="t"><b>' + esc(x.name) + '</b>'
        + '<span>' + esc(x.address || '') + '</span></span>'
        + '<button data-store="' + i + '">지정</button></li>';
    }).join('') + '</ul>'
      + (s.total > s.list.length
          ? '<div class="empty" style="margin-top:6px">가까운 ' + s.list.length
            + '곳만 — ' + (s.radiusM / 1000) + 'km 안에 ' + s.total + '곳</div>'
          : '');
  }

  function parkingHtml() {
    if (!ctx) return '<div class="empty">재는 중…</div>';
    const p = ctx.parking;
    if (!p.list.length) {
      return '<div class="empty">' + (p.radiusM / 1000) + 'km 안에 등록된 주차장이 '
        + '없다 — 지도에서 우클릭해 직접 지정한다.</div>';
    }
    return '<ul class="near">' + p.list.map(function (x, i) {
      return '<li><span class="d">' + fmtDist(x.distanceM) + '</span>'
        + '<span class="t"><b>' + esc(x.name) + '</b>'
        + '<span>' + esc(x.source) + ' · ' + esc(x.detail || '') + '</span></span>'
        + '<button data-park="' + i + '">지정</button></li>';
    }).join('') + '</ul>'
      + (p.total > p.list.length
          ? '<div class="empty" style="margin-top:6px">가까운 ' + p.list.length
            + '곳만 — 1km 안에 ' + p.total + '곳</div>'
          : '');
  }

  function fmtDist(m) { return m >= 1000 ? (m / 1000).toFixed(1) + 'km' : m + 'm'; }

  function renderDetail() {
    const r = row();
    if (!r) {
      el('detail').innerHTML = '<h3>관측지를 고르세요</h3>'
        + '<p class="sub">지도의 점이나 왼쪽 목록에서 고르면 그 자리의 광공해·주변'
        + '·로드뷰가 뜨고, 아래에서 칸을 채울 수 있습니다.</p>';
      return;
    }
    const s = r.site;
    el('detail').innerHTML =
      '<h3>' + esc(r.values.name_ko) + '</h3>'
      + '<div class="sub">' + esc(r.values.region || '') + ' · '
      + esc(r.values.type || '') + ' · 좌표 ' + esc(r.values.coord_confidence || '?')
      + (r.values.discovery ? ' · <b>자동 발굴</b>(미검증)' : '') + '</div>'
      + '<div id="rv"></div>'
      + dl(siteRows(s))
      + '<div class="sub"><a target="_blank" rel="noopener" href="'
      + 'https://map.kakao.com/link/map/' + encodeURIComponent(r.values.name_ko) + ','
      + r.values.lat + ',' + r.values.lon + '">카카오맵에서 보기 →</a></div>'
      + '<section><h2>화장실 <span class="cap" id="tN"></span></h2>'
      + '<div id="toilets"></div></section>'
      + '<section><h2>주차 후보</h2><div id="parking"></div></section>'
      /* 경로는 주차 지점에서 시작하므로 주차 바로 다음에 둔다. 찍는 일은 지도에서
         일어나지만 **되짚는 자리는 여기**다 — 몇 번째 점이 어디인지. */
      + '<section><h2>경로 <span class="cap" id="rtN"></span></h2>'
      + '<div id="route"></div></section>'
      + '<section><h2>가게 <span class="cap" id="sN"></span></h2>'
      + '<div id="stores"></div></section>'
      + '<section><h2>기입 <button id="addCol" style="font:inherit;font-size:11px;'
      + 'padding:2px 7px;cursor:pointer;background:transparent;color:var(--ink-2);'
      + 'border:1px solid var(--hairline);border-radius:5px">+ 컬럼</button></h2>'
      + '<div id="form"></div>'
      + '<div class="acts"><button class="primary" id="save">저장</button>'
      + '<button id="revert">되돌리기</button>'
      + '<button class="danger" id="del">지우기</button></div>'
      + '<div class="status" id="status"></div></section>';

    renderNear();
    renderForm();
    el('addCol').onclick = openColumnDialog;
    el('save').onclick = save;
    el('revert').onclick = function () { draft = {}; renderForm(); renderList(); };
    el('del').onclick = remove;
    showRoadview(r);
  }

  function renderNear() {
    if (!el('toilets')) return;
    el('toilets').innerHTML = toiletHtml();
    el('parking').innerHTML = parkingHtml();
    el('stores').innerHTML = storeHtml();
    el('tN').textContent = ctx
      ? '반경 ' + ctx.toilets.radiusM + 'm · ' + ctx.toilets.list.length + '곳' : '';
    el('sN').textContent = ctx
      ? '반경 ' + (ctx.stores.radiusM / 1000) + 'km · ' + ctx.stores.total + '곳' : '';

    /* [지정] 은 후보 한 줄을 그 칸의 값으로 옮긴다. 가게는 관측 전에 들르는 한
       곳이라 **갈아 끼우고**, 주차·화장실은 여럿일 수 있어 **더한다**. */
    document.querySelectorAll('[data-store]').forEach(function (btn) {
      btn.onclick = function () {
        setPoint('store', ctx.stores.list[Number(btn.dataset.store)]);
      };
    });
    [['park', 'parking', 'parking'], ['toilet', 'toilet', 'toilets']]
      .forEach(function (spec) {
        document.querySelectorAll('[data-' + spec[0] + ']').forEach(function (btn) {
          btn.onclick = function () {
            addPlace(spec[1], ctx[spec[2]].list[Number(btn.dataset[spec[0]])]);
          };
        });
      });
  }

  function renderForm() {
    if (!el('form')) return;
    /* 점을 하나 찍을 때마다 칸 전체를 다시 그린다. 보던 자리를 되돌려 놓지 않으면
       우클릭할 때마다 오른쪽 화면이 위로 튀어 목록을 읽을 수 없다. */
    const box = el('detail'), top = box.scrollTop;
    el('form').innerHTML = DATA.columns.map(fieldHtml).join('');
    renderRoute();
    box.scrollTop = top;
    bindFields();
    renderActions();
    drawNear(row());
  }

  /* 점을 하나 찍을 때마다 다시 그린다. `bindFields` 가 이 안의 단추들(빼기·끝내기)
     까지 함께 묶으므로 그보다 **먼저** 불려야 한다. */
  function renderRoute() {
    if (!el('route')) return;
    el('route').innerHTML = routeHtml();
    const list = routes();
    const pts = points(activeRoute());
    el('rtN').textContent = !list.length ? ''
      : (list.length > 1 ? list.length + '갈래 · ' : '')
        + (pts.length ? pts.length + '점 · ' + fmtDist(Math.round(routeLength(pts)))
                      : '아직 안 찍었다');
  }

  function renderActions() {
    const saveBtn = el('save'), revertBtn = el('revert');
    if (!saveBtn) return;
    saveBtn.disabled = !dirty();
    revertBtn.disabled = !dirty();
    if (!dirty() && el('status').className === 'status') el('status').textContent = '';
  }

  function setPoint(key, p) {
    setValue(key, { name: p.name, lat: p.lat, lon: p.lon });
    renderForm();
  }

  function showRoadview(r) {
    const box = el('rv');
    if (!rvClient) rvClient = new kakao.maps.RoadviewClient();
    const pos = new kakao.maps.LatLng(r.values.lat, r.values.lon);
    /* 반경 100m 안에 파노라마가 없으면 로드뷰가 없는 곳이다(농로·사유지 진입로).
       그 자체가 검증에 쓰이는 정보라 빈칸으로 두지 않고 그렇다고 적는다. */
    rvClient.getNearestPanoId(pos, 100, function (panoId) {
      if (panoId === null) {
        box.className = 'none';
        box.textContent = '이 자리 100m 안에 로드뷰가 없습니다';
        return;
      }
      box.className = '';
      roadview = new kakao.maps.Roadview(box);
      roadview.setPanoId(panoId, pos);
    });
  }

  /* --- 목록 ---------------------------------------------------------------- */
  function filled(r) {
    let n = 0;
    DATA.columns.forEach(function (c) {
      if (c.type === 'coords') { n++; return; }
      const v = r.values[c.key];
      if (v !== undefined && v !== null && v !== ''
          && !(Array.isArray(v) && !v.length)) n++;
    });
    return n;
  }

  function visible(r) {
    const q = el('q').value.trim();
    if (q && (r.values.name_ko + ' ' + (r.values.name_en || '') + ' '
              + (r.values.notes || '') + ' ' + (r.values.why || '')).indexOf(q) < 0) {
      return false;
    }
    const region = el('fRegion').value, type = el('fType').value;
    if (region && r.values.region !== region) return false;
    if (type && r.values.type !== type) return false;
    if (el('fTodo').checked && filled(r) === DATA.columns.length) return false;
    if (el('fToilet').checked && !r.hasToilet) return false;
    return true;
  }

  function renderList() {
    const rows = DATA.spots.filter(visible);
    el('listCount').textContent = rows.length + ' / ' + DATA.spots.length;
    el('list').innerHTML = rows.map(function (r) {
      const n = filled(r), total = DATA.columns.length;
      const color = r.site.cap ? DATA.colors.cap[r.site.cap] : DATA.colors.noGrid;
      return '<button class="item' + (r.index === selected ? ' on' : '')
        + '" data-i="' + r.index + '">'
        + '<span class="nm"><span class="dot" style="background:' + color
        + '"></span>' + esc(r.values.name_ko) + '</span>'
        + '<span class="mt">' + (r.site.score === null ? '판정 없음'
            : r.site.score.toFixed(3) + ' · ' + esc(r.site.cap))
        + (r.hasToilet ? ' · 화장실' : '')
        + '<span class="fill"><i style="width:' + (100 * n / total) + '%"></i></span>'
        + ' ' + n + '/' + total + '</span></button>';
    }).join('');
    el('list').querySelectorAll('.item').forEach(function (btn) {
      btn.onclick = function () { select(Number(btn.dataset.i)); };
    });
  }

  /* --- 고르기 --------------------------------------------------------------- */
  function select(i) {
    if (dirty() && i !== selected
        && !confirm('저장하지 않은 값이 있습니다. 버리고 옮길까요?')) return;
    selected = i;
    draft = {};
    ctx = null;
    drawing = false;
    active = 0;
    detailOpen = null;
    highlight();
    renderList();
    renderDetail();
    const r = row();
    map.panTo(new kakao.maps.LatLng(r.values.lat, r.values.lon));
    if (map.getLevel() > 5) map.setLevel(5);
    fetch('/api/context?lat=' + r.values.lat + '&lon=' + r.values.lon)
      .then(function (res) { return res.json(); })
      .then(function (payload) {
        if (selected !== i) return;
        ctx = payload;
        renderNear();
        drawNear(r);
      })
      .catch(function (err) { alert('주변 조회 실패: ' + err); });
  }

  /* --- 경로 찍기 -------------------------------------------------------------
     누른 순서가 곧 경로다. 새 점은 언제나 끝에 붙고, 되돌리기는 마지막 점을
     뗀다 — 찍는 동안 화면이 하는 일은 이 둘뿐이다.

     첫 점만 코드가 놓는다. 도보 경로는 정의상 **주차 자리에서 시작**하는데 그
     좌표는 이미 지정돼 있으므로, 같은 자리를 눈대중으로 다시 찍게 하면 몇 m 씩
     어긋난 시작점만 쌓인다. 주차 지점이 아직 없으면 그대로 첫 우클릭이 첫 점이다.

     주차 자리가 둘 이상이면 코드가 고르지 않는다 — 어느 들머리에서 오르는 길인지가
     그 길의 정체이고, 짐작해서 놓은 첫 점은 나중에 아무도 틀린 줄 모른다. 그때는
     [그리기] 자리에 자리마다 단추가 서고, 누른 자리가 첫 점이 된다. */
  function addRoute() {
    setRoutes(routes().concat([{ name: '', points: [] }]));
    active = routes().length - 1;
    drawing = false;
    detailOpen = null;
    startDraw(-1);
  }

  /* `at` 은 시작할 주차 자리 번호. -1 이면 코드가 고른다 — 자리가 하나뿐이면 그것,
     아직 없으면 아무것도 놓지 않는다(첫 우클릭이 첫 점이다). */
  function startDraw(at) {
    if (drawing) { drawing = false; renderForm(); return; }
    if (!routes().length) setRoutes([{ name: '', points: [] }]);
    if (!points(activeRoute()).length) {
      const list = lots();
      const lot = at >= 0 ? list[at] : (list.length === 1 ? list[0] : null);
      if (lot) editRoute(active, { points: [[lot.lat, lot.lon]] });
    }
    drawing = true;
    renderForm();
    /* 켤 때 [경로] 칸을 화면 안으로 끌어온다. 우클릭 메뉴에서 켜면 오른쪽은 보던
       자리에 그대로 있어서, 점을 찍어도 목록이 화면 밖이면 확인할 수가 없다. */
    scrollToRoute();
  }

  function scrollToRoute() {
    const box = el('route');
    if (box) box.parentNode.scrollIntoView({ block: 'center' });
  }

  /* 끝점은 코드가 놓는다 — 첫 점(주차 지점)과 같은 이유다. 관측 좌표는 이미
     정해져 있으므로 그 자리를 눈대중으로 다시 찍으면 몇 m 어긋난 끝점만 남고,
     경로가 관측 자리에서 끝났는지를 나중에 아무도 알 수 없게 된다.

     이미 끝점이 관측 좌표면 다시 넣지 않는다(같은 점이 둘 쌓이면 0m 구간이 생긴다).
     점이 하나도 없으면 끝낼 경로가 없는 것이라 그냥 끈다 — 관측 좌표 한 점만 남는
     '경로'는 저장도 되지 않는다. */
  function finishDraw() {
    const pts = points(activeRoute()).slice();
    drawing = false;
    if (pts.length && !isSite(pts[pts.length - 1])) {
      const c = value('coords');
      pts.push([c.lat, c.lon]);
      editRoute(active, { points: pts });
    }
    renderForm();
  }

  function addRoutePoint(latLng) {
    editRoute(active,
      { points: points(activeRoute()).concat([[latLng.getLat(), latLng.getLng()]]) });
    renderForm();
  }

  /* 점을 빼면 구간 경계도 함께 밀린다 — 인덱스만 남겨 두면 다음에 열었을 때 구간이
     한 점씩 어긋난 채로 그려진다. 경계가 겹치게 되면 뒤엣것이 이긴다(방금 뺀 점에서
     시작하던 구간이 앞 구간에 흡수되는 것이 아니라 그 자리를 물려받는다). */
  function dropPoint(i) {
    const r = activeRoute();
    const pts = points(r).slice();
    pts.splice(i, 1);
    const segs = [];
    segments(r).forEach(function (s) {
      const from = s.from > i ? s.from - 1 : s.from;
      if (from > pts.length - 1) return;         /* 경로 끝이 잘려 나갔다 */
      const moved = Object.assign({}, s, { from: from });
      if (segs.length && segs[segs.length - 1].from === from) segs.pop();
      segs.push(moved);
    });
    if (segs.length) segs[0] = Object.assign({}, segs[0], { from: 0 });
    editRoute(active, { points: pts, segments: segs });
    renderForm();
  }

  /* --- 우클릭: 이 좌표를 무엇으로 쓸까 ---------------------------------------- */
  kakao.maps.event.addListener(map, 'rightclick', function (e) {
    if (selected < 0) return;
    /* 찍는 동안에는 우클릭이 곧 점 찍기다. 메뉴를 함께 띄우면 점마다 두 번
       눌러야 해서, 20~30곳을 찍는 일에는 그 한 번이 그대로 손해다. */
    if (drawing) { addRoutePoint(e.latLng); return; }
    picking = { lat: e.latLng.getLat(), lon: e.latLng.getLng() };
    const menu = el('menu');
    menu.innerHTML = '<div class="co">' + picking.lat.toFixed(6) + ', '
      + picking.lon.toFixed(6) + '</div>'
      + '<button data-as="route">'
      + (points(activeRoute()).length
          ? (routes().length > 1 ? routeName(activeRoute(), active) + ' 이어 찍기'
                                 : '경로 이어 찍기')
          : '경로 그리기')
      + '</button>'
      + '<button data-as="parking">'
      + (lots().length ? '주차 자리로 하나 더' : '주차 지점으로') + '</button>'
      + '<button data-as="toilet">'
      + (places('toilet').length ? '화장실 하나 더' : '화장실 위치로') + '</button>'
      + '<button data-as="store">가게 위치로</button>'
      + '<button data-as="coords">관측 좌표로 옮기기</button>'
      + '<button data-as="measure">이 자리 광공해 보기</button>';
    const p = map.getProjection().containerPointFromCoords(e.latLng);
    menu.style.left = p.x + 'px';
    menu.style.top = p.y + 'px';
    menu.style.display = 'block';
    menu.querySelectorAll('button').forEach(function (btn) {
      btn.onclick = function () { pickAs(btn.dataset.as); };
    });
  });
  document.addEventListener('click', function () {
    el('menu').style.display = 'none';
  });
  el('map').addEventListener('contextmenu', function (e) { e.preventDefault(); });

  /* 목록에 없는 자리도 지정할 수 있어야 한다 — 오름 초입 갓길, 원본에 없는 화장실.
     칸이 늘어도 여기 손댈 것이 없게 형식마다 한 길로 보낸다. 갈리는 것은 **갈아
     끼우는가 더하는가** 하나뿐이다(`point` 는 앞, 여러 자리를 담는 칸은 뒤). */
  const POINT_LABEL = { store: '가게' };
  const PLACE_LABEL = { parking: '주차 자리', toilet: '화장실' };

  function pickAs(what) {
    el('menu').style.display = 'none';
    if (!picking) return;
    /* 찍기는 우클릭으로 하는데 켜는 단추만 오른쪽 패널 아래에 있으면, 지도를
       보다가 그 칸을 찾아 내려가야 한다. 그래서 메뉴에서도 켠다 — 이때 방금
       우클릭한 자리는 버리지 않고 그대로 경로에 넣는다(메뉴의 다른 항목들도
       모두 그 좌표를 쓴다). */
    if (what === 'route') {
      if (!drawing) startDraw(-1);
      addRoutePoint(new kakao.maps.LatLng(picking.lat, picking.lon));
      return;
    }
    if (PLACE_LABEL[what]) {
      const name = prompt(PLACE_LABEL[what] + ' 이름 (비워도 된다)', '');
      if (name === null) return;
      addPlace(what, { name: name.trim(), lat: picking.lat, lon: picking.lon });
      return;
    }
    if (POINT_LABEL[what]) {
      const name = prompt(POINT_LABEL[what] + ' 이름 (비워도 된다)', '');
      if (name === null) return;
      setPoint(what, { name: name.trim(), lat: picking.lat, lon: picking.lon });
    } else if (what === 'coords') {
      setValue('coords', { lat: picking.lat, lon: picking.lon });
      renderForm();
    } else {
      fetch('/api/context?lat=' + picking.lat + '&lon=' + picking.lon)
        .then(function (r) { return r.json(); })
        .then(function (payload) {
          const s = payload.site;
          alert(picking.lat.toFixed(6) + ', ' + picking.lon.toFixed(6) + '\\n'
            + (s.score === null ? '격자 밖 — 판정 없음'
               : '광공해 종합 ' + s.score.toFixed(3) + ' · ' + s.cap
                 + '\\nFalchi ' + s.falchi + ' · SQM ' + s.sqm.toFixed(2))
            + '\\n최근접 가로등 '
            + (s.nearestM === null ? '1km 안에 없음' : s.nearestM.toFixed(0) + 'm')
            + '\\n200m 안 화장실 ' + payload.toilets.list.length + '곳');
        });
    }
  }

  /* --- 저장 ---------------------------------------------------------------- */
  function save() {
    const r = row();
    const status = el('status');
    status.className = 'status';
    status.textContent = '저장 중…';
    fetch('/api/spot', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: r.index, values: draft })
    }).then(function (res) { return res.json(); }).then(function (res) {
      if (!res.ok) {
        status.className = 'status bad';
        status.textContent = res.error;
        return;
      }
      DATA.spots[r.index] = res.spot;
      draft = {};
      status.className = 'status good';
      status.textContent = '저장했습니다 · ' + res.at;
      /* 좌표를 옮겼으면 점도 따라가야 한다 — 지도와 파일이 다른 자리를 가리키면
         다음에 열었을 때 "왜 여기지"가 된다. */
      marks[r.index].setPosition(
        new kakao.maps.LatLng(res.spot.values.lat, res.spot.values.lon));
      highlight();
      renderList();
      renderDetail();
      ctx = res.context;
      renderNear();
      drawNear(DATA.spots[r.index]);
    }).catch(function (err) {
      status.className = 'status bad';
      status.textContent = '저장 실패: ' + err;
    });
  }

  /* 지우기. [되돌리기]는 아직 저장 안 한 값만 되돌리므로 이것은 **되돌릴 수 없다** —
     그래서 이름을 그대로 받아 적게 한다. 관측지 하나에는 좌표·출처·주의사항이 붙어
     있어서, 잘못 지우면 다시 찾는 데 그것을 모은 만큼 걸린다.

     지우고 나서는 화면을 다시 읽는다. 관측지를 **번호로** 가리키는 구조라(마커·
     선택·저장 요청이 모두 번호다) 가운데 하나가 빠지면 뒤 번호가 전부 한 칸씩
     밀린다. 지우는 일은 드무니 어긋날 자리를 만드는 것보다 다시 읽는 편이 낫다. */
  function remove() {
    const r = row();
    const name = r.values.name_ko || '이름 없는 관측지';
    /* `_HTML` 은 파이썬 일반 문자열이라 여기 적는 `\\n` 은 **두 자로** 써야 한다 —
       한 자로 쓰면 파이썬이 먼저 줄바꿈으로 바꿔서 이 JS 문자열이 그 자리에서
       끊긴다. */
    const typed = prompt(
      name + ' 을 지웁니다. 되돌릴 수 없습니다.\\n'
      + '지우려면 이름을 그대로 적으세요.', '');
    if (typed === null) return;
    const status = el('status');
    if (typed.trim() !== name) {
      status.className = 'status bad';
      status.textContent = '이름이 달라 지우지 않았습니다.';
      return;
    }
    status.className = 'status';
    status.textContent = '지우는 중…';
    fetch('/api/spot/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: r.index, name: name })
    }).then(function (res) { return res.json(); }).then(function (res) {
      if (!res.ok) {
        status.className = 'status bad';
        status.textContent = res.error;
        return;
      }
      location.reload();
    }).catch(function (err) {
      status.className = 'status bad';
      status.textContent = '지우기 실패: ' + err;
    });
  }

  /* --- 컬럼 추가 ------------------------------------------------------------ */
  function openColumnDialog() {
    el('colType').innerHTML = DATA.addable.map(function (t) {
      return '<option value="' + t[0] + '">' + esc(t[1]) + '</option>';
    }).join('');
    el('colStatus').textContent = '';
    el('colStatus').className = 'status';
    el('colDialog').showModal();
  }
  el('colCancel').onclick = function () { el('colDialog').close(); };
  el('colAdd').onclick = function () {
    const body = {
      key: el('colKey').value.trim(), label: el('colLabel').value.trim(),
      type: el('colType').value, help: el('colHelp').value.trim()
    };
    fetch('/api/column', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (!res.ok) {
        el('colStatus').className = 'status bad';
        el('colStatus').textContent = res.error;
        return;
      }
      DATA.columns = res.columns;
      el('colKey').value = el('colLabel').value = el('colHelp').value = '';
      el('colDialog').close();
      renderForm();
      renderList();
    });
  };

  /* --- 지도 종류 -------------------------------------------------------------
     로드뷰로도 안 보이는 것(초지 한가운데 자리·주차장 포장 여부·나무 그늘)은
     위성이 답한다. 고른 종류는 브라우저에 남긴다 — 이 도구는 고쳤다 껐다를
     자주 하는데 그때마다 다시 누르게 하지 않는다. */
  const MAP_TYPE_KEY = 'jejuSpots.mapType';

  function setMapType(name) {
    const id = kakao.maps.MapTypeId[name];
    if (!id) return;
    map.setMapTypeId(id);
    try { localStorage.setItem(MAP_TYPE_KEY, name); } catch (e) { /* 사생활 모드 */ }
    document.querySelectorAll('#maptype button').forEach(function (btn) {
      btn.classList.toggle('on', btn.dataset.map === name);
    });
  }

  document.querySelectorAll('#maptype button').forEach(function (btn) {
    btn.onclick = function () { setMapType(btn.dataset.map); };
  });

  let savedType = 'ROADMAP';
  try { savedType = localStorage.getItem(MAP_TYPE_KEY) || 'ROADMAP'; } catch (e) { }
  setMapType(savedType);

  /* --- 필터 --------------------------------------------------------------- */
  function option(list, all) {
    return '<option value="">' + all + '</option>' + list.map(function (v) {
      return '<option value="' + esc(v) + '">' + esc(v) + '</option>';
    }).join('');
  }
  el('fRegion').innerHTML = option(DATA.choices.region || [], '지역 전체');
  el('fType').innerHTML = option(DATA.choices.type || [], '유형 전체');
  ['q', 'fRegion', 'fType', 'fTodo', 'fToilet'].forEach(function (id) {
    el(id).oninput = renderList;
  });

  el('legend').innerHTML = DATA.legendHtml;
  renderList();
  renderDetail();
}
</script>
"""


def _legend_html() -> str:
    """지도 위 색이 무슨 뜻인지. 화면에서 바로 읽히게 둔다."""
    rows = [
        (color, f"어둡기 상한 {cap}") for cap, color in _CAP_COLOR.items()
    ] + [
        (_NO_GRID_COLOR, "격자 밖 — 판정 없음"),
        (_TOILET_COLOR, f"화장실 (반경 {toilet.WALK_M:g}m)"),
        (_PARKING_COLOR, f"주차 후보 ({_PARKING_M / 1000:g}km)"),
        (_STORE_COLOR, f"편의점 ({_STORE_M / 1000:g}km)"),
        (_PICK_COLOR, "지정해 둔 자리 (주차·화장실·가게)"),
        (_ROUTE_COLOR, "도보 경로 (사람이 찍은 선 · 현장 미검증)"),
    ] + [
        (color, f"└ 노면 {surface}")
        for surface, color in _SURFACE_COLOR.items()
    ] + [
        (_LAMP_COLOR, f"가로등 ({_LAMP_M / 1000:g}km, 최대 {_LAMP_LIMIT}개)"),
    ]
    body = "".join(
        f'<div class="row"><span class="sw" style="background:{color}"></span>'
        f"<span>{label}</span></div>"
        for color, label in rows
    )
    return f"<h2>범례</h2>{body}"


def build_page(key: str, store: Spots) -> str:
    """지도 페이지 한 장. 서버가 뜰 때 한 번 만든다.

    관측지 106곳의 어둡기는 여기서 한 번에 재서 싣는다(곳당 ≈2ms). 주변(화장실·
    주차·가로등)은 고를 때 `/api/context` 로 따로 받는다 — 106곳치를 미리 실으면
    페이지가 커지기만 하고, 대부분은 열어 보지도 않는다.
    """
    spots = store.spots
    columns = store.columns()
    rows = [spot_row(i, spot) for i, spot in enumerate(spots)]
    for row in rows:
        # 목록 필터('화장실 있는 곳만')가 쓰는 한 가지. 목록만 쓰는 값이라
        # 화장실 상세는 싣지 않는다 — 그건 고를 때 받는다.
        row["hasToilet"] = bool(toilet.near(row["values"]["lat"], row["values"]["lon"]))

    payload = {
        "view": {"bounds": [
            store.meta["jeju_bounds"]["lat_min"], store.meta["jeju_bounds"]["lon_min"],
            store.meta["jeju_bounds"]["lat_max"], store.meta["jeju_bounds"]["lon_max"],
        ]},
        "spots": rows,
        "columns": [vars(c) for c in columns],
        "choices": choices(spots, columns),
        "flagKeys": flag_keys(spots),
        "parkingFee": list(PARKING_FEE),
        "addable": [[t, _TYPE_LABEL[t]] for t in ADDABLE],
        "colors": {
            "cap": _CAP_COLOR, "noGrid": _NO_GRID_COLOR, "toilet": _TOILET_COLOR,
            "parking": _PARKING_COLOR, "store": _STORE_COLOR, "lamp": _LAMP_COLOR,
            "pick": _PICK_COLOR, "route": _ROUTE_COLOR,
            "surface": _SURFACE_COLOR,
        },
        # 눈금과 배점은 전부 `core.trail` 이 원문에서 들고 온 것이다. 화면은 그것을
        # 받아 **셈만** 한다 — 수를 두 곳에 적으면 언젠가 둘이 갈린다.
        "trail": {
            "surface": trail.SURFACE, "surfaceHelp": _SURFACE_HELP,
            "rock": trail.ROCK, "rockHelp": _ROCK_HELP,
            "terrain": trail.TERRAIN, "terrainHelp": _TERRAIN_HELP,
            "weight": trail.WEIGHT, "omitted": trail.OMITTED,
            "slopePct": {k: list(v) for k, v in trail._SLOPE_PCT.items()},
            "distanceM": {k: list(v) for k, v in trail._DISTANCE_M.items()},
            "grades": list(trail._GRADE), "hardest": trail.HARDEST,
            "source": trail.SOURCE,
        },
        "demSource": elevation.SOURCE,
        # 경로 길이는 화면이 찍을 때마다 다시 잰다. 같은 눈금·같은 근사를 쓰라고
        # 서버가 쓰는 값을 그대로 넘긴다.
        "kmPerDeg": lamps.KM_PER_DEG,
        "legendHtml": _legend_html(),
    }
    return (
        _HTML
        .replace("/*__KEY__*/", key)
        .replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False))
    )


#: 화면의 형식 고르기에 쓸 이름.
_TYPE_LABEL = {
    "text": "한 줄 글", "textarea": "여러 줄 글", "number": "숫자",
    "choice": "고르기(자유 입력 가능)", "bool": "예·아니오", "list": "목록(줄 단위)",
}


# --- 서버 ---------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    """지도 한 장과 쓰기 둘(관측지 값·컬럼 정의). 로컬 전용이라 그 이상 안 연다."""

    html: str
    store: Spots
    #: 페이지를 다시 만들 때 필요한 카카오 키. 페이지는 시작할 때 한 번 만들어 두는데,
    #: 지우기는 그 안에 박힌 관측지 목록을 바꾸므로 그 자리에서 다시 만들어야 한다 —
    #: 안 그러면 새로 고친 화면에 방금 지운 곳이 되살아나 보인다.
    key: str

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    # do_GET·do_POST 이름은 BaseHTTPRequestHandler 규약이라 바꿀 수 없다.
    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(200, self.html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if url.path != "/api/context":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        query = parse_qs(url.query)
        try:
            lat = float(query["lat"][0])
            lon = float(query["lon"][0])
        except (KeyError, IndexError, ValueError):
            self._json(400, {"ok": False, "error": "lat·lon 이 필요합니다"})
            return
        self._json(200, context(lat, lon))

    def do_POST(self) -> None:
        if self.path not in ("/api/spot", "/api/spot/delete", "/api/column"):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"ok": False, "error": "본문이 JSON 이 아닙니다"})
            return
        if self.path == "/api/spot":
            self._spot(request)
        elif self.path == "/api/spot/delete":
            self._delete(request)
        else:
            self._column(request)

    def _spot(self, request: dict) -> None:
        spots = self.store.spots
        try:
            index = int(request.get("index", -1))
        except (TypeError, ValueError):
            index = -1
        if not 0 <= index < len(spots):
            self._json(400, {"ok": False, "error": f"모르는 관측지 번호: {index}"})
            return

        values = request.get("values") or {}
        if not isinstance(values, dict):
            self._json(400, {"ok": False, "error": "values 가 사전이 아닙니다"})
            return

        # 사본에 먼저 적용한다 — 한 칸이 어긋나면 그 관측지는 손대지 않은 채로 둔다.
        draft = dict(spots[index])
        try:
            apply(draft, self.store.columns(), values)
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return

        spots[index] = draft
        self.store.flush()
        row = spot_row(index, draft)
        row["hasToilet"] = bool(toilet.near(draft["lat"], draft["lon"]))
        self._json(200, {
            "ok": True,
            "at": _now(),
            "spot": row,
            "context": context(draft["lat"], draft["lon"]),
        })

    def _delete(self, request: dict) -> None:
        """관측지 하나를 파일에서 뺀다. 되돌릴 수 없다.

        화면이 보낸 이름을 그 번호의 관측지와 **맞춰 본 뒤에** 지운다. 번호는 화면이
        연 뒤에 목록이 바뀌면 어긋날 수 있는 값이고(다른 창에서 지웠다든지), 어긋난
        번호로 지우면 **엉뚱한 곳이 조용히 사라진다**. 이름이 맞아야 지우는 것은
        화면에서 이름을 받아 적게 한 것과 같은 확인을 서버에서 한 번 더 하는 것이다.
        """
        spots = self.store.spots
        try:
            index = int(request.get("index", -1))
        except (TypeError, ValueError):
            index = -1
        if not 0 <= index < len(spots):
            self._json(400, {"ok": False, "error": f"모르는 관측지 번호: {index}"})
            return

        name = str(request.get("name", ""))
        actual = str(spots[index].get("name_ko", ""))
        if name != actual:
            self._json(400, {"ok": False, "error":
                             f"{index}번은 '{actual}' 입니다 — 목록이 바뀌었을 수 "
                             "있으니 화면을 새로 고치고 다시 하세요"})
            return

        spots.pop(index)
        self.store.flush()
        # 화면은 곧 새로 고친다. 시작할 때 만들어 둔 페이지에는 지운 곳이 아직 박혀
        # 있으므로 여기서 다시 만든다.
        Handler.html = build_page(Handler.key, self.store)
        print(f"지움: {actual} · 남은 {len(spots):,}곳 · {_now()}")
        self._json(200, {"ok": True, "at": _now(), "remaining": len(spots)})

    def _column(self, request: dict) -> None:
        key = str(request.get("key", "")).strip()
        label = str(request.get("label", "")).strip()
        type_ = str(request.get("type", "")).strip()
        help_ = str(request.get("help", "")).strip()

        if not _KEY_RE.match(key):
            self._json(400, {"ok": False, "error":
                             "키는 영문 소문자로 시작하는 2~30자(소문자·숫자·_)"})
            return
        if any(column.key == key for column in self.store.columns()):
            self._json(400, {"ok": False, "error": f"이미 있는 키: {key}"})
            return
        if key in _READONLY:
            error = f"{key} 는 도구가 붙이는 표식이라 칸으로 만들 수 없습니다"
            self._json(400, {"ok": False, "error": error})
            return
        if not label:
            self._json(400, {"ok": False, "error": "이름이 필요합니다"})
            return
        if type_ not in ADDABLE:
            self._json(400, {"ok": False, "error": f"만들 수 없는 형식: {type_}"})
            return

        self.store.add_column(key, label, type_, help_)
        self._json(200, {
            "ok": True, "columns": [vars(c) for c in self.store.columns()]
        })

    def log_message(self, fmt: str, *args) -> None:
        """기본 구현은 매 요청을 stderr 에 찍는다 — 저장 기록만 남기면 충분하다."""


def _now() -> str:
    """저장 시각. 화면이 "언제 적혔는지"를 그 자리에서 보여 준다."""
    return datetime.now(KST).isoformat(timespec="seconds")


def main() -> None:
    key = env.require(
        _KEY_VAR,
        "카카오 콘솔 [앱 키 → JavaScript 키] · "
        f"[플랫폼 → Web] 에 http://localhost:{_PORT} 등록",
    )

    store = Spots(path.SPOTS)
    Handler.store = store
    Handler.key = key
    Handler.html = build_page(key, store)

    try:
        server = Server(("127.0.0.1", _PORT), Handler)
    except OSError as exc:
        raise SystemExit(
            f"{_PORT} 포트를 이미 쓰고 있습니다 ({exc}).\n"
            "  `review_parking.py` 가 떠 있으면 그쪽을 먼저 끄세요 — 카카오 도메인\n"
            "  등록이 포트 단위라 두 도구가 같은 주소를 씁니다."
        ) from exc

    columns = store.columns()
    total = len(store.spots) * len(columns)
    done = sum(
        1
        for spot in store.spots
        for column in columns
        if column.type == "coords" or spot.get(column.key) not in (None, "", [], {})
    )
    print(f"관측지 {len(store.spots):,}곳 · 칸 {len(columns)}개 "
          f"(기입 {done:,}/{total:,} = {100 * done / total:.0f}%)")
    print(f"화장실 {toilet.COUNT:,}곳 · 주차 후보 "
          f"{parking.COUNT:,}(공영) + {places.COUNT:,}(카카오) · "
          f"가로등 {lamps.COUNT:,}개")
    print(f"기록 → {path.SPOTS.relative_to(path.ROOT)}")
    print(f"http://localhost:{_PORT}  (Ctrl+C 로 종료)")

    webbrowser.open(f"http://localhost:{_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료. 저장은 [저장]을 누를 때마다 이미 파일에 적혔습니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
