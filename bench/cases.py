"""평가 케이스 24개 — TEST_GUIDELINE.md §4 의 구현.

한 케이스는 사람이 쓰듯 쓴 한국어 질문 하나와, 채점에 필요한 메타데이터다.

    gold_tool   기대 도구 이름 (None 이면 "도구를 부르면 안 된다")
    gold_args   arm T(tool-floor)가 정답을 만들 때 쓰는 인자. 그대로 MCP 에 넘어간다
    required    이 키들이 값까지 맞으면 인자 정답(AEM)
    accept      required 대신 인정하는 대안 인자 조합들 (하나라도 맞으면 정답)
    facts       답변에 실려야 하는 근거 값의 위치 (GFR 채점)
    abstain     "확인되지 않았다/범위 밖이다"를 밝혀야 하는 케이스인가
    forbid      나오면 안 되는 문구 (정규식)

`facts` 의 path 는 `spots[*].name` 처럼 쓴다 — `[*]` 는 배열 전체, `[0]` 은 첫 항목.
kind 는 'text'(공백 무시 부분일치) 또는 'num'(허용오차 안의 수가 답변에 있는가).

기준 날짜는 2026-08-20 (KST) 로 고정한다. 시스템 프롬프트가 모델에게 같은 날짜를
알려 주므로, 날짜를 인자로 넣는 케이스의 정답이 결정된다.
"""

TODAY = "2026-08-20"
TOMORROW = "2026-08-21"

# 추천 결과에 실리는 이름·수치.
# 이름은 고른 곳 **전부**를 본다 — 몇 곳을 골랐는지가 추천의 내용이다.
# 수치는 **1순위 한 곳만** 본다. limit=5 케이스에서 곳마다 수치를 다 요구하면
# 3~6문장 답변이 구조적으로 못 채우는 분모가 생겨, 모델 차이가 아니라 분모가
# 점수를 정하게 된다. 1순위의 구름·등급을 옮겼는지가 "수치를 인용하는가"를 가른다.
_REC_FACTS = [
    {"path": "spots[*].name", "kind": "text"},
    {"path": "spots[0].cloud_cover", "kind": "num", "tol": 1},
    {"path": "spots[0].bortle", "kind": "num", "tol": 0},
]
_REC_FACTS_DRIVE = _REC_FACTS + [
    {"path": "spots[*].drive.minutes", "kind": "num", "tol": 1.5},
]

CASES = [
    # ── recommend_spots (7) ────────────────────────────────────────────
    {
        "id": "R-01",
        "category": "recommend",
        "question": "제주공항에서 차로 40분 안에 갈 수 있는 별 보기 좋은 곳 3군데 알려줘.",
        "gold_tool": "recommend_spots",
        "gold_args": {"origin": "제주공항", "max_drive_minutes": 40, "limit": 3},
        "required": ["origin", "max_drive_minutes"],
        "facts": _REC_FACTS_DRIVE,
    },
    {
        "id": "R-02",
        "category": "recommend",
        "question": "제주 동쪽에서 별 보기 좋은 데 추천해줘.",
        "gold_tool": "recommend_spots",
        "gold_args": {"region": "동", "limit": 3},
        "required": ["region"],
        "facts": _REC_FACTS,
    },
    {
        "id": "R-03",
        "category": "recommend",
        "question": "등산은 못 하겠고, 안 올라가도 되는 별 관측지 알려줘.",
        "gold_tool": "recommend_spots",
        "gold_args": {"no_climb": True, "limit": 3},
        "required": ["no_climb"],
        "facts": _REC_FACTS,
    },
    {
        "id": "R-04",
        "category": "recommend",
        "question": "강아지 데리고 갈 수 있는 별 보는 곳 추천해줘.",
        "gold_tool": "recommend_spots",
        "gold_args": {"pets": True, "limit": 3},
        "required": ["pets"],
        "facts": _REC_FACTS,
    },
    {
        "id": "R-05",
        "category": "recommend",
        "question": "주차하고 걸어가지 않아도 바로 별 볼 수 있는 데 있을까?",
        "gold_tool": "recommend_spots",
        "gold_args": {"max_walk_minutes": 0, "limit": 3},
        "required": ["max_walk_minutes"],
        # 걷지 않는다 = 도보 0분으로도, 주차 확인된 곳으로도 옮길 수 있다
        "accept": [{"max_walk_minutes": 0}, {"parking_required": True}],
        "facts": _REC_FACTS,
    },
    {
        "id": "R-06",
        "category": "recommend",
        "question": "서귀포에서 출발해서 30분 안에 갈 수 있고 주차되는 곳으로 2군데만 골라줘.",
        "gold_tool": "recommend_spots",
        "gold_args": {
            "origin": "서귀포",
            "max_drive_minutes": 30,
            "parking_required": True,
            "limit": 2,
        },
        "required": ["origin", "max_drive_minutes", "limit"],
        "facts": _REC_FACTS_DRIVE,
    },
    {
        "id": "R-07",
        "category": "recommend",
        "question": "중산간 쪽에서 등산 없이 갈 수 있는 관측지 5곳 알려줘.",
        "gold_tool": "recommend_spots",
        "gold_args": {"region": "중산간", "no_climb": True, "limit": 5},
        "required": ["region", "no_climb", "limit"],
        "facts": _REC_FACTS,
    },

    # ── evaluate_place (8) ─────────────────────────────────────────────
    {
        "id": "E-01",
        "category": "evaluate",
        "question": "오늘 밤 10시에 새별오름에서 별 보여?",
        "gold_tool": "evaluate_place",
        "gold_args": {"query": "새별오름", "date": TODAY, "time": "22:00"},
        "required": ["query"],
        "facts": [
            {"path": "verdict", "kind": "text"},
            {"path": "numbers.cloud_cover", "kind": "num", "tol": 1},
            {"path": "numbers.bortle", "kind": "num", "tol": 0},
        ],
    },
    {
        "id": "E-02",
        "category": "evaluate",
        "question": "오늘 밤 1100고지 어때? 몇 시간이나 볼 수 있어?",
        "gold_tool": "evaluate_place",
        "gold_args": {"query": "1100고지", "date": TODAY, "scope": "night"},
        "required": ["query", "scope"],
        "facts": [
            {"path": "numbers.tonight.observable_hours", "kind": "num", "tol": 0},
            {"path": "resolved.matched_query", "kind": "text"},
        ],
    },
    {
        "id": "E-03",
        "category": "evaluate",
        "question": "위도 33.46, 경도 126.83 지점에서 오늘 밤 10시에 별이 보일까?",
        "gold_tool": "evaluate_place",
        "gold_args": {"lat": 33.46, "lon": 126.83, "date": TODAY, "time": "22:00"},
        "required": ["lat", "lon"],
        "facts": [
            {"path": "verdict", "kind": "text"},
            {"path": "numbers.cloud_cover", "kind": "num", "tol": 1},
        ],
    },
    {
        "id": "E-04",
        "category": "evaluate",
        "question": "제주공항에서 출발할 건데 용눈이오름 별 보기 어때? 거기까지 얼마나 걸려?",
        "gold_tool": "evaluate_place",
        "gold_args": {"query": "용눈이오름", "origin": "제주공항", "date": TODAY, "time": "23:00"},
        "required": ["query", "origin"],
        "facts": [
            {"path": "verdict", "kind": "text"},
            {"path": "numbers.drive.minutes", "kind": "num", "tol": 1.5},
        ],
    },
    {
        "id": "E-05",
        "category": "evaluate",
        "question": "내일 밤 섭지코지에서 별 볼 수 있을까?",
        "gold_tool": "evaluate_place",
        "gold_args": {"query": "섭지코지", "date": TOMORROW, "time": "23:00"},
        "required": ["query", "date"],
        "facts": [
            {"path": "verdict", "kind": "text"},
            {"path": "numbers.cloud_cover", "kind": "num", "tol": 1},
        ],
    },
    {
        "id": "E-06",
        "category": "evaluate",
        "question": "협재해수욕장에서 오늘 밤 별 보여? 거기 주차랑 야간 출입은 어때?",
        "gold_tool": "evaluate_place",
        "gold_args": {"query": "협재해수욕장", "date": TODAY, "time": "23:00"},
        "required": ["query"],
        "abstain": True,   # 미등록 — 주차·야간 출입은 확인되지 않았음을 밝혀야 한다
        "facts": [
            {"path": "verdict", "kind": "text"},
            {"path": "numbers.cloud_cover", "kind": "num", "tol": 1},
        ],
    },
    {
        "id": "E-07",
        "category": "evaluate",
        "question": "사려니숲길 오늘 밤 별 관측 괜찮아? 밤에 들어가도 되는 곳이야?",
        "gold_tool": "evaluate_place",
        "gold_args": {"query": "사려니숲길", "date": TODAY, "time": "23:00"},
        "required": ["query"],
        "abstain": True,
        "facts": [
            {"path": "verdict", "kind": "text"},
        ],
    },
    {
        "id": "E-08",
        "category": "evaluate",
        "question": "오늘 밤 알뜨르비행장에서 별 볼 수 있는 시간이 총 몇 시간이나 돼?",
        "gold_tool": "evaluate_place",
        "gold_args": {"query": "알뜨르비행장", "date": TODAY, "scope": "night"},
        "required": ["query", "scope"],
        "facts": [
            {"path": "numbers.tonight.observable_hours", "kind": "num", "tol": 0},
        ],
    },

    # ── spot_details (5) ───────────────────────────────────────────────
    {
        "id": "D-01",
        "category": "details",
        "question": "매오름 많이 걸어야 해?",
        "gold_tool": "spot_details",
        "gold_args": {"name": "매오름"},
        "required": ["name"],
        "facts": [
            {"path": "numbers.walk_minutes", "kind": "num", "tol": 1},
            {"path": "spots[0].trail_grade", "kind": "text"},
        ],
    },
    {
        "id": "D-02",
        "category": "details",
        "question": "1100고지 휴게소에 강아지 데려가도 돼?",
        "gold_tool": "spot_details",
        "gold_args": {"name": "1100고지 휴게소"},
        "required": ["name"],
        "facts": [
            {"path": "spots[0].pets", "kind": "text"},
        ],
        "forbid": [r"동반\s*가능", r"데려\s*갈\s*수\s*있"],
    },
    {
        "id": "D-03",
        "category": "details",
        "question": "새별오름 밤에 들어갈 수 있어?",
        "gold_tool": "spot_details",
        "gold_args": {"name": "새별오름"},
        "required": ["name"],
        "facts": [
            {"path": "spots[0].night_access", "kind": "text"},
        ],
    },
    {
        "id": "D-04",
        "category": "details",
        "question": "천아계곡 화장실 있어? 주차는?",
        "gold_tool": "spot_details",
        "gold_args": {"name": "천아계곡"},
        "required": ["name"],
        "facts": [
            {"path": "numbers.toilet_count", "kind": "num", "tol": 0},
            {"path": "numbers.parking_count", "kind": "num", "tol": 0},
        ],
    },
    {
        "id": "D-05",
        "category": "details",
        "question": "제주공항에서 관음사 야영장까지 얼마나 걸려? 거기 야간에 들어갈 수 있어?",
        "gold_tool": "spot_details",
        "gold_args": {"name": "관음사 야영장", "origin": "제주공항"},
        "required": ["name", "origin"],
        "facts": [
            {"path": "numbers.drive.minutes", "kind": "num", "tol": 1.5},
            {"path": "spots[0].night_access", "kind": "text"},
        ],
    },

    # ── 도구를 부르면 안 되는 질문 (4) ─────────────────────────────────
    {
        "id": "N-01",
        "category": "no-tool",
        "question": "서울 남산타워에서 별이 잘 보일까?",
        "gold_tool": None,
        "gold_args": {},
        "required": [],
        "abstain": True,
        "facts": [],
    },
    {
        "id": "N-02",
        "category": "no-tool",
        "question": "제주도 흑돼지 맛집 세 군데만 추천해줘.",
        "gold_tool": None,
        "gold_args": {},
        "required": [],
        "abstain": True,
        "facts": [],
    },
    {
        "id": "N-03",
        "category": "no-tool",
        "question": "MCP 프로토콜이 뭔지 설명해줘.",
        "gold_tool": None,
        "gold_args": {},
        "required": [],
        "abstain": True,
        "facts": [],
    },
    {
        "id": "N-04",
        "category": "no-tool",
        "question": "내일 부산 날씨 어때?",
        "gold_tool": None,
        "gold_args": {},
        "required": [],
        "abstain": True,
        "facts": [],
    },
]

BY_ID = {c["id"]: c for c in CASES}
