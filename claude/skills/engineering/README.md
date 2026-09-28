# Engineering

일상적인 코드 작업.

전부 **User-invoked** 다. 사람이 `/이름` 을 칠 때만 실행되고(`disable-model-invocation: true`), 모델이나 다른 스킬은 부를 수 없다.

- **[cso](./cso/SKILL.md)**: Read-only 보안 감사. 시크릿·공급망·CI/CD·OWASP·STRIDE를 훑어 exploitable한 발견만 보고서로 낸다.
- **[grill](./grill/SKILL.md)**: 결정을 끝까지 캐묻는다. 사실은 내가 찾고, 갈림길만 라운드로 묶어 묻고, 합의된 결정을 decisions.md로 남긴다.
- **[guard](./guard/SKILL.md)**: 이번 세션에 안전 모드를 건다. 위험 명령 경고 + 지정 디렉토리 밖 편집 확인. `off` 로 편집 제한을 푼다.
- **[implement](./implement/SKILL.md)**: 확정된 계획을 vertical slice 단위로 구현한다. 안전 모드를 걸고, 코드 규칙을 적재하고, 슬라이스마다 테스트를 green으로 만든다.
- **[implement-review](./implement-review/SKILL.md)**: 내 PR을 서브에이전트 3개(보안 트리거가 있으면 4개)로 병렬 리뷰하고, 발견마다 고치거나 하나씩 물어 반영한 뒤 커밋까지 끝낸다.
- **[investigate](./investigate/SKILL.md)**: 버그를 근본 원인까지 추적해 고치고 DEBUG REPORT로 마감한다.
- **[plan-review](./plan-review/SKILL.md)**: 구현 계획을 코드 작성 전에 스코프 챌린지·6차원 리뷰·Codex 적대 검증으로 통과시킨다.
- **[pr-create](./pr-create/SKILL.md)**: 브랜치를 PR로 올린다. 크기를 검사하고 push 명령을 낸 뒤, PR이 없으면 Draft로 만들고 있으면 제목·본문을 코드에 맞게 고친다.
