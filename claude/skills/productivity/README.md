# Productivity

일상적인 비코드 업무 도구.

mastery-tutor 밖의 스킬은 **User-invoked** 다. 사람이 `/이름` 을 칠 때만 실행되고(`disable-model-invocation: true`), 모델이나 다른 스킬은 부를 수 없다. mastery-tutor는 모델이 고를 수 있다.

- **[explain-html](./explain-html/SKILL.md)**: 주제를 조사해 인라인 SVG 도식이 들어간 단일 파일 HTML 해설서를 만들고, ~/plans에 저장한 뒤 브라우저로 연다.
- **[mastery-tutor](./mastery-tutor/SKILL.md)**: 슬랙 스레드나 개념을 사전지식부터 블록별로 정복하고 진척 퍼센트를 표시한다. 학습 정리·오답·진행 상황을 Codex와 Claude 공용 로컬 기록에 저장해 중복 지식은 재사용하고 약점을 우선 재검증하며, 중단 뒤 이어서 할 수 있다. 질문별로 답을 받고 남은 질문을 즉시 수정·제거하며, 자세한 채점·해설은 나중에 공개한다. "완전히 이해할 때까지 질문해", "퀴즈로 공부하자", "사전지식부터 정복하자", "전에 하던 학습 이어서"에 쓴다. 단순 요약이나 일회성 개념 설명에는 적용하지 않는다.
- **[refresh-session](./refresh-session/SKILL.md)**: 다음 작업을 빈 컨텍스트에서 잇는다. Claude Code는 같은 탭의 대화를 비우거나 새 탭 명령을 만들고, Codex는 새 세션 명령과 이어갈 프롬프트를 만든다.
- **[rules-refresh](./rules-refresh/SKILL.md)**: AI 규칙(진입 파일·lib·instructions·스킬·검사 스크립트)을 개발 방법론과 Simple Design 기준에 맞춰 다시 짜고, 매주 바뀐 것만 갱신하며, 매달 지난달 머지 PR로 리뷰 규칙을 리뷰봇·사람 리뷰와 대조한다.
