"""P0 응답 스키마 — verdict/reasons/numbers/attribution/as_of (최종형).

값이 아직 부분/하드코딩이라도 응답 '모양'은 1단계부터 최종형으로 고정한다.
필드 추가는 쉬워도 구조 변경은 어렵기 때문(계획서 고정2).

- verdict:      한 줄 결론(사람이 먼저 읽는 것)
- reasons:      판정 근거 문자열 목록
- numbers:      구조화 수치 — LLM 이 지어내지 못하게 문장과 분리해 노출
- attribution:  데이터 출처. 최상위에 두고 축약·생략하지 않는다
- as_of:        평가 기준 시각(ISO8601, +09:00)
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

    def to_dict(self) -> dict:
        """MCP 도구 반환용 순수 dict. 복사본을 만들어 내부 상태 유출을 막는다."""
        return {
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "numbers": dict(self.numbers),
            "attribution": list(self.attribution),
            "as_of": self.as_of,
        }
