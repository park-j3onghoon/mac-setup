# Phase 17: 심층 검토

## 지시사항

이 코드를 reject하려는 시니어 리뷰어 관점에서 결함을 찾고, 엣지케이스를 사냥하고, 테스트 품질을 검증하여 수정하라.
**매 이터레이션마다 전체 spec을 재대조한다.**

**Spec**:
{{SPEC_PATH}}
**스펙 요약**: {{DIGEST_PATH}} (핵심 개념, 교차 참조, 전역 제약. 먼저 읽고 큰 그림을 파악하라.)
**구현 디렉토리**: {{MODULE_PATH}}
**테스트 디렉토리**: {{TEST_PATH}}
**체크리스트**: {{CHECKLIST_PATH}}
**메모**: {{NOTES_PATH}} (이전 Phase의 발견/수정 사항. 읽고 참조하라. 수정 시 기록하라.)

## 공통 원칙

1. **발견된 문제의 관련 영역도 재검토** — 문제 수정 후 영향받을 수 있는 코드를 추적하여 추가 검토
2. **모든 spec 파일을 매 이터레이션마다 함께 처리** — 체크리스트 라인 참조로 해당 줄만 Read
3. **이전 이터레이션 이어받기** — 체크리스트/결과 파일로 진행 상황 추적
4. **수정 발생 시 promise 출력 금지** — 수정 없는 클린 이터레이션에서만 promise 출력

## 절차

### 1단계: 병렬 심층 검토 (3개 에이전트를 동시에 호출한다)

다음 3개 에이전트를 **병렬로** 호출한다:

- Task(subagent_type='adversarial-reviewer'): **{{CHECKLIST_PATH}}를 전달**하여:
  - 체크리스트의 모든 REQ 항목을 하나씩 순회하며, 라인 참조를 따라 원본 spec을 읽고 코드와 대조
  - 비즈니스 규칙 전수 검사 (모든 상태/조건 조합 매트릭스)
  - 테스트 assert 유효성 검증
  - 에러 핸들링 완전성

- Task(subagent_type='edge-case-hunter'): **{{CHECKLIST_PATH}}를 전달**하여:
  - 각 REQ별 엣지케이스 탐색
  - None/빈값/경계값 시나리오
  - 비즈니스 규칙 경계 조건
  - 동시성/Race condition
  - 외부 의존성 실패 시나리오

- Task(subagent_type='test-quality-reviewer'): 테스트 품질 전문 검증:
  - Mock 정확성 (mock이 실제 동작을 반영하는지)
  - 테스트 격리 (테스트 간 상태 공유 없는지)
  - Assert 완전성 (핵심 필드 검증 누락, 무의미한 assert)
  - 네거티브 테스트 커버리지 (실패 케이스 테스트)
  - 테스트 데이터 현실성

### 2단계: Spec 직접 재대조

에이전트와 별개로, 직접 spec을 재대조한다:
1. {{CHECKLIST_PATH}}의 `[x]` 항목을 **처음부터 끝까지** 순회한다
2. 각 항목의 라인 참조를 따라 원본 spec을 Read(offset, limit)로 읽는다
3. 구현 코드가 spec 원문의 **모든 조건**을 정확히 구현했는지 대조한다
4. 불일치 발견 시 기록한다

### 3단계: 체크리스트 완전성 재검증

체크리스트 자체가 spec을 빠뜨렸을 수 있다:
1. {{CHECKLIST_PATH}}의 "섹션 처리 현황"에서 모든 섹션의 라인 범위를 파악한다
2. 각 섹션을 Read(offset, limit)로 읽고, 해당 라인 범위를 참조하는 REQ 항목이 체크리스트에 있는지 대조한다
3. **체크리스트에 없는 요구사항**을 발견하면 REQ 항목을 추가하고 즉시 구현한다

### 4단계: 결함/엣지케이스/테스트 품질 수정

- adversarial-reviewer REJECT 사유 수정
- edge-case-hunter가 발견한 커버되지 않은 엣지케이스에 대해 테스트 추가 및 코드 수정
- test-quality-reviewer가 발견한 CRITICAL/HIGH 이슈 수정 (mock 부정확, 무의미한 assert, 격리 오류)
- 2단계에서 발견한 불일치 수정

### 5단계: 테스트 및 lint/format/type check (변경 파일만)
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v --cov={{MODULE_PATH}} --cov-fail-under=80
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

### 6단계: 메모 기록 + 재리뷰

수정 사항을 {{NOTES_PATH}}에 기록한다.
수정 후 adversarial-reviewer를 다시 호출하여 APPROVE 판정을 받는다.
**수정이 있었으면 promise를 출력하지 않는다.** 다음 이터레이션에서 1단계부터 재검증한다.

## 완료 조건

- adversarial-reviewer 판정: APPROVE 또는 APPROVE WITH COMMENTS
- REJECT 사유 0건
- **Spec 직접 재대조 불일치 0건**
- 체크리스트 완전성 재검증 누락 0건
- 엣지케이스 테스트 추가됨
- test-quality-reviewer CRITICAL/HIGH 이슈 0건
- 커버리지 80% 이상
- 모든 테스트 통과
- ruff check/format/mypy 통과

- **클린 이터레이션 ≥ 1** (수정 없는 이터레이션이 최소 1회 있어야 함)

모든 조건 충족 시 <promise>DEEP REVIEW DONE</promise> 출력.
