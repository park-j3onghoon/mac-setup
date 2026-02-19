# Phase 1: 구현

## 지시사항

체크리스트와 구현 계획을 읽고, **원본 spec의 해당 라인을 참조하며** TDD로 구현하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}
**체크리스트**: {{CHECKLIST_PATH}} (Phase 0에서 생성된 요구사항 인덱스)
**계획**: {{PLAN_PATH}} (Phase 0에서 작성된 구현 계획)

## DDD 레이어 규칙

구현 시 다음 의존성 방향을 반드시 준수한다:
- `domain/`: 순수 Python만. Django/프레임워크 import 금지. Entity, VO, Domain Service, Protocol(인터페이스), exceptions 정의
- `application/`: domain만 의존. adapter/infra import 금지. Use Case, Application Service
- `adapter/`: domain Protocol 구현. Django ORM, 외부 API 등 프레임워크 의존 허용
- `infra/`: 인프라 관심사 (설정, 미들웨어 등)

## 절차

### 1단계: 체크리스트 및 계획 확인

1. {{CHECKLIST_PATH}}를 읽고 미완료(`- [ ]`) 항목을 파악한다.
2. {{PLAN_PATH}}를 읽고 다음 구현할 Unit을 확인한다.
3. CLAUDE.md와 CLAUDE.local.md의 코딩 컨벤션을 확인한다.
4. 모든 REQ가 `- [x]`이면 3단계로 건너뛴다.

### 2단계: Unit별 TDD 사이클 구현

현재 Unit의 REQ 항목에 대해:

**a) 원본 spec 읽기**:
체크리스트의 라인 참조(예: `[spec.md:45-52]`)를 보고, 해당 spec 파일의 **해당 라인만** Read(offset, limit)로 읽는다. 전체 spec을 읽지 않는다.

**b) 구현 순서** (DDD 레이어 순):
1. `domain/` — Entity, VO, Domain Service, exceptions, Protocol
2. `application/` — Use Case / Application Service
3. `adapter/` — Repository 구현체, 외부 시스템 어댑터

**c) 각 REQ별 TDD 사이클**:

**RED** — 테스트 먼저 작성하고 실패를 확인한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v -x
```
테스트가 실패(RED)하는 것을 확인한 뒤 다음 단계로 넘어간다.

**GREEN** — 테스트를 통과하는 최소한의 구현을 작성한다.

**REFACTOR** — 중복 제거, 네이밍 개선. 테스트가 여전히 통과해야 한다.

**d) 체크리스트 업데이트**:
구현 완료한 REQ 항목을 {{CHECKLIST_PATH}}에서 `- [x]`로 변경한다.

### 3단계: 전체 테스트 및 커버리지 확인
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v --cov={{MODULE_PATH}} --cov-fail-under=80
```

### 4단계: lint/format/type check (변경 파일만)
```bash
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 체크리스트의 모든 REQ 항목이 `- [x]`
- 모든 테스트 통과
- 커버리지 80% 이상
- 변경 파일 ruff check/format 경고 0건
- 변경 파일 mypy 에러 0건
- DDD 레이어 의존성 위반 없음

모든 조건 충족 시 <promise>IMPL DONE</promise> 출력.
