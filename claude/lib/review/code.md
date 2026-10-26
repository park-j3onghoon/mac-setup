diff를 아래 카테고리별로 빠짐없이 검증한다.

`~/.claude/lib/coding/index.md`를 Read하고 그 목록에서 diff가 닿는 모듈을 Read해 이 기준에 더한다.

## 1. 보안

`~/.claude/lib/review/security-gate.md`를 Read하고 그 항목을 판정한다.

## 2. 정확성

- Enum 필요성·완전성: `~/.claude/lib/coding/types.md`의 기준으로 값 자체의 의미가 있는지, 판정 → enum → 재분기가 불필요한지 생산자부터 소비자까지 확인한다. 새 enum 값 추가 시 diff 밖의 모든 참조 위치도 확인한다.
- 데이터 정의 검증: 쿼리 결과가 비즈니스 정의와 일치하는지 (클릭, 전환, 기여 인정 등)
- SQL 쿼리 논리: JOIN 순서, GROUP BY/DISTINCT, 1:N 카운팅 중복
- 시간 계산: floor/shift/ceil에서 off-by-one, 타임존 변환 경계
- 조건 분기 엣지케이스: start_date만 있고 end_date 없을 때, null/empty 구분

## 3. 계약 일관성

- 함수 시그니처 ↔ mock/fake 동기화: diff에서 함수 파라미터가 변경되면 테스트의 mock/fake를 Grep. `grep -rn "def mock_{함수명}\|def fake_{함수명}" tests/`
- dataclass/VO 필드 추가 시 수동 생성자 동기화: 기본값 없는 필드 추가 시 `grep -rn "ClassName(" tests/`로 수동 dict 구성 테스트 검색. 빠진 필드를 자동으로 채우는 테스트 팩토리는 새 필드도 채우고 수동 dict만 깨진다.
- SELECT ↔ INSERT 컬럼 동기화: 같은 데이터를 SELECT하는 함수와 INSERT하는 함수가 별도인 경우, SELECT에 새 컬럼을 추가했으면 INSERT에도 추가. SELECT하는 함수의 결과를 테이블을 비우고 INSERT하는 함수로 넣는 패턴이 이 경우다.
- 하위 호환성: proto 필드 번호뿐 아니라 응답 enum 값, 직렬화, 저장된 식별자·검증 토큰·서명과 오류 조건도 비교한다. 파일 이동·타입 변경을 이유로 동작 불변을 가정하지 않고, 승인된 계약 변경은 보존한 동작과 분리해 적는다.
- FE-BE 데이터 정합성: 응답 필드명/타입이 프론트 기대와 일치하는지.
- proto ↔ cmd DTO 필드 매핑: `MessageToDict(request) → Cmd(**dict)` spread 패턴 사용 시, proto 메시지의 필드 구조와 cmd DTO 의 필드명/타입이 정확히 일치해야 함. proto 가 nested object (`customer: CustomerDetail`) 인데 cmd 가 lookup key (`customer_name: str`) 면 pydantic `extra='ignore'` 기본값에서 silent drop. proto + cmd 가 별도 PR/publish 일 때 publish 순서 의존성을 PR 본문에 머지 차단 조건으로 명시.

## 4. 클린 코드 / 네이밍

- `~/.claude/lib/coding/functions.md`·`~/.claude/lib/coding/file-layout.md`·`~/.claude/lib/coding/comments.md`·`~/.claude/lib/coding/naming.md`와 `~/.claude/lib/coding/design.md`의 DRY of knowledge·Abstraction discipline을 Read하고 그 규칙으로 판정한다.

## 5. YAGNI / 명시성

- 최소 변경: 요청 범위 밖 주변 코드의 리팩토링·재포매팅은 같은 PR 대신 별도 이슈나 PR로 낸다.
- Dead code: diff에서 추가된 코드 중 사용되지 않는 것.
- 과도한 추상화: 한 번만 쓰는 코드에 불필요한 패턴/레이어 적용.
- 필드 명시적 나열: 동적 탐색보다 하드코딩이 안전한 경우.
- 호출 체인 내 중복 로직: caller와 callee가 같은 검증·변환을 각각 하면 한쪽에만 둔다. caller가 값을 가공해 넘기고 callee도 같은 가공을 하면 callee 쪽에 남긴다.

## 6. 아키텍처

- 타입·규칙 소유권: `~/.claude/lib/coding/architecture.md`·`~/.claude/lib/coding/domain.md`의 의미 기준으로 domain의 업무 규칙과 application의 요청·실행 옵션·작업 결과를 구분한다. 불변성·순수성·공유 여부만으로 domain으로 옮기지 않으며, 도메인 계산은 기존 entity/value object의 책임인지 먼저 본다.
- 에러 처리 레이어: 실패한 규칙과 예외의 소유자가 같은지, 별도로 어느 usecase가 잡아 어떤 정책으로 처리하는지 `~/.claude/lib/coding/errors.md` 기준으로 확인한다. 위치 이동으로 domain → application 역방향 의존이 생기지 않는지 본다.
- 설계 의도 일치: secondary write가 primary 성공과 무관하게 실행되어야 하는지 등.
- API 설계: boolean 필드 과다 시 filter 구조체 통합, 중복 API.
- 패키지 구조: 순환참조. 코드 위치는 `~/.claude/lib/coding/architecture.md`를 Read하고 그 레이어 규칙으로 판정한다.

## 7. 에러 핸들링

- 에러 wrapping: 필요한 경우에만 구체적인 domain·port 예외에 안전한 usecase 맥락을 추가하고 원래 원인·식별 정보를 보존하는지 본다. transport 상태 변환은 presentation에 두고, 중복 `failed to` prefix나 원인을 잃는 boolean·기본값 변환을 확인한다.
- 조건부 부작용: if 안에서 외부 API 호출, DB 쓰기.
- except 범위 최소화: `try` 블록이 그 예외를 의도한 한 줄보다 넓으면, 같은 블록의 다른 단계가 같은 예외 타입을 던질 때 의도치 않게 흡수된다. rollback/cleanup 경로에서 `try: cancel(); close() except NotFound: pass`는 cancel이 NotFound로 실패해도 정리 성공으로 둔갑시켜 좀비 리소스를 silent 방치한다. `except`가 흡수해도 되는 정확한 호출만 내부 try로 감싸고, 나머지 단계의 예외는 밖으로 escalate시켜야 한다. 검증: "이 except가 잡는 예외를 try 안의 모든 호출이 던질 수 있나? 그 중 흡수하면 안 되는 게 있나?"

## 8. 관측성

- 로그 레벨: error vs warn vs info 적절성.
- 로그 컨텍스트: 에러 로그에 event_id, user_id 등 디버깅 정보 포함.
- 모니터링 유지: sentry/metric 제거 시 대안.

## 9. 성능

- N+1 쿼리: 루프 안에서 DB 조회.
- 고트래픽 테이블: 빈번 조회 테이블에 불필요한 컬럼 추가.
- 트랜잭션 범위: 불필요하게 넓지 않은지. 읽기/쓰기 분리 가능 여부.
- DB 타입: 값의 범위·정밀도에 맞는 타입인지. Decimal vs int, PositiveIntegerField 등.

## 10. 테스팅

- 테스트 갭: 새 코드패스에 테스트 없음.
- 과한/중복 테스트: 같은 코드패스를 여러 테스트에서 검증.
- 형식적 검증: expected 값이 전부 0/기본값이면 양수값 동작 미검증.
- 테스트 데이터 정합성: UTC↔KST 변환, GROUP BY 경계 등 expected가 로직에 맞는지 직접 계산.
- 리팩터링 동작 보존: `~/.claude/lib/coding/tests.md`의 동작 보존 기준으로 변경 전후 검증 근거를 확인한다. 테스트 통과와 동작 동일성을 구분하고, 승인된 변경·미확인 범위를 따로 적는다.

## 11. 운영 안전성

- 배포 순서: 스키마 변경 → 코드 배포 순서. 하위 호환 배포.
- 장애 전파: 일괄 적용 로직이 추후 문제 가능성.
- 레플리카/마스터 분리: DB 쿼리가 올바른 DB 사용.
- Merge 충돌 해결 후 코드 유실 확인: `--theirs`/`--ours`로 충돌 해결 시, 해결된 파일에서 상대 브랜치의 의도된 변경이 누락되지 않았는지 확인. stacked PR에서 중간 PR을 merge했으면 하위 PR 코드까지 확인한다.

## 출력 형식

각 카테고리별로:
```
### [카테고리명]: [PASS / 해당 없음 / N건 발견]
- [CRITICAL/INFO] file:line · 설명
```
발견이 없으면 `PASS`, 이 diff와 무관한 카테고리면 `해당 없음` 한 줄.
