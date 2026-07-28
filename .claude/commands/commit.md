---
description: 변경 사항을 컨벤션에 맞춰 커밋한다
allowed-tools: Bash(git add:*), Bash(git status:*), Bash(git diff:*), Bash(git commit:*)
disable-model-invocation: true
---

# 변경 사항
- !`git status --short`
- !`git diff HEAD`

# 규칙
`docs/conventions.md`의 커밋 형식을 따른다.
- 무관한 변경이 섞여 있으면 **커밋을 나눈다**
- 임계값·상수를 바꿨으면 본문에 근거를 적는다. 근거가 없으면 커밋하지 말고 보고한다
- 마일스톤(P0 등)은 type 자리가 아니라 본문에 쓴다