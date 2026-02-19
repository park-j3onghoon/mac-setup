# Phase 1: 구현

## 지시사항

아래 spec 파일과 계획을 읽고 TDD로 구현하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}
**계획**: {{PLAN_PATH}} (Phase 0에서 작성된 구현 계획)

## DDD 레이어 규칙

구현 시 다음 의존성 방향을 반드시 준수한다:
- `domain/`: 순수 Python만. Django/프레임워크 import 금지. Entity, VO, Domain Service, Protocol(인터페이스), exceptions 정의
- `application/`: domain만 의존. adapter/infra import 금지. Use Case, Application Service
- `adapter/`: domain Protocol 구현. Django ORM, 외부 API 등 프레임워크 의존 허용
- `infra/`: 인프라 관심사 (설정, 미들웨어 등)

## 절차

### 1단계: 계획 및 spec 확인
1. {{PLAN_PATH}}를 읽고 구현 계획과 순서를 파악한다.
2. spec 파일을 읽고 요구사항을 확인한다.
3. CLAUDE.md와 CLAUDE.local.md의 코딩 컨벤션을 확인한다.

### 2단계: TDD 사이클로 구현

계획의 각 기능에 대해 다음 순서로 구현한다:

**구현 순서** (DDD 레이어 순):
1. `domain/` — Entity, VO, Domain Service, exceptions, Protocol
2. `application/` — Use Case / Application Service
3. `adapter/` — Repository 구현체, 외부 시스템 어댑터

**각 기능별 TDD 사이클**:

**a) RED** — 테스트 먼저 작성하고 실패를 확인한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v -x
```
테스트가 실패(RED)하는 것을 확인한 뒤 다음 단계로 넘어간다.

**b) GREEN** — 테스트를 통과하는 최소한의 구현을 작성한다.

**c) REFACTOR** — 중복 제거, 네이밍 개선. 테스트가 여전히 통과해야 한다.

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

- spec에 명시된 파일이 모두 존재
- 모든 테스트 통과
- 커버리지 80% 이상
- 변경 파일 ruff check/format 경고 0건
- 변경 파일 mypy 에러 0건
- DDD 레이어 의존성 위반 없음

모든 조건 충족 시 <promise>IMPL DONE</promise> 출력.
