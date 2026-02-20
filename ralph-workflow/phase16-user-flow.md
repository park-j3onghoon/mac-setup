# Phase 16: 사용자 흐름 검증

## 지시사항

사용자 관점에서 코드의 흐름을 검증하라. API 호출 순서, 에러 메시지, 상태 전이 등을 검토한다.

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

### 1단계: 사용자 흐름 검토

Task(subagent_type='ux-reviewer')를 호출한다:
- API 호출 순서가 자연스러운지
- 에러 메시지가 사용자에게 명확한지
- 상태 전이가 자연스럽고 예측 가능한지
- 엣지케이스에서의 사용자 경험
- 입력 검증 메시지의 명확성
- 비동기 작업의 피드백 적절성

### 2단계: 이슈 수정

ux-reviewer가 보고한 CRITICAL/HIGH 이슈를 수정한다:
- 에러 메시지 개선
- API 응답 형식 일관성 확보
- 상태 전이 로직 수정

### 3단계: 테스트 및 lint/format/type check

```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

### 4단계: 메모 기록

수정 사항을 {{NOTES_PATH}}에 기록한다.

**수정이 있었으면 promise를 출력하지 않는다.**

## 완료 조건

- ux-reviewer CRITICAL/HIGH 이슈 0건
- 에러 메시지가 명확하고 일관됨
- 상태 전이가 자연스러움
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

- **검증 이터레이션 ≥ 1** (첫 이터레이션 이후 최소 1회 전체 재검증 통과)

모든 조건 충족 시 <promise>UX DONE</promise> 출력.
