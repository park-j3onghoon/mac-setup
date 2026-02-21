# Phase 12: 코드 정리

## 지시사항

불필요한 코드, 미사용 import, dead code를 정리하라.

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

## 절차

### 1단계: Dead Code 분석

Task(subagent_type='dead-code-analyzer')를 호출한다:
- 사용되지 않는 import 식별
- 호출되지 않는 private 메서드 식별
- 도달 불가능한 분기 식별
- 구현 과정에서 생긴 임시/디버깅 코드 식별
- 사용되지 않는 변수/상수 식별

### 2단계: 코드 정리

dead-code-analyzer가 보고한 항목을 정리한다:
- 미사용 import 제거
- Dead code 제거
- 임시 코드/주석 정리
- 불필요한 빈 파일 제거

**주의**: 기능을 변경하지 않는다. 정리만 수행한다.

정리 내역을 {{NOTES_PATH}}에 기록한다.

### 3단계: 테스트 및 lint/format/type check

정리 후 아무것도 깨지지 않았는지 확인한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 미사용 import 0건
- Dead code 0건
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

**수정이 있었으면 promise를 출력하지 않는다.**

- **클린 이터레이션 ≥ 1** (수정 없는 이터레이션이 최소 1회 있어야 함)

모든 조건 충족 시 <promise>CLEANUP DONE</promise> 출력.
