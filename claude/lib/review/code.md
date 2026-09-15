# 코드 공통 리뷰 기준

diff를 아래 카테고리별로 빠짐없이 검증한다. 각 항목에 해당 여부를 명시적으로 판단하고, 해당 시 파일:라인을 인용한다.

## 1. 보안 (Security)

`~/.claude/lib/review/security-gate.md`를 Read하고 그 여섯 항목을 판정한다. diff에 트리거가 없으면 `해당 없음` 한 줄로 끝낸다. 그 이상은 보안 서브에이전트 몫이라 여기서 파고들지 않는다.

## 2. 정확성 (Correctness)

- **Enum/값 완전성**: 새 enum 값 추가 시 모든 참조 위치에서 처리하는지. diff 외부 코드도 Grep으로 확인.
- **데이터 정의 검증**: 쿼리 결과가 비즈니스 정의와 일치하는지 (클릭, 전환, 기여 인정 등)
- **SQL 쿼리 논리**: JOIN 순서, GROUP BY/DISTINCT, 1:N 카운팅 중복
- **시간 계산**: floor/shift/ceil에서 off-by-one, 타임존 변환 경계
- **조건 분기 엣지케이스**: start_date만 있고 end_date 없을 때, null/empty 구분

## 3. 계약 일관성 (Contract Consistency)

- **함수 시그니처 ↔ mock/fake 동기화**: diff에서 함수 파라미터가 변경되면 테스트의 mock/fake를 Grep. `grep -rn "def mock_{함수명}\|def fake_{함수명}" tests/`
- **dataclass/VO 필드 추가 시 수동 생성자 동기화**: 기본값 없는 필드 추가 시 `grep -rn "ClassName(" tests/`로 수동 dict 구성 테스트 검색. 팩토리(`get_dataclass_example`)는 자동이라 OK, 수동 dict만 위험.
- **SELECT ↔ INSERT 컬럼 동기화**: 같은 데이터를 SELECT하는 함수와 INSERT하는 함수가 별도인 경우, SELECT에 새 컬럼을 추가했으면 INSERT에도 반드시 추가. `generate_*()` 결과를 `_empty_and_insert_*()` 로 넣는 패턴에서 특히 주의.
- **Django ORM annotate ↔ dataclass 필드 동기화**: ORM의 `.annotate()`에 새 필드를 추가했는지 확인. annotate에 없으면 결과 dict에 키 누락 → `Dataclass(**val)` TypeError.
- **하위 호환성**: 기존 동작이 깨지지 않는지. proto 필드 번호, 직렬화 형식.
- **FE-BE 데이터 정합성**: 응답 필드명/타입이 프론트 기대와 일치하는지.
- **proto ↔ wire DTO (cmd) 필드 매핑**: `MessageToDict(request) → Cmd(**dict)` spread 패턴 사용 시, proto 메시지의 필드 구조와 cmd DTO 의 필드명/타입이 정확히 일치해야 함. proto 가 nested object (`payment_group: PaymentGroupDetail`) 인데 cmd 가 lookup key (`payment_group_name: str`) 면 pydantic `extra='ignore'` 기본값 때문에 silent drop. 특히 proto + cmd 가 별도 PR/publish 일 때 publish 순서 의존성을 PR description 에 머지 차단 조건으로 명시.

## 3-1. 반환 타입 정확성 (Return Type Safety)

- **update/delete에서 None 반환 금지**: 존재해야 하는 데이터가 없으면 None이 아닌 도메인 예외(`NotFound`) 발생. None 반환은 "성공했는데 사라짐" vs "실패" 구분 불가, silent failure 위험.
- **find/search에서 None 반환 허용**: 없을 수 있는 조회는 None OK.
- **구분 기준**: 호출자가 "없을 수 있다"고 예상하면 None, "있어야 한다"가 전제면 예외.

## 4. 클린 코드 / 네이밍 (Clean Code)

- **용어 일관성**: 같은 개념에 다른 단어 (`alternative` vs `substitute`). 기존 코드베이스 용어와 일치.
- **네이밍 명확성**: 변수/함수명이 동작을 정확히 설명하는지. 모델 필드명과 DB 컬럼명 일치.
- **매직 넘버**: 하드코딩된 값. 상수로 추출 필요 여부.
- **중복 로직 (Rule of Three)**: **같은 로직이 3회 이상** 반복되면 함수 추출 제안. 2회는 보류 가능하다. 잘못된 추상화를 되돌리는 비용이 중복 제거 이득보다 클 수 있다. 팀 관행에 없는 공용 헬퍼/레이어 신설은 특히 신중(리뷰어 저항 가능).
- **주석 미니멀리즘 (CRITICAL)**: 주석은 *코드로 안 드러나는 why/외부 맥락*만. 아래는 모두 제거/이동 대상으로 flag:
  - 코드/표준지식 재진술 (`# compare-and-set 으로 중복 방지`, `# in_progress 면 failed 로`, `# try/except 로 격리`). 코드 구조가 이미 보여줌.
  - **다줄 설계 정당화(design essay)**: "왜 안전한가/왜 이 설계인가"를 문단으로 설명. 한 줄 외부사실로 줄이거나 PR 본문·plan 으로 이동.
  - **다른 모듈/함수의 동작 설명**: 이 코드 옆이 아니라 그 코드 옆에. 검증: "이 주석이 설명하는 동작이 *이 함수 안*에 있나?"
  - 남길 것: 외부 contract(타 브랜치/DBA/시스템 사실로 코드에 안 보이는 것), 채택 안 한 대안 이유, 비명시 알고리즘 트릭. 자기점검: "지우면 코드만 보고 의도를 놓치나? 아니오 → 삭제."
  - **AUTO-FIX 가 주석을 늘리지 말 것**: 리뷰 중 "주석 정합/보강"으로 설명을 *추가*하는 건 미니멀리즘 위반. 정합이 필요하면 *줄이는* 방향으로만.
- **인터페이스 메서드 순서 일관성**: Repository/Port 인터페이스는 **CRUD 순서**(`save` → `findBy*`/`findAll*` → `countBy*` → `existsBy*` → `deleteBy*`/변경 동작)로 통일되어 있는지 확인. 같은 프로젝트 내 다른 Repository 파일과 비교해 순서가 다르면 지적. 특히 `save`가 어떤 파일은 맨 위, 다른 파일은 중간/아래에 있으면 일관성 위반.
- **step-down 함수 배치 (추상화 내림차순, 반복 지적 항목)**: 공개/entry 함수가 위, 그것이 호출하는 private helper 는 *아래*. 특히 **공유 helper 를 추출**할 때 호출자보다 위에 두는 'define-before-use' 습관을 flag한다. 호출자(들) 아래로 내려야 한다(여러 호출자가 공유하면 마지막 호출자 아래, 진짜 atomic 은 모듈 레벨). helper 를 신설/추출한 diff 는 반드시 배치를 확인한다. (Clean Code step-down rule)

## 5. YAGNI / 명시성 (Do Less, Be Explicit)

- **최소 변경 (drive-by refactor 금지)**: 요청 범위 밖 주변 코드를 같은 PR에서 리팩토링/재포매팅하지 않는다. 스코프 확대는 diff 오염·리뷰 부담·회귀 위험을 키운다. 개선점은 별도 이슈/PR로 분리 제안.
- **불필요한 default 값**: 모든 callsite가 명시적으로 값을 전달하는데 default가 있으면 제거 제안.
- **컬렉션 파라미터 nullable 여부**: `list[str] | None = None`이면 "빈 리스트와 None을 구분하는 니즈가 있는가?" 확인. 없으면 `list[str] = []`로 non-nullable 제안. 스칼라(`int`, `str`)는 `None` 허용.
- **Dead code**: diff에서 추가된 코드 중 사용되지 않는 것.
- **과도한 추상화**: 한 번만 쓰는 코드에 불필요한 패턴/레이어 적용.
- **필드 명시적 나열**: 동적 탐색보다 하드코딩이 안전한 경우.
- **호출 체인 내 중복 로직**: 호출부(caller)와 피호출부(callee)에서 동일한 검증/변환을 각각 수행하고 있으면, 한쪽에만 두고 다른 쪽을 제거 제안. 특히 caller가 값을 가공해서 넘기고 callee도 같은 가공을 하는 경우, callee에 로직을 두는 것이 모든 호출 경로를 커버하므로 일반적으로 우선.

## 6. 아키텍처 (Architecture)

- **에러 처리 계층**: infra vs usecase 레이어 분리. 에러 반환 vs 값 기반 분기.
- **설계 의도 일치**: secondary write가 primary 성공과 무관하게 실행되어야 하는지 등.
- **usecase 단계 순서 (validation → write → response)**: update/create usecase에서 stats 집계, display_* 응답 필드, 추가 조회 등 **response payload 조립은 repository가 반환한 updated/created 엔티티 기반**으로 수행. 입력 merged 엔티티로 응답을 만들면 DB trim/default/timestamp/validation 결과가 반영 안 되어 응답 신뢰도가 떨어진다. 순서: (1) validation (2) update/create (3) response 집계.
- **API 설계**: boolean 필드 과다 시 filter 구조체 통합, 중복 API.
- **패키지 구조**: 순환참조, 코드 위치 적절성.
- **레이어 배치 판단**: 코드가 올바른 레이어에 있는지. 판단 기준:
  - 맥락 독립적 규칙(어떤 상황에서든 성립) → domain
  - 맥락 의존적 규칙(특정 플로우에서만 적용) → application
  - DDD/Clean Architecture/Layered Architecture 기준: 의존성은 안쪽(domain)으로만 향하고, 바깥 레이어가 안쪽 레이어를 import. 역방향 금지.
- **OCP(개방-폐쇄 원칙)**: 요구사항 변경 시 기존 코드 수정 없이 새 코드 추가로 대응 가능한 구조인지. 의존성 방향이 뚜렷하고 레이어 경계가 분명한지.
- **기존 패턴과 충돌 시**: 이상적 구조(DDD, Clean Architecture, CQS, Hexagonal Architecture)를 먼저 제시하되, 기존 코드베이스 패턴을 Grep으로 확인하여 함께 보여준다. 판단은 사용자에게 위임.

## 7. 에러 핸들링 (Error Handling)

- **검증 위치 (경계에서만)**: 입력 검증은 시스템 경계(사용자 입력·외부 API 응답·역직렬화)에서 수행하고, 내부 코드는 검증된 값을 신뢰한다. 내부 함수마다 같은 값을 재검증하는 방어 코드는 잉여 → 경계로 끌어올린다. (cf. §5 호출 체인 내 중복 로직, review-language의 '방어 코드 제거')
- **에러 wrapping**: 레이어 경계에서 context 추가. `failed to` prefix 중복.
- **에러 타입 선택**: None 반환 vs 예외. 호출자가 디버깅하기 쉬운 쪽.
- **조건부 부작용**: if 안에서 외부 API 호출, DB 쓰기.
- **except 블록 직접 return**: `handle_exceptions` 같은 데코레이터에서 변수 할당 후 fall-through 대신 각 except 블록에서 직접 `return Response(...)`. 새 except 추가 시 변수 할당 누락으로 `UnboundLocalError` 발생 방지.
- **내부 에러 메시지 노출 금지**: `except Exception`에서 `str(e)`를 클라이언트 응답에 포함하지 않는다. DB 에러, 스택 정보 등 내부 구현이 노출된다. `'Internal Server Error'` 같은 고정 문자열 사용.
- **Unreachable 분기 처리 방식 맥락 분리**: 순수 함수(pure function)의 도달 불가 분기는 "안전한 fallback + '정상 경로 도달 불가' 주석"이 자연스러움. async handler/이벤트 핸들러/mutation 콜백의 invariant 위반은 `throw new Error('unreachable: ...')`로 즉시 노출해 관측 파이프라인으로 잡히게 할 것. silent return은 사용자 피드백 없이 사일런트 실패하므로 지적.
- **except 범위 최소화 (silent 흡수 함정)**: `try` 블록이 "그 예외를 의도한 한 줄"보다 넓으면, 같은 블록의 다른 단계가 같은 예외 타입을 던질 때 의도치 않게 흡수된다. 특히 rollback/cleanup 경로에서 `try: cancel(); close() except NotFound: pass`는 cancel이 NotFound로 실패해도 "정리 성공"으로 둔갑시켜 좀비 리소스를 silent 방치한다. `except`가 흡수해도 되는 정확한 호출만 내부 try로 감싸고, 나머지 단계의 예외는 밖으로 전파(escalate)시켜야 한다. 검증: "이 except가 잡는 예외를 try 안의 *모든* 호출이 던질 수 있나? 그 중 흡수하면 안 되는 게 있나?"

## 8. 관측성 (Observability)

- **로그 레벨**: error vs warn vs info 적절성.
- **로그 컨텍스트**: 에러 로그에 event_id, user_id 등 디버깅 정보 포함.
- **모니터링 유지**: sentry/metric 제거 시 대안.

## 9. 성능 (Performance)

- **N+1 쿼리**: 루프 안에서 DB 조회.
- **고트래픽 테이블**: 빈번 조회 테이블에 불필요한 컬럼 추가.
- **트랜잭션 범위**: 불필요하게 넓지 않은지. 읽기/쓰기 분리 가능 여부.
- **DB 타입 적절성**: Decimal vs int, PositiveIntegerField 등.

## 10. 테스팅 (Testing)

- **테스트 갭**: 새 코드패스에 테스트 없음.
- **과한/중복 테스트**: 같은 코드패스를 여러 테스트에서 검증.
- **형식적 검증**: expected 값이 전부 0/기본값이어서 양수값 동작 미검증.
- **테스트 데이터 정합성**: UTC↔KST 변환, GROUP BY 경계 등 expected가 로직에 맞는지 직접 계산.
- **flaky 위험 (CRITICAL)**: 실 스레드/executor 제출 후 즉시 단언, sleep 기반 대기, 시드 없는 랜덤/Faker 의존, now() 직접 호출, 테스트 간 순서 결합. 배경 실행은 동기 패치(autouse) + Event 대기 전용 테스트 분리 패턴인지 확인.

## 11. 운영 안전성 (Operations)

- **배포 순서**: 스키마 변경 → 코드 배포 순서. 하위 호환 배포.
- **장애 전파**: 일괄 적용 로직이 추후 문제 가능성.
- **레플리카/마스터 분리**: DB 쿼리가 올바른 DB 사용.
- **Merge 충돌 해결 후 코드 유실 확인**: `--theirs`/`--ours`로 충돌 해결 시, 해결된 파일에서 상대 브랜치의 의도된 변경이 누락되지 않았는지 확인. 특히 stacked PR에서 중간 PR merge 시 하위 PR의 코드가 사라질 수 있다.

## 출력 형식

각 카테고리별로:
```
### [카테고리명]: [PASS / N건 발견]
- [CRITICAL/INFO] file:line · 설명
```
발견 없으면 `PASS` 한 줄.
