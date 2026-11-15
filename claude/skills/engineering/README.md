# Engineering

- [ai-review](./ai-review/SKILL.md): PR을 위험도에 맞춘 리뷰어로 리뷰하고, 코드는 고치지 않은 채 결과를 GitHub 리뷰 한 건으로 단다. CRITICAL이 없으면 승인하며 나머지 코멘트를 달고, 있으면 CRITICAL 코멘트만 달아 수정을 요청한다. 올리기 전에 초안을 승인받는다.
- [cso](./cso/SKILL.md): Read-only 보안 감사. 시크릿·공급망·CI/CD·OWASP·STRIDE를 훑어 exploitable한 발견만 보고서로 낸다.
- [grill](./grill/SKILL.md): 결정을 끝까지 캐묻는다. 사실은 내가 찾고, 갈림길은 한 턴에 하나씩 묻고, 합의된 결정을 decisions.md로 남긴다.
- [guard](./guard/SKILL.md): 이번 세션에 안전 모드를 건다. 위험 명령 경고 + 지정 디렉토리 밖 편집 확인. `off` 로 편집 제한을 푼다.
- [implement](./implement/SKILL.md): 확정된 계획을 vertical slice 단위로 구현한다. 안전 모드와 코드 규칙을 적용하고, 슬라이스마다 테스트 통과 후 커밋하며, 끝에 simplify로 정리한 변경도 검증 후 별도 커밋한다.
- [implement-review](./implement-review/SKILL.md): 내 PR이나 구현 커밋을 위험도에 맞춘 리뷰어로 리뷰하고, 다시 리뷰할 때는 직전 리뷰 뒤 커밋만 본다. 발견마다 고치거나 하나씩 물어 반영하고, 테스트 통과 후 수정분을 별도 커밋한다.
- [investigate](./investigate/SKILL.md): 버그를 근본 원인까지 추적해 고치고 DEBUG REPORT로 마감한다.
- [plan-review](./plan-review/SKILL.md): 구현 계획을 코드 작성 전에 스코프 챌린지·6차원 리뷰·다른 AI 교차 검증으로 통과시킨다.
- [pr-create](./pr-create/SKILL.md): push된 브랜치로 Draft PR을 만든다. 크기를 검사하고, 받을 리뷰(CodeRabbit·사내 AI 리뷰 봇)를 추천과 함께 고르게 한 뒤, 제목·본문 초안을 승인받아 만들고 고른 리뷰를 CodeRabbit → 사내 AI 리뷰 봇 순서로 요청해 끝날 때까지 기다린 뒤 지적에 모두 대응한다.
- [push-commit](./push-commit/SKILL.md): 변경을 커밋하고 브랜치를 push한 뒤, PR이 있으면 제목·본문을 코드에 맞춘다. 사람 리뷰를 받기 전이면 Claude가 push하고, 받은 뒤면 사용자가 push한다.
