# 코드 공통 리뷰 기준

diff를 아래 카테고리별로 빠짐없이 검증한다.

`~/.claude/lib/coding/index.md`를 Read하고 그 목록에서 diff가 닿는 모듈을 Read해 이 기준에 더한다.

## 1. 보안

`~/.claude/lib/review/security-gate.md`를 Read하고 그 여섯 항목을 판정한다.

## 2. 정확성

- Enum/값 완전성: 새 enum 값 추가 시 모든 참조 위치에서 처리하는지. diff 외부 코드도 Grep으로 확인.
- 데이터 정의 검증: 쿼리 결과가 비즈니스 정의와 일치하는지 (클릭, 전환, 기여 인정 등)
- SQL 쿼리 논리: JOIN 순서, GROUP BY/DISTINCT, 1:N 카운팅 중복
- 시간 계산: floor/shift/ceil에서 off-by-one, 타임존 변환 경계
- 조건 분기 엣지케이스: start_date만 있고 end_date 없을 때, null/empty 구분

## 3. 계약 일관성

- 함수 시그니처 ↔ mock/fake 동기화: diff에서 함수 파라미터가 변경되면 테스트의 mock/fake를 Grep. `grep -rn "def mock_{함수명}\|def fake_{함수명}" tests/`
- dataclass/VO 필드 추가 시 수동 생성자 동기화: 기본값 없는 필드 추가 시 `grep -rn "ClassName(" tests/`로 수동 dict 구성 테스트 검색. 팩토리(`make_example`)는 자동이라 OK, 수동 dict만 위험.
- SELECT ↔ INSERT 컬럼 동기화: 같은 데이터를 SELECT하는 함수와 INSERT하는 함수가 별도인 경우, SELECT에 새 컬럼을 추가했으면 INSERT에도 반드시 추가. `generate_*()` 결과를 `_insert_*()` 로 넣는 패턴에서 특히 주의.
- 하위 호환성: 기존 동작이 깨지지 않는지. proto 필드 번호, 직렬화 형식.
- FE-BE 데이터 정합성: 응답 필드명/타입이 프론트 기대와 일치하는지.
- proto ↔ wire DTO (cmd) 필드 매핑: `MessageToDict(request) → Cmd(**dict)` spread 패턴 사용 시, proto 메시지의 필드 구조와 cmd DTO 의 필드명/타입이 정확히 일치해야 함. proto 가 nested object (`customer: CustomerDetail`) 인데 cmd 가 lookup key (`customer_name: str`) 면 pydantic `extra='ignore'` 기본값 때문에 silent drop. 특히 proto + cmd 가 별도 PR/publish 일 때 publish 순서 의존성을 PR description 에 머지 차단 조건으로 명시.

## 4. 클린 코드 / 네이밍

- `~/.claude/lib/coding/clean-code.md`와 `~/.claude/lib/coding/simple-design.md`의 Abstraction discipline으로 판정한다.

## 5. YAGNI / 명시성

- 최소 변경: 요청 범위 밖 주변 코드를 같은 PR에서 리팩토링/재포매팅했으면 지적하고, 개선점은 별도 이슈/PR로 분리 제안.
- Dead code: diff에서 추가된 코드 중 사용되지 않는 것.
- 과도한 추상화: 한 번만 쓰는 코드에 불필요한 패턴/레이어 적용.
- 필드 명시적 나열: 동적 탐색보다 하드코딩이 안전한 경우.
- 호출 체인 내 중복 로직: caller 와 callee 에서 동일한 검증/변환을 각각 수행하고 있으면, 한쪽에만 두고 다른 쪽을 제거 제안. 특히 caller가 값을 가공해서 넘기고 callee도 같은 가공을 하면 callee 쪽에 남긴다.

## 6. 아키텍처

- 에러 처리 계층: infra vs usecase 레이어 분리. 에러 반환 vs 값 기반 분기.
- 설계 의도 일치: secondary write가 primary 성공과 무관하게 실행되어야 하는지 등.
- usecase 단계 순서: update/create usecase에서 stats 집계, display_* 응답 필드, 추가 조회 등 response payload 조립은 repository가 반환한 updated/created 엔티티 기반으로 수행. 순서: validation → update/create → response 집계.
- API 설계: boolean 필드 과다 시 filter 구조체 통합, 중복 API.
- 패키지 구조: 순환참조, 코드 위치 적절성.

## 7. 에러 핸들링

- 에러 wrapping: 레이어 경계에서 context 추가. `failed to` prefix 중복.
- 조건부 부작용: if 안에서 외부 API 호출, DB 쓰기.
- except 블록 직접 return: `handle_exceptions` 같은 데코레이터에서 변수 할당 후 fall-through 대신 각 except 블록에서 직접 `return Response(...)`.
- except 범위 최소화: `try` 블록이 "그 예외를 의도한 한 줄"보다 넓으면, 같은 블록의 다른 단계가 같은 예외 타입을 던질 때 의도치 않게 흡수된다. 특히 rollback/cleanup 경로에서 `try: cancel(); close() except NotFound: pass`는 cancel이 NotFound로 실패해도 "정리 성공"으로 둔갑시켜 좀비 리소스를 silent 방치한다. `except`가 흡수해도 되는 정확한 호출만 내부 try로 감싸고, 나머지 단계의 예외는 밖으로 escalate시켜야 한다. 검증: "이 except가 잡는 예외를 try 안의 모든 호출이 던질 수 있나? 그 중 흡수하면 안 되는 게 있나?"

## 8. 관측성

- 로그 레벨: error vs warn vs info 적절성.
- 로그 컨텍스트: 에러 로그에 event_id, user_id 등 디버깅 정보 포함.
- 모니터링 유지: sentry/metric 제거 시 대안.

## 9. 성능

- N+1 쿼리: 루프 안에서 DB 조회.
- 고트래픽 테이블: 빈번 조회 테이블에 불필요한 컬럼 추가.
- 트랜잭션 범위: 불필요하게 넓지 않은지. 읽기/쓰기 분리 가능 여부.
- DB 타입 적절성: Decimal vs int, PositiveIntegerField 등.

## 10. 테스팅

- 테스트 갭: 새 코드패스에 테스트 없음.
- 과한/중복 테스트: 같은 코드패스를 여러 테스트에서 검증.
- 형식적 검증: expected 값이 전부 0/기본값이어서 양수값 동작 미검증.
- 테스트 데이터 정합성: UTC↔KST 변환, GROUP BY 경계 등 expected가 로직에 맞는지 직접 계산.

## 11. 운영 안전성

- 배포 순서: 스키마 변경 → 코드 배포 순서. 하위 호환 배포.
- 장애 전파: 일괄 적용 로직이 추후 문제 가능성.
- 레플리카/마스터 분리: DB 쿼리가 올바른 DB 사용.
- Merge 충돌 해결 후 코드 유실 확인: `--theirs`/`--ours`로 충돌 해결 시, 해결된 파일에서 상대 브랜치의 의도된 변경이 누락되지 않았는지 확인. stacked PR에서 중간 PR을 merge했으면 하위 PR 코드까지 확인한다.

## 출력 형식

각 카테고리별로:
```
### [카테고리명]: [PASS / N건 발견]
- [CRITICAL/INFO] file:line · 설명
```
발견 없으면 `PASS` 한 줄.
