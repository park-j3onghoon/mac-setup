# Phase 6: 버그/보안 검토

## 지시사항

구현된 코드의 보안 취약점, 논리 오류, 런타임 안전성을 검토하고 수정하라.

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

### 1단계: 병렬 리뷰 (3개 에이전트를 동시에 호출한다)

다음 3개 에이전트를 **병렬로** 호출한다 (Task tool을 한 번에 3개 호출):

- Task(subagent_type='security-reviewer'): 인젝션 방지, 입력 검증, 시크릿 노출, 인증/인가, CSRF/XSS 검토
- Task(subagent_type='logic-error-detector'): 조건문 로직 오류, 비즈니스 분기 누락, off-by-one, 상태 전이 오류, 계산/변환 오류
- Task(subagent_type='runtime-safety-checker'): None 안전성, 타입 불일치, 에러 핸들링 갭, 데이터 무결성, 입력 경계 안전성

### 2단계: 이슈 수정

에이전트 결과를 집계하고 수정한다:

**우선순위**: CRITICAL → HIGH → MEDIUM (MEDIUM은 2개 이상 에이전트가 동시 지적한 것만)
**충돌 해결**: 에이전트 간 상충하는 지적이 있으면 심각도가 높은 쪽 우선. 동일 심각도면 security-reviewer > logic-error-detector > runtime-safety-checker 순.

CRITICAL/HIGH 이슈를 모두 수정한다.

### 3단계: 테스트 및 lint/format/type check (변경 파일만)

수정 후 regression이 없는지 확인한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

**수정이 있었으면 promise를 출력하지 않는다.** 다음 이터레이션에서 에이전트를 재호출하여 수정 결과를 검증한다.

수정 사항을 {{NOTES_PATH}}에 기록한다.

## 완료 조건

- security-reviewer CRITICAL/HIGH 이슈 0건
- logic-error-detector CRITICAL/HIGH 이슈 0건
- runtime-safety-checker CRITICAL/HIGH 이슈 0건
- 수정 후 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

모든 조건 충족 시 <promise>SECURITY DONE</promise> 출력.
