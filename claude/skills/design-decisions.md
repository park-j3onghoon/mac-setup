# 설계 원칙 (review · plan-review 공통 참조)

software engineer 로서의 **일반 설계 규칙**만 둔다.
⚠️ 프로젝트(payments-api 등)·프레임워크/라이브러리(pydantic 등)·언어·회사 컨벤션 **특화 내용은 여기 두지 않는다** → 메모리/coding-rules/플랜으로.
리뷰 서브에이전트는 이 원칙 위반을 `[CRITICAL/INFO] file:line — 위반 + 근거` 로 보고한다.

## 따르는 패러다임
**Clean Architecture · Hexagonal(Ports & Adapters) · CQRS · CQS · TDD · DDD.**
설계·리뷰는 이 패러다임 준수를 기준으로 점검한다. 아래 항목은 그 구체적 적용이다.

## 핵심 원칙
- **YAGNI**: 지금 필요하지 않은 것을 만들지 않는다.
- **KISS**: 동작하는 가장 단순한 해법. 우연한 복잡도(accidental complexity) 제거.
- **DRY (Don't Repeat Yourself)**: 모든 지식·결정은 **단일 출처(single source of truth)** 하나로. 단 *지식*의 중복만 대상 — 우연히 닮았을 뿐 다른 이유로 변하는 코드(accidental duplication)는 억지로 합치지 않는다. 성급한 추상화(잘못된 결합)는 약간의 중복보다 비싸다 → Rule of Three / AHA(Avoid Hasty Abstractions).
- **SOLID**: SRP · OCP · LSP · ISP · DIP.
- **Clean Code**: 의도를 드러내는 이름, 작은 함수, 한 가지 책임, 부수효과 최소.
- **긍정형 이름 우선**: 술어(predicate)는 `can_*`/`is_*`/`has_*` 긍정형을 우선한다 — `blocks_*`·`*_unfinished` 류 부정형보다 의도가 직접 읽히고 호출부 재사용이 쉽다(엔티티 `can_retrigger()` 처럼). 부정이 불가피하면 술어 자체는 긍정으로 두고 부정을 호출부 guard(`if not …: continue`)로 옮긴다.
- **Kent Beck Simple Design (우선순위 순)**: ① 테스트 통과 ② 의도 노출 ③ 중복 제거(DRY) ④ 요소 최소.

## 레이어 / 의존 방향 (Clean Architecture · Hexagonal)
- 의존은 **안쪽(domain)으로** 향한다. **domain 은 아무것도 의존하지 않는다.**
- `presentation → application → domain`. **`infrastructure → domain`** (domain 이 정의한 port 를 구현, DIP) — infrastructure 는 **application 구현에 의존하지 않는다**(추상=port 에만 의존, core 는 infra 를 모름).
- 설계는 domain 부터. infra 구현(repo 시그니처 등)에 도메인을 끼워 맞추지 않는다.
- 맥락 독립 → domain, 맥락 의존 → application.
- **게이트웨이/어댑터는 감싸는 서비스의 도메인 규칙을 재구현하지 않는다**: 프록시(BFF·gateway·adapter)는 입출력 변환·전달만 하고, 기본값·필드 병합/보존·불변식 같은 도메인 규칙은 그 도메인을 *소유한* 서비스가 갖는다. 게이트웨이가 흉내 내면(예: 호출자에서 read-modify-write 로 누락 필드 보존) 규칙이 두 곳에 흩어지고 동시성 레이스·드리프트가 생긴다. (도메인 로직은 도메인에 · SRP)

## 도메인 모델 / 상태머신 (DDD · rich domain)
- 엔티티가 불변을 강제(always-valid): 상태 전이는 엔티티 메서드가 검사하고, 잘못된 전이는 도메인 예외. 호출부 점검에 의존하지 않는다(불변이 흩어지고 누락됨).
- **상태머신은 "전이맵 + 공유 전이 메서드 + 이름있는 메서드" 하이브리드**로 표현한다: 전이 가능 여부는 전이맵 한 곳(단일 출처), 이름있는 메서드(`mark_*`)가 의도와 per-state 로직을 담고 공유 `_transition_to` 가 가드. 전이맵은 노출(테스트 재사용), 전이 추가는 맵 한 줄.
- 상태는 다른 필드에서 resolve 하지 말고 **저장**한다. 종결 상태·전이 다이어그램을 초기에 확정.
- 막는 건 "실제로 일어날 수 있는 잘못된 전이"만. 시스템상 불가능한 상태까지 막는 방어 가드는 노이즈.

## 확장 by 추가 (OCP · Clean Code)
- 기능 추가/수정이 **기존 코드 수정이 아니라 코드 추가**로 가능하도록 추상화(전략·다형성·port)를 적극 도입한다. 같은 분기를 반복 수정하게 되면 추상화로 OCP 를 확보.

## Command / Query (CQRS · CQS)
- 상태를 바꾸는 command 와 읽기만 하는 query 를 분리한다. command 는 부작용을 담당(반환 최소), query 는 부작용 없음. 읽기/쓰기 모델·경로가 갈리면 분리한다.

## Repository / 영속 (DDD · Hexagonal)
- Repository 는 기본적으로 aggregate/entity 를 반환한다(쓰기 모델, domain 이 정의한 port). 그러나 **"entity 만 반환해야 한다"는 통념이지 절대 규칙이 아니다** — count·summary·id projection 반환은 **Evans-DDD 가 Repository 패턴에서 명시 허용**(DB 가 잘하는 집계·카운트), "필요한 것만 주는" 좁은 query 메서드는 **Clean Architecture 의 ISP(인터페이스 분리 원칙)** 가 지지한다.
- **읽기 최적화**: 카운트·존재확인처럼 entity *데이터*가 불필요한 읽기는 entity 를 hydrate 해서 버리지 말고 **projection 메서드**(필요한 필드만, 예 `list[int]`)를 쓴다. hydrate-then-discard 는 낭비 — 특히 비싼 집계/FK 를 끌어올 때. 반환 타입 자체가 "aggregate 가 아니라 projection" 임을 드러내므로 주석 불필요.
- 단, **외부에 서빙하는 query 엔드포인트**용 읽기는 별도 read model(CQRS)로 분리한다. projection repo 메서드는 command-내부 계산(예: 진행률 분모 카운트)에 적합하다.

## TDD
- 테스트를 계약으로 먼저 쓰고, 구현은 통과시키는 최소 코드. (테스트 작성 세부 규칙은 coding-rules.)
