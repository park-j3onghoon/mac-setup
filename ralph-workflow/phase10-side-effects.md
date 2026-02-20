# Phase 10: 사이드이펙트 분석

## 지시사항

구현 코드의 암묵적 의존성과 사이드 이펙트를 분석하고 수정하라.

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

### 1단계: 사이드이펙트 분석

Task(subagent_type='side-effect-analyzer')를 호출한다:
- Hook/Signal 체인 추적
- 외부 시스템 동기화 누락 확인
- 공유 상태 변경 영향 분석
- Import 체인/레이어 의존성 검증
- 트랜잭션 경계 적절성 확인

### 2단계: 이슈 수정

side-effect-analyzer가 보고한 CRITICAL/HIGH 이슈를 수정한다:
- 동기화 누락 → 동기화 호출 추가
- 레이어 의존성 위반 → import 경로 수정
- 트랜잭션 경계 이슈 → 트랜잭션 범위 조정

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

- side-effect-analyzer CRITICAL/HIGH 이슈 0건
- 레이어 의존성 위반 없음
- 동기화 누락 없음
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

- **검증 이터레이션 ≥ 1** (첫 이터레이션 이후 최소 1회 전체 재검증 통과)

모든 조건 충족 시 <promise>SIDEEFFECT DONE</promise> 출력.
