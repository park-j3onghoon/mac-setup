# Phase 11: 전체 재검토

## 지시사항

구조 개선, 통합, 사이드이펙트 분석 후 전체 변경 사항을 재검증하라.
**체크리스트 항목 검증 + 체크리스트 자체의 완전성 검증** 모두 수행한다.

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

### 1단계: 체크리스트 기반 전수 검증

{{CHECKLIST_PATH}}의 **모든 `- [x]` 항목**을 처음부터 끝까지 순회하며:
1. 라인 참조(예: `[spec.md:45-52]`)를 따라 원본 spec 해당 줄을 Read(offset, limit)로 읽는다
2. 구현 코드가 해당 spec 원문의 모든 조건을 정확히 구현했는지 대조한다
3. 불일치가 있으면 수정한다

### 2단계: 체크리스트 완전성 재검증

체크리스트 자체가 spec을 빠뜨렸을 수 있다. 원본 spec의 **모든 섹션**을 다시 읽어 확인한다:
1. {{CHECKLIST_PATH}}의 "섹션 처리 현황"에서 모든 섹션의 라인 범위를 파악한다.
2. 각 섹션을 Read(offset, limit)로 읽고, 해당 라인 범위를 참조하는 REQ 항목이 체크리스트에 있는지 대조한다.
3. **체크리스트에 없는 요구사항**을 발견하면 REQ 항목을 추가하고 즉시 구현한다.

### 3단계: Spec Digest 완전성 검증

Phase 4~10에서 코드가 변경되었으므로, {{DIGEST_PATH}}가 현재 상태를 정확히 반영하는지 검증한다.

1. {{DIGEST_PATH}}를 읽는다.
2. **교차 참조 맵**: 체크리스트의 모든 REQ를 순회하며, 여러 섹션에 걸친 REQ가 맵에 반영되어 있는지 확인한다. 누락된 교차 참조가 있으면 추가한다.
3. **전역 제약사항**: 체크리스트의 `(정량)`, `(부정)`, `(참조)` REQ가 모두 전역 제약사항에 포함되어 있는지 확인한다. 누락 시 추가한다.
4. **엔티티 관계**: 구현된 코드의 실제 엔티티 관계가 Digest와 일치하는지 확인한다. 불일치 시 수정한다.
5. 200줄 제한을 유지한다.

### 4단계: 병렬 재검증 (2개 에이전트를 동시에 호출한다)

다음 2개 에이전트를 **병렬로** 호출한다:

- Task(subagent_type='full-spec-auditor'): {{CHECKLIST_PATH}}와 {{NOTES_PATH}}를 전달. 구조 변경 후 전체 spec 커버리지 감사 + 체크리스트 완전성 검증
- Task(subagent_type='architecture-reviewer'): {{NOTES_PATH}}를 전달. DDD 레이어 의존성, SOLID 원칙, 설계 패턴 준수 검증

### 5단계: DDD 레이어 의존성 확인
변경된 파일들의 import를 직접 검사하여 레이어 규칙 위반이 없는지 확인한다:
- `domain/` 파일이 Django/adapter/infra를 import하지 않는지
- `application/` 파일이 adapter/infra를 import하지 않는지
- 의존성 방향: domain ← application ← adapter

### 6단계: 이슈 수정
발견된 CRITICAL/HIGH 이슈를 수정한다.
수정 사항을 {{NOTES_PATH}}에 기록한다.
**이슈를 수정한 경우 promise를 출력하지 않는다.** 다음 이터레이션에서 1단계부터 재검증한다.

### 7단계: 테스트 및 lint/format/type check (변경 파일만)
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 체크리스트 전수 검증 불일치 0건
- 체크리스트 완전성 재검증 누락 0건
- Spec Digest 완전성 검증 완료 (교차 참조/전역 제약/엔티티 관계 최신화)
- full-spec-auditor MISS/DIFF 0건
- architecture-reviewer CRITICAL/HIGH 이슈 0건
- SOLID 원칙 위반 0건
- DDD 레이어 의존성 위반 0건
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

- **클린 이터레이션 ≥ 1** (수정 없는 이터레이션이 최소 1회 있어야 함)

모든 조건 충족 시 <promise>FULL REVIEW DONE</promise> 출력.
