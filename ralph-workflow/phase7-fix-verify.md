# Phase 7: 수정 검증

## 지시사항

Phase 6에서 수정한 내용이 spec과 여전히 일치하는지 검증하라.

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

### 1단계: fix-validator 검증

다음 에이전트를 호출한다:

- Task(subagent_type='fix-validator'): {{CHECKLIST_PATH}}와 {{NOTES_PATH}}를 전달. 수정 사항의 정확성, spec 적합성 유지, 회귀 위험 검증

### 2단계: Spec 직접 재대조

에이전트와 별개로, 직접 spec을 재대조한다:
1. {{CHECKLIST_PATH}}의 `[x]` 항목을 **처음부터 끝까지** 순회한다
2. 각 항목의 라인 참조를 따라 원본 spec을 Read(offset, limit)로 읽는다
3. 구현 코드가 spec 원문의 **모든 조건**을 정확히 구현했는지 대조한다
4. 불일치 발견 시 수정한다

수정 사항을 {{NOTES_PATH}}에 기록한다.

### 3단계: 테스트 및 lint/format/type check (변경 파일만)

```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

**수정이 있었으면 promise를 출력하지 않는다.**

## 완료 조건

- fix-validator CRITICAL/HIGH 이슈 0건
- 수정이 spec 적합성을 깨뜨리지 않음
- Spec 직접 재대조 불일치 0건
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

모든 조건 충족 시 <promise>FIXES VERIFIED</promise> 출력.
