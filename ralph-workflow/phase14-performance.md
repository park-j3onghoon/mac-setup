# Phase 14: 성능 검토

## 지시사항

구현 코드의 성능 문제를 검토하라. N+1 쿼리, DB 라운드트립, 알고리즘 복잡도, 캐싱 기회를 중점적으로 본다.

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

### 1단계: 성능 검토

Task(subagent_type='performance-reviewer')를 호출한다:
- N+1 쿼리 탐지 (루프 내 ORM 쿼리, select_related 미사용)
- 불필요한 DB 라운드트립 (한 번에 가져올 수 있는 데이터의 분리 조회)
- 알고리즘 복잡도 (O(n²) 중첩 루프, 리스트 탐색 대신 딕셔너리 미사용)
- 인덱스 필요성 (filter/order_by 필드의 인덱스 여부)
- 캐싱 기회 (자주 조회되지만 변경이 적은 데이터)
- 메모리 효율성 (대량 데이터 일괄 로드, iterator 미사용)
- 배치 처리 기회 (bulk_create/bulk_update 미사용)

### 2단계: 이슈 수정

performance-reviewer가 보고한 CRITICAL/HIGH 이슈를 수정한다:
- N+1 → select_related()/prefetch_related() 추가
- 중복 쿼리 → 쿼리 통합 또는 캐싱
- O(n²) → 적절한 자료구조/알고리즘으로 교체
- 배치 미사용 → bulk 연산으로 교체

### 3단계: 테스트 및 lint/format/type check (변경 파일만)

```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

### 4단계: 메모 기록

수정 사항을 {{NOTES_PATH}}에 기록한다:
- 어떤 성능 이슈를 발견했는지
- 어떻게 수정했는지

**수정이 있었으면 promise를 출력하지 않는다.**

## 완료 조건

- performance-reviewer CRITICAL/HIGH 이슈 0건
- N+1 쿼리 0건
- O(n²) 알고리즘 0건 (대량 데이터 처리 경로)
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

모든 조건 충족 시 <promise>PERF DONE</promise> 출력.
