# Phase 5: 스펙 검증

## 지시사항

구현 완료된 코드가 spec의 모든 요구사항을 정확히 구현했는지 라인별로 대조하라.

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
5. **검증 이터레이션 필수** — 첫 이터레이션에서는 promise를 출력하지 않는다. 최소 1회 전체 재검증을 통과해야 한다.

## 절차

### 1단계: spec-compliance-verifier 호출

Task(subagent_type='spec-compliance-verifier')를 호출한다:
- **{{CHECKLIST_PATH}}의 `- [x]` 항목을 하나씩 순회**하며, 각 항목의 라인 참조를 따라 원본 spec 해당 줄을 읽고, 구현 코드와 대조한다
- MISS/DIFF를 REQ 번호와 함께 보고

### 2단계: 역방향 spec 검증 (체크리스트 무시, 원문 직접 순회)

**체크리스트에 의존하지 않고** 원본 spec을 처음부터 끝까지 직접 읽으며 누락을 찾는다.
이 단계는 Phase 0의 REQ 추출 누락(5~15%)을 잡는 안전망이다.

**절차:**
1. {{SPEC_PATH}}의 모든 spec 파일을 **처음부터 끝까지** 순차 Read한다 (체크리스트 라인 참조를 사용하지 않는다).
2. spec의 **각 문장/조건/제약**에 대해, 구현 코드에서 해당 동작이 존재하는지 Grep/Read로 확인한다.
3. 구현이 있지만 체크리스트에 REQ가 없는 경우 → 체크리스트에 REQ 추가 (Phase 0 누락 복구).
4. 구현 자체가 없는 경우 → REQ 추가 + 즉시 구현.
5. **암묵적 요구사항**도 탐색한다: spec에서 "~해야 한다", "~를 반환한다", "~인 경우", "~이면 에러" 등의 표현을 모두 검사한다.
6. **부정 요구사항** 검증: "~하지 않는다", "~금지", "~불가" 등의 표현이 구현에서 올바르게 차단/거부되는지 확인한다.
7. **참조 요구사항** 검증: "기존 X와 동일하게", "Y처럼 동작", "Z 방식을 따른다" 등의 표현이 있으면, 참조 대상의 실제 동작을 Read/Grep으로 확인하고 구현이 행동적으로 동등한지 대조한다.
8. **정량적 요구사항** 검증: 체크리스트에서 `(정량)` 태그가 붙은 REQ를 찾고, 구현 코드에서 해당 상수/설정값이 spec의 숫자와 정확히 일치하는지 확인한다. (예: spec "페이지당 20건" → 코드에서 `PAGE_SIZE=20` 또는 `paginate_by=20` 확인). spec에 없는 정량적 값이 코드에 하드코딩되어 있으면 근거를 확인한다.

### 3단계: 체크리스트 완전성 검증

2단계와 별도로, 체크리스트의 구조적 완전성도 검증한다:
1. {{CHECKLIST_PATH}}의 "섹션 처리 현황"에서 모든 섹션의 라인 범위를 파악한다
2. 각 섹션을 Read(offset, limit)로 읽고, 해당 라인 범위를 참조하는 REQ 항목이 체크리스트에 있는지 대조한다
3. **체크리스트에 없는 요구사항**을 발견하면 REQ 항목을 추가하고 즉시 구현한다

### 4단계: Spec Digest 보강

2~3단계에서 **새 REQ가 추가되었거나 교차 참조가 발견된 경우**, {{DIGEST_PATH}}를 업데이트한다.

1. {{DIGEST_PATH}}를 읽는다.
2. 새로 추가된 REQ가 기존 도메인 개념과 관련되면 → **교차 참조 맵**에 추가한다.
3. 새로 추가된 `(정량)`, `(부정)`, `(참조)` REQ가 있으면 → **전역 제약사항**에 추가한다.
4. 역방향 검증에서 발견된 **섹션 간 암묵적 의존성** → **교차 참조 맵**에 추가한다.
5. 200줄 제한을 유지한다.

**새 REQ 추가가 없었으면 이 단계를 건너뛴다.**

### 5단계: 이슈 수정

spec-compliance-verifier가 보고한 MISS/DIFF 항목을 수정한다:
- MISS: 누락된 구현을 추가한다
- DIFF: spec과 불일치하는 구현을 수정한다

### 6단계: 테스트 및 lint/format/type check

수정 후 테스트를 실행한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

**수정이 있었으면 promise를 출력하지 않는다.** 다음 이터레이션에서 spec-compliance-verifier를 재호출하여 수정 결과를 검증한다.

수정 사항을 {{NOTES_PATH}}에 기록한다.

## 완료 조건

- spec-compliance-verifier MISS/DIFF 0건 (체크리스트 기반 전수 검증)
- 역방향 spec 검증 누락 0건 (원본 spec 전문 직접 순회)
- 체크리스트 완전성 재검증 누락 0건
- Spec Digest 보강 완료 (새 REQ/교차 참조 반영)
- 모든 테스트 통과
- 변경 파일 ruff check/format/mypy 통과

- **검증 이터레이션 ≥ 1** (첫 이터레이션 이후 최소 1회 전체 재검증 통과)

모든 조건 충족 시 <promise>SPEC VERIFIED</promise> 출력.
