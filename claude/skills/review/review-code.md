# 코드 공통 리뷰 기준

diff를 아래 카테고리별로 빠짐없이 검증한다. 각 항목에 해당 여부를 명시적으로 판단하고, 해당 시 파일:라인을 인용한다.

## 1. 보안 (Security)

- **SQL 인젝션**: raw SQL에 문자열 보간(`f"..."`, `%s` 아닌 `.format()`) 사용 여부
- **Race condition**: 공유 상태 동시 접근, 락 누락, non-idempotent 연산의 이중 실행

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

## 3-1. 반환 타입 정확성 (Return Type Safety)

- **update/delete에서 None 반환 금지**: 존재해야 하는 데이터가 없으면 None이 아닌 도메인 예외(`NotFound`) 발생. None 반환은 "성공했는데 사라짐" vs "실패" 구분 불가, silent failure 위험.
- **find/search에서 None 반환 허용**: 없을 수 있는 조회는 None OK.
- **구분 기준**: 호출자가 "없을 수 있다"고 예상하면 None, "있어야 한다"가 전제면 예외.

## 4. 클린 코드 / 네이밍 (Clean Code)

- **용어 일관성**: 같은 개념에 다른 단어 (`alternative` vs `substitute`). 기존 코드베이스 용어와 일치.
- **네이밍 명확성**: 변수/함수명이 동작을 정확히 설명하는지. 모델 필드명과 DB 컬럼명 일치.
- **매직 넘버**: 하드코딩된 값. 상수로 추출 필요 여부.
- **중복 로직**: 유사 패턴 반복 시 함수 추출 제안 (DRY).
- **인터페이스 메서드 순서 일관성**: Repository/Port 인터페이스는 **CRUD 순서**(`save` → `findBy*`/`findAll*` → `countBy*` → `existsBy*` → `deleteBy*`/변경 동작)로 통일되어 있는지 확인. 같은 프로젝트 내 다른 Repository 파일과 비교해 순서가 다르면 지적. 특히 `save`가 어떤 파일은 맨 위, 다른 파일은 중간/아래에 있으면 일관성 위반.

## 5. YAGNI / 명시성 (Do Less, Be Explicit)

- **불필요한 default 값**: 모든 callsite가 명시적으로 값을 전달하는데 default가 있으면 제거 제안.
- **컬렉션 파라미터 nullable 여부**: `list[str] | None = None`이면 "빈 리스트와 None을 구분하는 니즈가 있는가?" 확인. 없으면 `list[str] = []`로 non-nullable 제안. 스칼라(`int`, `str`)는 `None` 허용.
- **Dead code**: diff에서 추가된 코드 중 사용되지 않는 것.
- **과도한 추상화**: 한 번만 쓰는 코드에 불필요한 패턴/레이어 적용.
- **필드 명시적 나열**: 동적 탐색보다 하드코딩이 안전한 경우.
- **호출 체인 내 중복 로직**: 호출부(caller)와 피호출부(callee)에서 동일한 검증/변환을 각각 수행하고 있으면, 한쪽에만 두고 다른 쪽을 제거 제안. 특히 caller가 값을 가공해서 넘기고 callee도 같은 가공을 하는 경우 — callee에 로직을 두는 것이 모든 호출 경로를 커버하므로 일반적으로 우선.

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

- **에러 wrapping**: 레이어 경계에서 context 추가. `failed to` prefix 중복.
- **에러 타입 선택**: None 반환 vs 예외 — 호출자가 디버깅하기 쉬운 쪽.
- **조건부 부작용**: if 안에서 외부 API 호출, DB 쓰기.
- **except 블록 직접 return**: `handle_exceptions` 같은 데코레이터에서 변수 할당 후 fall-through 대신 각 except 블록에서 직접 `return Response(...)`. 새 except 추가 시 변수 할당 누락으로 `UnboundLocalError` 발생 방지.
- **내부 에러 메시지 노출 금지**: `except Exception`에서 `str(e)`를 클라이언트 응답에 포함하지 않는다. DB 에러, 스택 정보 등 내부 구현이 노출된다. `'Internal Server Error'` 같은 고정 문자열 사용.
- **Unreachable 분기 처리 방식 맥락 분리**: 순수 함수(pure function)의 도달 불가 분기는 "안전한 fallback + '정상 경로 도달 불가' 주석"이 자연스러움. async handler/이벤트 핸들러/mutation 콜백의 invariant 위반은 `throw new Error('unreachable: ...')`로 즉시 노출해 관측 파이프라인으로 잡히게 할 것. silent return은 사용자 피드백 없이 사일런트 실패하므로 지적.

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

## 11. 운영 안전성 (Operations)

- **배포 순서**: 스키마 변경 → 코드 배포 순서. 하위 호환 배포.
- **장애 전파**: 일괄 적용 로직이 추후 문제 가능성.
- **레플리카/마스터 분리**: DB 쿼리가 올바른 DB 사용.
- **Merge 충돌 해결 후 코드 유실 확인**: `--theirs`/`--ours`로 충돌 해결 시, 해결된 파일에서 상대 브랜치의 의도된 변경이 누락되지 않았는지 확인. 특히 stacked PR에서 중간 PR merge 시 하위 PR의 코드가 사라질 수 있다.

## 출력 형식

각 카테고리별로:
```
### [카테고리명]: [PASS / N건 발견]
- [CRITICAL/INFO] file:line — 설명
```
발견 없으면 `PASS` 한 줄.
