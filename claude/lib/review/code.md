## 1. 보안

`~/.claude/lib/review/security-gate.md`를 Read하고 그 항목을 판정한다.

## 2. 정확성

- Enum 필요성·완전성: `~/.claude/lib/coding/types.md`의 기준으로 값 자체의 의미가 있는지, 판정 → enum → 재분기가 불필요한지 생산자부터 소비자까지 확인한다. 새 enum 값 추가 시 diff 밖의 모든 참조 위치도 확인한다.
- 데이터 정의: 쿼리는 비즈니스 정의(클릭, 전환, 기여 인정)와 같은 조건으로 센다.
- SQL 쿼리 논리: JOIN 순서, GROUP BY/DISTINCT, 1:N 카운팅 중복
- 시간 계산: floor/shift/ceil과 타임존 변환은 구간 경계에서 하루·한 칸 어긋나지 않게 계산한다.
- 조건 분기: 한쪽 값만 있는 경우(start_date만 있고 end_date가 없음)와 null·빈 값을 나눠 처리한다.

## 3. 계약 일관성

- 함수 시그니처 ↔ mock/fake 동기화: diff에서 함수 파라미터가 변경되면 테스트의 mock/fake를 Grep. `grep -rn "def mock_{함수명}\|def fake_{함수명}" tests/`
- dataclass/VO 필드 추가 시 수동 생성자 동기화: 기본값 없는 필드 추가 시 `grep -rn "ClassName(" tests/`로 수동 dict 구성 테스트 검색. 빠진 필드를 자동으로 채우는 테스트 팩토리는 새 필드도 채우고 수동 dict만 깨진다.
- SELECT ↔ INSERT 컬럼 동기화: 같은 데이터를 SELECT하는 함수와 INSERT하는 함수가 별도인 경우, SELECT에 새 컬럼을 추가했으면 INSERT에도 추가. SELECT하는 함수의 결과를 테이블을 비우고 INSERT하는 함수로 넣는 패턴이 이 경우다.
- 하위 호환성: `~/.claude/lib/coding/tests.md`를 Read하고 proto 필드 번호와 그 Refactoring equivalence가 꼽는 계약을 변경 전후로 비교한다.
- FE-BE 데이터 정합성: 응답 필드명/타입이 프론트 기대와 일치하는지.
- proto ↔ cmd DTO 필드 매핑: `MessageToDict(request) → Cmd(**dict)` spread 패턴 사용 시, proto 메시지의 필드 구조와 cmd DTO 의 필드명/타입이 정확히 일치해야 함. proto 가 nested object (`customer: CustomerDetail`) 인데 cmd 가 lookup key (`customer_name: str`) 면 pydantic `extra='ignore'` 기본값에서 silent drop. proto + cmd 가 별도 PR/publish 일 때 publish 순서 의존성을 PR 본문에 머지 차단 조건으로 명시.

## 4. Simple Design / 네이밍

- `~/.claude/lib/coding/functions.md`·`~/.claude/lib/coding/file-layout.md`·`~/.claude/lib/coding/comments.md`·`~/.claude/lib/coding/naming.md`와 `~/.claude/lib/coding/design.md`의 DRY of knowledge·Abstraction discipline을 Read하고 그 규칙으로 판정한다.

## 5. YAGNI / 명시성

- 최소 변경: 요청 범위 밖 주변 코드의 리팩토링·재포매팅은 같은 PR 대신 별도 이슈나 PR로 낸다.
- 필드 명시적 나열: 동적 탐색보다 하드코딩이 안전한 경우.
- 호출 체인 내 중복 로직: caller와 callee가 같은 검증·변환을 각각 하면 한쪽에만 둔다. caller가 값을 가공해 넘기고 callee도 같은 가공을 하면 callee 쪽에 남긴다.

## 6. 아키텍처

- 타입·규칙 소유권과 위치: `~/.claude/lib/coding/architecture.md`(Layers 절, What a use case holds, Business rules in the domain)와 `~/.claude/lib/coding/domain.md`를 Read하고 그 기준으로 판정하며, 순환 참조가 생기지 않는지 본다.
- 설계 의도 일치: secondary write가 primary 성공과 무관하게 실행되어야 하는지 등.
- API 설계: boolean 필드 과다 시 filter 구조체 통합, 중복 API.

## 7. 에러 핸들링

- 에러 처리: `~/.claude/lib/coding/errors.md`를 Read하고 Exception ownership·Handling policy·Failure representation으로 판정하며, 위치 이동으로 domain → application 역방향 의존이 생기지 않는지 본다.
- 조건부 부작용: if 안에서 외부 API 호출, DB 쓰기.
- except 범위 최소화: `try` 블록이 그 예외를 의도한 한 줄보다 넓으면, 같은 블록의 다른 단계가 같은 예외 타입을 던질 때 의도치 않게 흡수된다. rollback/cleanup 경로에서 `try: cancel(); close() except NotFound: pass`는 cancel이 NotFound로 실패해도 정리 성공으로 둔갑시켜 좀비 리소스를 silent 방치한다. `except`가 흡수해도 되는 정확한 호출만 내부 try로 감싸고, 나머지 단계의 예외는 밖으로 escalate시켜야 한다. 검증: "이 except가 잡는 예외를 try 안의 모든 호출이 던질 수 있나? 그 중 흡수하면 안 되는 게 있나?"

## 8. 관측성

- 로그 레벨: error vs warn vs info 적절성.
- 모니터링 유지: sentry/metric 제거 시 대안.
- 루프 안에서 항목마다 남기는 debug 로그는 머지 전에 지운다.
- info 로그에 `[DEBUG]` 같은 접두어가 붙어 있으면, 테스트용이면 지우고 아니면 debug 레벨로 바꾼다.
- 기존 로그에 샘플링이 걸려 있으면 같은 종류의 로그를 새로 남기는 곳에도 같은 샘플링을 건다.
- 한 사건은 여러 줄로 나누는 대신 한 줄 로그에 필드로 묶고, 요청 추적 id(`correlation_id`)와 대상 id(`event_id`, `user_id`)를 넣는다.
- 새 메트릭 이름은 같은 대상을 재는 기존 메트릭의 단어와 단어 순서를 따른다(기존이 `daily_total`이면 `total_daily` 대신 `daily_` 꼴).
- 기존 메트릭과 같은 값을 재야 하면 새 메트릭 대신 기존 메트릭을 쓴다.
- 새 메트릭을 더하면 그 메트릭을 볼 알람이나 대시보드를 PR에 적는다.
- 메트릭 라벨에는 사용자 id·요청 id처럼 끝없이 늘어나는 값 대신 값 종류가 정해진 값(상태, 종류)을 넣는다.
- 새로 만든 배치, consumer, 다른 시스템 호출에는 성공·실패 수를 재는 메트릭을 단다.

## 9. 성능

- N+1 쿼리: 측정된 병목이 있는 경로에서는 루프가 쓰는 행을 루프 앞에서 한 번에 조회한다.
- 고트래픽 테이블: 빈번 조회 테이블에 불필요한 컬럼 추가.
- 트랜잭션 범위: 불필요하게 넓지 않은지. 읽기/쓰기 분리 가능 여부.
- DB 타입: 컬럼 타입은 담을 값의 범위·정밀도에 맞춘다(Decimal vs int, PositiveIntegerField).
- 루프 안에서 매번 같은 값을 내는 계산은 루프 밖으로 옮긴다.
- 메모리에서 정렬·필터하는 목록이나 범위 조회는 건수 상한을 코드에 두거나, 운영에서 들어올 최대 건수를 PR에 적는다.
- 페이지마다 같은 집계를 다시 계산하는 대신 서버가 한 번 계산해 돌려준다.

## 10. 테스팅

- 테스트 규칙: `~/.claude/lib/coding/tests.md`의 Cover the change·Dedup and shared setup·Refactoring equivalence로 판정한다.
- 형식적 검증: expected 값에 0·기본값이 아닌 값을 넣어 양수값 동작까지 확인한다.
- 테스트 데이터 정합성: expected는 UTC↔KST 변환·GROUP BY 경계를 직접 계산해 로직과 맞춘다.
- 집계 코드를 바꾸면 빈 입력과 기간 경계(월 합계가 일 합계의 합과 같은지)를 확인하는 테스트를 둔다.
- 테스트는 호출 여부만 확인하는 대신 이름이나 docstring이 약속한 결과를 assert로 확인한다.
- 테스트는 결과를 인덱스(`result[0]`) 대신 id로 찾아 확인한다.
- 테스트 형식(함수별 테스트, 표 기반 테스트)은 그 파일이 이미 쓰는 형식을 따른다.

## 11. 운영 안전성

- 배포 순서: 스키마 변경을 코드보다 먼저 배포하고, 각 배포가 직전 버전과 함께 돌도록 하위 호환을 지킨다.
- 레플리카/마스터 분리: DB 쿼리가 올바른 DB 사용.
- Merge 충돌 해결 후 코드 유실 확인: `--theirs`/`--ours`로 충돌 해결 시, 해결된 파일에서 상대 브랜치의 의도된 변경이 누락되지 않았는지 확인. stacked PR에서 중간 PR을 merge했으면 하위 PR 코드까지 확인한다.
- 다른 서비스의 변경이 있어야 동작하는 diff면 그 서비스의 PR과 배포 순서(서버 → 게이트웨이 → 화면)를 PR 본문에 적는다.
- 공유 API 스펙 패키지의 버전을 바꾸면 스펙 저장소의 짝 PR을 함께 낸다.
- 여러 유형(상품 종류, 매체 종류)의 동작을 바꿀 때는 한 번에 바꾸는 대신 유형별로 나누거나 비율을 정해 차례로 적용한다.
- 배포 설정의 서비스 이름·환경 값은 PR이 바꾸려는 대상과 같게 쓴다.

## 출력 형식

각 카테고리별로:
```
### [카테고리명]: [PASS / 해당 없음 / N건 발견]
- [CRITICAL/INFO] file:line · 설명
```
발견이 없으면 `PASS`, 이 diff와 무관한 카테고리면 `해당 없음` 한 줄.

설명은 `~/Downloads/Obsidian Vault/Simple Design.md` 4절대로 쓴다.
