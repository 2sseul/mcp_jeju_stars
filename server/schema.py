"""응답 스키마 — verdict/reasons/numbers/attribution/as_of (최종형).

값이 아직 부분/하드코딩이라도 응답 '모양'은 첫 단계부터 최종형으로 고정한다.
필드 추가는 쉬워도 구조 변경은 어렵기 때문.

- verdict:      한 줄 결론(사람이 먼저 읽는 것)
- reasons:      판정 근거 문자열 목록
- numbers:      구조화 수치 — LLM 이 지어내지 못하게 문장과 분리해 노출
- attribution:  데이터 출처. 최상위에 두고 축약·생략하지 않는다
- as_of:        평가 기준 시각(ISO8601, +09:00)
- resolved:     지오코딩으로 해석된 위치(질의·좌표 등). 좌표를 직접 받은 경우나
                해석 실패 시에는 None. 필드 자체는 모든 응답에 항상 존재한다.
- spots:        이 응답이 말하는 **검증된 관측지들**. 추천은 여러 곳, 상세조회·등록된
                장소 평가는 한 곳, 미등록 장소 평가는 None 이다. 최상위 필드는 그대로
                두고 목록만 얹는 형태다(`plan.md` §72).

resolved·spots 는 일부 경로에서만 값이 차지만, 성공/실패에 따라 응답의 필드 집합이
달라지지 않도록 **모든 경로에서 키를 항상 내보낸다**(없으면 None). 응답 '모양'을
고정한다는 원칙을 도구·경로에 걸쳐 지키기 위함이다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Response:
    verdict: str
    reasons: list[str]
    numbers: dict
    attribution: list[str]
    as_of: str
    resolved: dict | None = None
    spots: list[dict] | None = None

    def to_dict(self) -> dict:
        """MCP 도구 반환용 순수 dict. 복사본을 만들어 내부 상태 유출을 막는다."""
        return {
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "numbers": dict(self.numbers),
            "attribution": list(self.attribution),
            "as_of": self.as_of,
            "resolved": dict(self.resolved) if self.resolved is not None else None,
            "spots": [dict(s) for s in self.spots] if self.spots is not None else None,
        }
