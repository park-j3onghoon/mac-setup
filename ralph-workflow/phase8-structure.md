# Phase 8: 구조 개선

## 지시사항

코드 구조를 최적화하라. 파일/함수 분리, 재사용 탐색, 확장성 검증에 집중한다.
데드코드 정리는 Phase 12에서, 아키텍처 정합성은 Phase 11에서 별도 수행한다.

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

### 1단계: 구조 최적화
Task(subagent_type='structure-optimizer')를 호출한다:
- 50줄 초과 함수, 400줄 초과 파일 분리
- 기존 코드와 재사용 가능한 부분 탐색
- 의미가 같은 중복 코드 통합
- 확장성 검증: OCP 준수, 새 타입/케이스 추가 시 변경 범위 최소화, 인터페이스 설계 적절성

### 2단계: 잔여 이슈 수정
structure-optimizer가 보고한 잔여 이슈(MEDIUM 이하) 중 수정 가능한 항목을 처리한다:
- 재사용 기회로 보고된 코드 통합
- 400줄 초과 파일 분리 검토 (800줄 이하라도)
- 구조 변경 후 import 경로 정리

### 3단계: 테스트 실행
구조 변경 후 모든 테스트가 통과하는지 확인한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
```

**수정이 있었으면 promise를 출력하지 않는다.**

### 4단계: lint/format/type check (변경 파일만)
```bash
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 50줄 초과 함수 없음
- 800줄 초과 파일 없음
- 재사용 가능한 중복 코드 통합 완료
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

- **검증 이터레이션 ≥ 1** (첫 이터레이션 이후 최소 1회 전체 재검증 통과)

모든 조건 충족 시 <promise>REFACTOR DONE</promise> 출력.
