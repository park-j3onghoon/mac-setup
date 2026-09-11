---
name: answer-style
description: 답변 스타일 규칙을 다시 적재한다 — 약어 풀이·구체 예시·3관점·one-pass briefing·근거 검증·self-review.
disable-model-invocation: true
argument-hint: "[이 세션에서 특히 지킬 항목]"
---

# /answer-style — 답변 규칙 재적재

`~/.claude/lib/answer-style.md`를 Read하고, 이 세션의 남은 답변·문서·카드·리포트에 그대로 적용한다.

인자가 있으면 그 항목을 이번 세션의 중점으로 삼는다(예: `근거` → 모든 주장에 `파일:라인` 또는 수치+출처를 붙인다).

적용 직후, 직전 답변이 그 규칙을 어겼다면 어긴 항목을 한 줄로 밝히고 고쳐 쓴다.

→ 완료: 규칙을 읽었고, 어긴 항목이 있었다면 정정본을 냈다.
