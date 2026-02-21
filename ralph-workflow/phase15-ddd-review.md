# Phase 15: DDD 심층 검증

## 지시사항

도메인 주도 설계의 심층 원칙을 검증하라. 단순 레이어 의존성을 넘어 aggregate, value object, domain event, repository 패턴 수준까지 검증한다.

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

### 1단계: DDD 심층 검토

Task(subagent_type='ddd-reviewer')를 호출한다. **{{CHECKLIST_PATH}}를 전달**하여:
- Aggregate Root 경계가 올바른지 (트랜잭션 일관성 단위)
- Aggregate 간 참조가 ID로만 이루어지는지
- Value Object가 불변이고 값 기반 동등성을 가지는지
- Value Object가 자체 유효성 검증을 수행하는지
- 중요 상태 변경 시 Domain Event가 발행되는지 (spec에 이벤트 요구사항이 있는 경우)
- Repository가 Aggregate Root 단위인지 (하위 Entity별 Repository 금지)
- Repository 인터페이스(Protocol)가 domain 레이어에 있는지
- Bounded Context 간 번역 레이어가 있는지
- Domain Service가 stateless인지

### 2단계: 이슈 수정

ddd-reviewer가 보고한 CRITICAL/HIGH 이슈를 수정한다:
- Aggregate 경계 위반 → 적절한 경계로 재구성
- VO 가변성 → frozen dataclass/NamedTuple로 변경
- Repository 위반 → Aggregate Root 단위로 재구성
- 레이어 오염 → import 정리 및 레이어 이동

### 3단계: 테스트 및 lint/format/type check (변경 파일만)

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

- ddd-reviewer CRITICAL/HIGH 이슈 0건
- Aggregate 경계 위반 0건
- Value Object 가변성 0건
- Repository 패턴 위반 0건
- 레이어 의존성 위반 0건
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

- **클린 이터레이션 ≥ 1** (수정 없는 이터레이션이 최소 1회 있어야 함)

모든 조건 충족 시 <promise>DDD DONE</promise> 출력.
