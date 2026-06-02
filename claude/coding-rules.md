# Coding Rules — 모든 언어/프로젝트에 공통 적용할 규칙

이 파일은 리뷰와 피드백에서 학습한 "코드를 쓸 때 따라야 할 공통 규칙"이다.
코드를 작성/수정할 때 이 파일을 참조하여 같은 실수를 반복하지 않는다.

언어/프레임워크/프로젝트 특화 규칙은 서브 파일에 있다. 현재 작업 대상에 해당하면 함께 읽는다:

- `coding-rules-python.md` — Python / Django / Pydantic
- `coding-rules-vue.md` — Vue + Buzzvil 메인 프로젝트 (ads-center 등)
- `coding-rules-frontend.md` — React / Vue 프론트 공통

도구별 노하우는 메모리에 있다:

- `reference_tool_{tool}.md` — Playwright 등 특정 도구 전용 노하우
- `project_{name}.md` — 해당 프로젝트에만 국한된 노하우

> `/review` Step 9에서 자동 업데이트된다. 수동 추가도 가능.

---

## 아키텍처 / 모델 설계

- **단방향 의존성 필수, 순환 의존 금지**. A가 B를 참조하면 B는 A를 절대 알아서는 안 된다. 순환이 되면 분리한 의미가 없다.
- **상태는 resolve가 아니라 저장**. 다른 필드에서 현재 상태를 계산(resolve)하는 방식 지양. 이벤트 기반 동작(이메일 1회 발송 등)은 resolve만으로 "이미 실행했는지" 판단 불가 — 명시적 상태 필드를 저장한다.
- **상태값은 초기에 정확히 설계**. 상태는 잘 변하지 않으므로 처음에 전이 다이어그램과 종결 조건을 확정한다.
- **페이지네이션 메타 계산은 application(usecase) 책임**. Repo는 DB 프리미티브(`limit`/`offset`)와 `count`/`items`만 반환. `num_pages`/`has_next`/`has_previous`/페이지 번호 같은 "비즈니스 페이지 계약" 계산은 호출자(usecase)가 수행. Repo가 `page_number`/`page_size`를 알면 infra 레이어에 비즈니스 계약이 침투.
- **시간 범위 인자는 수신자 타임존에 맞춰 변환**. repo/API 구현체가 전달받은 `date`를 특정 타임존 자정에 앵커링하면(예: `arrow.replace(tzinfo='Asia/Seoul').floor('day')`), 호출부는 동일 타임존 기준 달력 날짜(`astimezone(tz).date()`)를 넘긴다. UTC tz-aware `datetime`에 `.date()`만 쓰면 경계 구간(UTC 15:00~23:59)에서 off-by-one. 계약은 주석·타입이 아닌 **실제 repo 내부 처리 방식**을 확인한다.
- **Repo는 entity를 있는 그대로 저장한다**. 수정 가능 필드 whitelist/blacklist 같은 도메인 정책 강제는 application(usecase) 책임. infra는 시스템 필드(id/created_at/updated_at) 제외만 수행. Repo가 "어느 필드가 수정 가능한지" 판단하면 다른 usecase(승인/반려/취소 등)가 동일 `update()`를 못 쓰게 된다. 도메인 규칙은 DTO 설계·usecase 분기·엔티티 라우팅으로 표현한다.
- **Repo `_to_entity` 정규화는 역방향 write와 비대칭임을 고려**. raw DB 값(schedule/live/pause/close) → canonical entity 값(APPROVE)으로 읽을 때 정규화하면, entity를 그대로 저장할 때 canonical 값이 DB EnumField에 없어서 충돌한다. 정규화를 응답 payload 계층으로 옮기거나, entity는 raw 값을 유지하고 정규화된 view는 별도 field/proeprty로 노출한다.

## 코드 구조

- **import는 파일 최상단에 배치**. 함수/메서드 내부 import 금지. 순환 import는 모듈 구조로 해결.
- **2곳 이상 반복 로직은 추출**. 판별 로직은 해당 도메인 모듈에, 포맷팅/변환은 공유 유틸에.
- **불필요한 default 값 금지**. 모든 callsite가 명시적으로 값을 전달하면 default 제거.
- **컬렉션 파라미터는 non-nullable, 빈 컬렉션으로 default**. nullable 배열/맵 대신 빈 컬렉션 = "필터 없음". 스칼라는 null/None 허용.
- **한 번만 쓰는 코드에 과도한 추상화 금지**.
- **리팩토링 스코프 밖 새 추상화 무단 추가 금지**. 사용자/이슈가 요청한 변경만 수행한다. 유사 위치에 ClassVar·헬퍼 메서드·레이어를 "겸사겸사" 추가하면 사용자가 "처음에 없었는데 왜 새로 넣었냐"로 되돌림 요청한다. 기존에 없던 구조를 넣기 전에 사용자 확인.
- **인라인 가능하면 인라인을 선호**. 단, 100~110자를 초과하면 변수로 분리.
- **인터페이스/클래스의 메서드 순서는 일관되게**. Repository/Port 인터페이스는 **CRUD 순서**로 통일: `save` → `findBy*` / `findAll*` → `countBy*` → `existsBy*` → `deleteBy*`(또는 `update/revoke` 등 변경 동작). 파일마다 순서가 다르면 리뷰어가 "어느 게 메인 엔트리포인트인지" 파악하기 어렵고, 비슷한 포트끼리 비교가 힘들어진다. 한 프로젝트 안에서 동일 패턴 유지.

## 함수 분할 / 설계 패턴

- **함수 길이는 Clean Code / Google guide 기준** (30~40줄 soft limit). 초과 시 책임 단위로 private helper 분할 (Composed Method 패턴, Bob Martin). "한 번만 쓰는 코드에 과도한 추상화 금지" 룰은 *cross-module utility* 자제 의미 — 같은 모듈 안 step helper 분할은 OK.
- **Composed Method + Stepdown Rule**: 분할 후 파일 내 순서는 **public main 위 → helper 아래** (위→아래로 추상화 한 단계씩 내려감). Python 은 late binding (runtime lookup) 이라 helper 가 main 아래에 있어도 호출 시점에 module 정의 완료 후라 동작 OK.
- **SRP + CQS 적용**: helper 도 단일 책임 (reason to change 가 하나). **Query** (값 반환 + side-effect 없음) 와 **Command** (state 변경 + void) 분리. 한 함수가 둘 다 하면 분할.
- **CQS 의 도메인 예외 수용**: entity 메서드 (`Entity.change()` 등) 가 in-memory mutate + 결과 반환 — DDD / cosmicpython 도메인 객체 패턴이라 엄격 CQS 와 충돌하지만 도메인 차원 수용.
- **immutable copy 패턴**: helper 가 dict/list mutate 가 자연스러워도 CQS 정합 위해 `dict(input) + 수정 + 새 객체 반환` 권장.
- **`private → private` 호출 OK** (2026-05-19 reversal): 같은 추상화 수준의 step helper 가 서로 호출해도 됨. 단 **cross-usecase 호출은 여전히 금지** (atomic validator 만 공유).
- **dataclass vs dict (kwargs 표현)**: entity API 가 sentinel 스타일 (None=변경 안 함, unset_xxx=명시 unset) 이면 dict 가 자연스럽게 fit (명시 set vs default 구분 가능). dataclass 도입은 entity API 의 sentinel 리팩토링 (`UNSET` sentinel / 별도 메서드) 과 함께 진행 — 그 전엔 dict 유지.
- **helper 의 책임 단일화 — 진입 가드는 호출자**: helper 함수가 첫머리에서 `if 진입조건: return` 을 쌓고 있다면 그 가드는 helper 가 아니라 호출자 (loop `continue` 또는 early return) 의 책임이다. helper 는 함수 이름이 약속한 로직만 수행한다 — 그래야 이름과 동작이 일치하고 호출 흐름이 외부에서 읽힌다. 예: `_verify_value(field, value, registry)` 내부에 `if field not in mask: return` / `if not value: return` 을 두지 말고, 호출자 loop 에서 `continue` 로 처리.
- **동일 패턴 N 호출은 list + loop 로**: 같은 helper 를 인자만 바꿔 2회 이상 명시 호출한다면 `(인자조합)` list 를 모듈 상수로 빼고 for-loop 로 묶는다. 4 호출 + 비슷한 매핑 검증 2 호출 같이 누적되면 가독성 큰 차이.
- **모듈 상수는 파일 최상단**: 모듈 상수 (`_STRATEGY_REGISTRIES` 등) 는 imports + logger 정의 다음, 첫 함수 정의 전 위치. 함수들 사이에 끼면 가독성 떨어지고 "어디서 정의됐지" 추적 부담.

## 에러 처리

- **update/delete에서 대상 미존재 시 도메인 예외** (`NotFound` 등). null/None 반환 금지.
- **find/search에서 null/None 반환 허용**. 없을 수 있는 조회는 None OK.
- **구분 기준**: 호출자가 "없을 수 있다"고 예상하면 None, "있어야 한다"가 전제면 예외.
- **Retrieve API 응답 404 vs 200+null 구분**:
  - **id 기반 리소스 상세 조회**(`GET /resources/{id}`): 리소스 부재 시 **404 (NotFound 예외)**. REST 표준.
  - **조건 기반 단건 조회**("조건 맞는 하나 찾기", 예: "진행중 amendment"): 없으면 **200 + null 필드**. "찾아봤는데 없음"이 정상 경로.
- **포괄 예외 핸들러에서 원본 에러 메시지를 클라이언트에 노출 금지**. 고정된 에러 응답을 반환하고 원본 에러는 로깅에만 남긴다.
- **Unreachable 분기는 맥락에 맞게 처리**. 순수 함수의 도달 불가 분기는 "안전한 fallback 반환 + '정상 경로 도달 불가: ...' 주석"이 호출부에 혼란을 덜 준다. 반면 async handler/이벤트 핸들러의 invariant 위반은 `throw new Error('unreachable: ...')`로 즉시 노출해 Sentry/콘솔로 원인 추적 가능하게 한다. 조용히 return하면 유저에게 피드백 없이 사일런트 실패한다.
- **외부 서비스/네트워크 호출에는 항상 타임아웃을 건다**. HTTP/gRPC/SMTP/외부 API 등 응답이 보장되지 않는 호출은 타임아웃이 없으면 무한 대기로 스레드/커넥션/트랜잭션/락을 묶는다. 클라이언트 레벨 타임아웃(connect/read)을 명시하고, **DB 트랜잭션·락을 쥔 채 외부 호출을 하는 경우엔 특히** 상한을 둬서 락 보유 시간이 외부 응답 지연에 종속되지 않게 한다(예: Django `EMAIL_TIMEOUT`, requests `timeout=`, gRPC `timeout=`).

## 네이밍

- **용어는 코드베이스 기존 용어와 일치**. 같은 개념에 다른 단어 사용 금지.
- **함수명 = 비즈니스 역할**. 구현 세부사항(async, thread) 노출 금지.
- **모델 필드명 = DB 컬럼명**. 디버깅 용이성.

## 주석

- **기본은 주석 없음**. 식별자·시그니처로 파악되는 것은 적지 않는다. "무엇"이 아니라 "왜"만 적는다.
- **남길 맥락**:
  - 외부 표준 참조 (AIP-XXX, RFC NNNN, 회사 RFC 링크)
  - 보안 근거 (enumeration 방지, capability 토큰, XSS 벡터 차단 등)
  - 아키텍처 결정 근거·검토 후 채택하지 않은 대안
  - 비명시적 알고리즘 트릭 (limit+1 hasNext, microsecond precision cursor, base64url 형식 등)
  - 혼동되는 코드/타입 간 disambiguation (vs 비교)
  - 숨어 있는 제약·invariant (DB 컬럼 타입 정합, 외부 API 응답 nullability 가정 등)
- **지워야 할 주석**:
  - 시그니처로 자명한 함수/클래스 동작 설명
  - 데이터 클래스의 "X용 VO/DTO" 라벨
  - 변경 이력·과거 구현 ("이전에는 Map이었으나...") — git log·PR 본문이 담당
  - 호출자 정보 ("X 화면이 이걸 쓴다") — 코드 변경에 따라 거짓이 된다
  - 한 줄 식별자를 풀어 쓴 설명 (`"X 토큰을 생성한다"` / `fun generate(): String`)
- **지웠을 때 미래 독자가 헷갈리면 남기고, 그렇지 않으면 지운다.**

## 테스팅

- **테스트 메서드명은 영어**.
- **프레임워크 빌트인 검증 테스트 금지**. 프레임워크가 보장하는 제약(필드 타입, Enum, 필수/선택 등)은 테스트하지 않는다. "이 테스트가 검증하는 건 우리 코드인가, 프레임워크인가?" 자문. 자매 모듈을 복사할 때는 원본의 테스트 관행(어떤 레이어를 테스트/생략하는지)을 먼저 확인하고 따른다.
- **순수 데이터 객체 단독 테스트 불필요**. UseCase/Repo/Service 테스트에서 자연스럽게 검증된다.
- **스냅샷 테스트 금지**. private dict 복붙 비교는 의미 없음.
- **무효 케이스 전수 검증 불필요**. 유효 케이스로 비즈니스 규칙 검증이면 충분.
- **단순 조합 UseCase 단독 테스트 불필요**. 필드 조합만 하고 비즈니스 로직이 없는 UseCase는 View/Controller 통합테스트에서 커버.
- **중복 테스트 통합, 헬퍼는 공통 위치에 집중** (pytest는 conftest, vitest는 shared helper 등).
- **개인 프로젝트(linkcart 등 회사 외부 repo)는 MC/DC 커버리지(Modified Condition/Decision Coverage) 만족**. 복합 조건 `A && (B || C)`에서 각 sub-condition이 다른 condition을 고정한 채 단독으로 decision을 뒤집은 적이 있어야 한다. branch coverage 100%로는 부족. n+1개 케이스로 보통 충분(n=condition 수). JaCoCo 등 native 지원이 없으므로 입력 조합표를 직접 설계해 확인. 회사 프로젝트(buzzvil 등)에는 미적용.

## Git / CI

- **push 전 관련 테스트 실행**. 빌드/타입체크를 통과해도 런타임에서만 드러나는 에러는 테스트로 잡는다.
- **파일 이동/import 변경 후 빌드 검증 필수**. 테스트 통과 ≠ 빌드 성공. 프레임워크의 빌드 명령을 직접 돌려 확인한다.
- **import 경로는 절대 경로 우선** (path alias 사용).
- **stacked branch merge 후 하위 브랜치 전파 필수**. base 브랜치에 변경 push 후 의존 브랜치에 merge 전파. conflict는 즉시 해결.
- **commit/merge 전 현재 브랜치 확인 필수**. 여러 브랜치를 오가는 세션에서는 직전 checkout이 원하는 브랜치인지 `git branch --show-current`로 먼저 확인한 뒤 명령을 실행한다. 엉뚱한 브랜치에 커밋하면 reset + 재작업이 필요해 시간 손실이 크다.

## PR

- **PR 본문에 RFC/PRD 링크 포함** (해당 문서가 있다면).
- **커밋 메시지, PR 제목/본문은 한글**.
- **PR 코멘트 답글은 습니다체, 자연스럽게**. 커밋 해시 금지, 로봇 포맷 금지.
- **PR push 후 제목/본문이 코드와 일치하는지 확인**. 파일 추가/제거/이동 시 PR 본문의 파일 목록도 갱신.
- **다수 리뷰어 독립 지적은 반영 가중**. 2명 이상의 리뷰어(봇 포함)가 같은 이슈를 독립적으로 지적하면 반영 신호. 1명 지적은 설계 의도 설명으로 갈음 가능하지만, 독립 2명 이상은 관점이 더 나을 가능성이 높다.
- **반복 지적은 재고려**. 이전 라운드에 "의도"로 답변한 이슈를 리뷰어가 다시 지적하면 "답변으로 끝"보다 재검토/반영이 안전. 한 번 거부 후 반복되면 설명이 부족했거나 리뷰어의 관점이 옳았을 가능성.
- **PRD/디자인 근거 없는 방어 로직은 YAGNI**. 규격에 없는 "안전 장치"(취소 시 확인 모달 등)는 기본적으로 빼는 쪽. 되돌릴 수 없는 유저 손실 방어처럼 명확한 근거가 있을 때만 추가.
- **호출처 1곳 헬퍼도 "단일 방어 지점" 가치가 있으면 허용**. Rule of Three 예외: 이중 캐스트(`as unknown as T`)나 drift 방어를 캡슐화하는 함수는 호출처가 1곳이어도 미래 변경 포인트를 한 곳에 모으는 가치가 있음.

## 코드 변경 원칙

- **코드 변경 제안 전 다른 모듈의 기존 패턴을 먼저 확인**한다 (Grep).
- **리뷰 에이전트 제안을 맹목적으로 적용하지 않는다**. 기존 패턴을 확인한 뒤 판단.
- **파일 있다/없다/삭제됐다 단정 전 실제로 확인**한다 (git diff/ls).
