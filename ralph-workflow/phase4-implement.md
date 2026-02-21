# Phase 4: 구현

## 지시사항

체크리스트와 구현 계획을 읽고, **원본 spec의 해당 라인을 참조하며** TDD로 구현하라.
**모든 REQ 구현 후에도, 남은 이터레이션은 spec 재대조에 사용한다.**

**Spec**:
{{SPEC_PATH}}
**스펙 요약**: {{DIGEST_PATH}} (핵심 개념, 교차 참조, 전역 제약. 먼저 읽고 큰 그림을 파악하라.)
**구현 디렉토리**: {{MODULE_PATH}}
**체크리스트**: {{CHECKLIST_PATH}} (Phase 0에서 생성된 요구사항 인덱스)
**계획**: {{PLAN_PATH}} (Phase 0에서 작성된 구현 계획)
**메모**: {{NOTES_PATH}} (이전 Phase의 발견/수정 사항. 읽고 참조하라. 수정 시 기록하라.)

## 공통 원칙

1. **수정 발생 시 promise 출력 금지** — 수정 없는 클린 이터레이션에서만 promise 출력

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
4. {{TEST_PATH}} 내 기존 테스트 파일의 구조/패턴/conftest를 확인하고 동일한 컨벤션을 따른다.
5. 모든 REQ가 `- [x]`이면 → **3단계(구현 재대조)로 이동**한다 (건너뛰지 않는다).

### 2단계: 기존 구현 재확인 + Unit별 TDD 사이클 구현

현재 Unit의 REQ 항목에 대해:

**a) 기존 구현 확인** (각 REQ 구현 전 필수):
{{CHECKLIST_PATH}}의 "기존 구현 매핑" 섹션을 확인한다.
- "그대로 호출"로 표시된 REQ → 새로 구현하지 않고 기존 함수를 import하여 호출한다.
- "래핑하여 재사용"으로 표시된 REQ → 기존 함수를 래핑하는 얇은 어댑터만 작성한다.
- "신규 구현"으로 표시된 REQ → TDD 사이클로 새로 구현한다.

**추가로**, 계획에 없던 기존 코드를 발견할 수 있다. 각 REQ 구현 전에:
1. 구현하려는 기능의 핵심 키워드로 {{MODULE_PATH}}와 프로젝트를 Grep 검색한다.
2. 동일/유사 함수가 발견되면 Read로 읽고 재사용 가능 여부를 판단한다.
3. 재사용 가능하면 → 호출/래핑으로 대체. {{CHECKLIST_PATH}}의 기존 구현 매핑을 업데이트한다.
4. 재사용 불가(시그니처 다르고 목적도 다름)면 → 신규 구현 진행.

**b) 원본 spec 읽기**:
체크리스트의 라인 참조(예: `[spec.md:45-52]`)를 보고, 해당 spec 파일의 **해당 라인만** Read(offset, limit)로 읽는다. 전체 spec을 읽지 않는다.

**c) 구현 순서** (DDD 레이어 순, 인터페이스 먼저 → 구현체):
1. `domain/` — Entity, VO, exceptions 먼저. 그 다음 Protocol(인터페이스) 정의, Domain Service
2. `application/` — Use Case / Application Service (Protocol에 의존, 구현체에 의존하지 않음)
3. `adapter/` — domain Protocol의 구현체 (Repository, 외부 시스템 어댑터)

**d) 각 REQ별 TDD 사이클** (신규 구현 REQ + 재사용 REQ):

> **재사용 REQ도 테스트 작성 대상이다.** "그대로 호출"이나 "래핑하여 재사용"으로 표시된 REQ라도, 현재 spec 맥락에서의 동작을 검증하는 테스트를 작성한다. 기존 함수의 단위 테스트가 있더라도, 현재 use case에서 올바르게 동작하는지(입력 범위, 반환값, 에러 케이스)를 별도로 테스트한다.

**RED** — 테스트 먼저 작성하고 실패를 확인한다:
- **부정 시나리오(에러/예외 경로)를 먼저 작성한다**: 잘못된 입력, 권한 없음, 존재하지 않는 리소스, 중복 요청 등
- 그 다음 정상 시나리오 테스트를 작성한다
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v -x
```
테스트가 실패(RED)하는 것을 확인한 뒤 다음 단계로 넘어간다.

**GREEN** — 테스트를 통과하는 최소한의 구현을 작성한다.

**REFACTOR** — 중복 제거, 네이밍 개선. 테스트가 여전히 통과해야 한다.

**구현 중 준수 원칙 체크리스트** (매 REQ 완료 시 자가 점검):
- [ ] **YAGNI**: spec에 없는 기능, 미래 확장용 추상화, 사용하지 않는 파라미터를 추가하지 않았는가?
- [ ] **SRP**: 이 클래스/함수가 하나의 책임만 가지는가? 변경 이유가 하나인가?
- [ ] **DIP**: 상위 레이어(domain/application)가 하위 구현체를 직접 import하지 않는가?
- [ ] **CQS**: 상태를 변경하는 메서드가 값을 반환하지 않는가? (프레임워크 컨벤션 제외)
- [ ] **Aggregate 경계**: 하나의 트랜잭션에서 여러 Aggregate를 수정하지 않는가?
- [ ] **최소 요소**: 같은 목적의 클래스/함수가 이미 있지 않은가? 불필요한 레이어를 추가하지 않았는가?
- [ ] **긍정 네이밍**: 변수/함수명에 부정 표현 대신 긍정 표현을 사용했는가? (예: `is_valid` O, `is_invalid` X / `is_active` O, `is_not_active` X / `can_proceed` O, `cannot_proceed` X). 조건문도 `if is_valid` 형태가 `if not is_invalid`보다 낫다.

**e) 체크리스트 업데이트**:
구현 완료한 REQ 항목을 {{CHECKLIST_PATH}}에서 `- [x]`로 변경한다.

### 3단계: 구현 재대조 (모든 REQ가 `[x]`가 된 후, 매 이터레이션 반복)

**모든 REQ가 `[x]`가 된 후에도 promise를 바로 출력하지 않는다.**
남은 이터레이션을 활용하여 구현이 spec과 정확히 일치하는지 재대조한다.

**절차:**
1. {{CHECKLIST_PATH}}의 `[x]` 항목을 **처음부터 순서대로** 순회한다.
2. 각 항목의 라인 참조를 따라 원본 spec을 Read(offset, limit)로 읽는다.
3. 구현 코드가 spec 원문의 **모든 조건**을 정확히 구현했는지 대조한다.
4. 불일치 발견 시 → 코드 수정 + 테스트 추가/수정. promise를 출력하지 않는다.

매 이터레이션마다 **모든 `[x]` 항목**을 처음부터 끝까지 순회한다. 불일치가 0건이면 4단계로 진행한다.

### 4단계: 통합 테스트 추가

Unit 테스트에 더하여, 주요 사용자 시나리오에 대한 **통합 테스트**를 작성한다:
- API 엔드포인트가 있는 경우: 요청→응답 전체 흐름 테스트
- Use Case 간 연동이 있는 경우: 시나리오 테스트 (예: 생성 → 수정 → 삭제)
- 외부 의존성이 있는 경우: mock을 사용한 통합 테스트
- 테스트 파일명: `test_integration_*.py` 또는 기존 프로젝트 컨벤션 따름

### 5단계: 전체 테스트 및 커버리지 확인
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v --cov={{MODULE_PATH}} --cov-fail-under=80
```

### 6단계: lint/format/type check (변경 파일만)
```bash
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 체크리스트의 모든 REQ 항목이 `- [x]`
- **구현 재대조 완료**: 모든 `[x]` 항목을 라인 참조로 spec과 대조, 불일치 0건
- 주요 시나리오 통합 테스트 작성됨
- 모든 테스트 통과
- 커버리지 80% 이상
- 변경 파일 ruff check/format 경고 0건
- 변경 파일 mypy 에러 0건
- DDD 레이어 의존성 위반 없음

- **클린 이터레이션 ≥ 1** (수정 없는 이터레이션이 최소 1회 있어야 함)

모든 조건 충족 시 <promise>IMPL DONE</promise> 출력.
