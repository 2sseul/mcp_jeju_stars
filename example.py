# 등록된 도구를 실제로 호출해 보는 예시입니다.

'''
도구를 등록하기 위해서는 컨테이너(MCP 서버 + NGROK)가 올라가 있는 상황에서,
- URL (엔드포인트): NGROK 상의 URL (http://localhost:4040 에서 확인)
- 도구이름: recommend_spots · evaluate_place · spot_details
- 설명: 원하는 설명 간략하게 기재

를 입력하고 등록하면 정상적으로 도구 스키마를 불러올 수 있음을 확인 가능합니다.

도구 셋은 **질문의 목적**으로 나뉘어 있습니다 (좌표냐 지명이냐로 나뉘지 않습니다).
    recommend_spots  "어디로 갈까"
    evaluate_place   "여기 별 보여?"
    spot_details     "거기 어때?"

응답의 numbers·attribution 은 문장과 분리되어 나갑니다 — 수치는 지어내지 말고
그대로 인용하면 됩니다. 경로 지도가 있으면 map_url 로 나갑니다.
'''
# 이미 외부 홈페이지에 도구를 등록했다는 가정하에 실시합니다.

import json

import requests

BASE_URL = "https://jejuax.ngrok.app/api/agent"
API_KEY = "{x-api-key}"  # 전달받은 API 키를 입력해야 합니다.

resp = requests.post(
    f"{BASE_URL}/v1/responses",
    headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
    json={
        "model": "jeju-tourism-agent",
        "input": "제주공항에서 30분 안에 갈 수 있고 "
                 "등산 없이 별 보기 좋은 곳 추천해줘.",
        "stream": False,
        "tools": [
            {
                "name": "recommend_spots",
            }  # 특정 TOOL 사용 강제
        ],
    },
)

resp.raise_for_status()
result = resp.json()

print(json.dumps(result, ensure_ascii=False, indent=2))
