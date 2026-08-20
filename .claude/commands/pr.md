---
description: 검증을 돌리고 PR 본문을 채워 올린다
argument-hint: [PR 제목]
allowed-tools: Bash(git *), Bash(gh pr *), Bash(uv run *), Read, Write
disable-model-invocation: true
---

# 현재 상태
- 브랜치: !`git branch --show-current`
- 커밋: !`git log --oneline -10`

# 절차

## 1. base 브랜치 결정
`git merge-base`로 분기 지점을 찾아 실제 부모 브랜치를 base로 쓴다.
**`main`이 기본값이 아니다.** 애매하면 만들지 말고 사용자에게 묻는다.

## 2. 검증 실행 — 결과를 그대로 기록한다
```
uv run ruff check .
uv run pytest
git diff --stat <base>..HEAD
```

경로·import를 바꿨으면 파이프라인도 실제로 돌린다 (import 통과 ≠ 동작).
```
uv run python -m server.app
```

**중단 조건** (PR을 만들지 말고 보고만 한다)
- ruff에 `F821`이 있다
- pytest가 실패한다
- diff에 `.tif` `.bsp` `.npz`가 있다

## 2.5. 관련 이슈 (선택)

`$ARGUMENTS`에 `#숫자`가 있을 때만 본문 맨 아래에 추가한다.
```
Closes #12
```
여러 개면 **줄마다 키워드를 반복한다** — `Closes #1, #2`는 #1만 닫힌다.
없으면 항목 자체를 넣지 않는다. 지어내지 않는다.

## 3. diff를 읽고 "리뷰 요약"을 쓴다
파일 나열이 아니라 **동작이 어떻게 달라지는지**. 판단이 갈렸거나
근거가 약한 부분이 있으면 반드시 적는다.

## 4. 본문 작성
`.github/pull_request_template.md` 구조를 그대로 쓴다.

**체크 규칙 — 어기지 말 것**
| 항목 | 체크 조건 |
|---|---|
| 코딩 스타일 | ruff 통과 |
| 스스로 리뷰 | "리뷰 요약"을 실제로 채웠을 때 |
| 상수·임계값 | diff에 임계값 변경이 없거나, 있으면 근거를 "설명"에 적었을 때 |
| 문서 반영 | 임계값·데이터 변경이 있으면 해당 docs 파일이 diff에 있을 때 |
| 새 경고 | base 대비 ruff 경고 수가 늘지 않았을 때 |
| 테스트 추가 | diff에 `tests/` 파일이 있을 때 |
| 기존 테스트 | pytest 통과 |
| 응답 계약 | `server/schema.py`와 도구 시그니처에 변경이 없을 때 |
| 바이너리 | diff에 해당 확장자가 없을 때 |

조건을 못 채운 항목은 **비워두고**, "추가 설명"에 왜 못 채웠는지 한 줄 적는다.

"실행 결과" 블록에는 명령의 실제 출력 요약을 넣는다. 지어내지 않는다.

## 5. 제목
`<type>(<scope>): <요약>` 형식. $ARGUMENTS가 있으면 그것을 쓰고,
없으면 커밋 로그에서 대표 하나를 요약한다.

## 6. 생성
본문을 `.pr-body.md`에 쓰고:
```
gh pr create --base <base> --title "<제목>" --body-file .pr-body.md
```
끝나면 `.pr-body.md`를 지운다.

# 금지
- `--admin` `--auto` 등 리뷰 우회
- force push
- 확인 없이 base를 main으로 두기
- 돌리지 않은 명령의 결과를 체크하거나 지어내기