# Phase 9: 통합/재사용 검증

## 지시사항

새 코드가 기존 코드베이스와 충돌 없이 통합되는지 검증하라.

**Spec**:
{{SPEC_PATH}}
**스펙 요약**: {{DIGEST_PATH}} (핵심 개념, 교차 참조, 전역 제약. 먼저 읽고 큰 그림을 파악하라.)
**구현 디렉토리**: {{MODULE_PATH}}
**테스트 디렉토리**: {{TEST_PATH}}
**메모**: {{NOTES_PATH}} (이전 Phase의 발견/수정 사항. 읽고 참조하라. 수정 시 기록하라.)

## 공통 원칙

1. **발견된 문제의 관련 영역도 재검토** — 문제 수정 후 영향받을 수 있는 코드를 추적하여 추가 검토
2. **모든 spec 파일을 매 이터레이션마다 함께 처리** — 체크리스트 라인 참조로 해당 줄만 Read
3. **이전 이터레이션 이어받기** — 체크리스트/결과 파일로 진행 상황 추적
4. **수정 발생 시 promise 출력 금지** — 수정 없는 클린 이터레이션에서만 promise 출력
5. **검증 이터레이션 필수** — 첫 이터레이션에서는 promise를 출력하지 않는다. 최소 1회 전체 재검증을 통과해야 한다.

## 절차

### 1단계: 통합 검증
Task(subagent_type='integration-verifier')를 호출한다:
- Import 충돌
- Model/Schema 충돌
- 라우팅 충돌
- Hook/Signal 간섭
- 기존 코드 영향
- 설정/환경 충돌

### 2단계: 전체 테스트 스위트
```bash
# 새 코드 테스트
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v

# MODULE_PATH 전체 테스트
docker exec "$DEV_CONTAINER" pytest {{MODULE_PATH}} --reuse-db -x -q
```

### 3단계: 충돌 해결
발견된 충돌을 수정한다.

### 4단계: 메모 기록

수정 사항을 {{NOTES_PATH}}에 기록한다.

### 5단계: 재검증
수정 후 모든 테스트와 lint/format/type check를 다시 실행한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
docker exec "$DEV_CONTAINER" pytest {{MODULE_PATH}} --reuse-db -x -q
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 통합 검증 CRITICAL/HIGH 이슈 0건
- 새 코드 테스트 전체 통과
- 기존 테스트 영향 없음
- MODULE_PATH 전체 테스트 통과
- 변경 파일 ruff check/format/mypy 통과

**수정이 있었으면 promise를 출력하지 않는다.**

- **검증 이터레이션 ≥ 1** (첫 이터레이션 이후 최소 1회 전체 재검증 통과)

모든 조건 충족 시 <promise>INTEGRATION DONE</promise> 출력.
