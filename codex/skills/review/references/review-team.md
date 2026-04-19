# 전문 분야별 리뷰어 관점

diff를 **시니어 엔지니어의 전문 분야별 관점**으로 검증한다.
각 관점은 실제 PR 리뷰에서 반복적으로 나오는 패턴을 정리한 것이다.

---

## 인프라/대규모 설계 관점

- **레플리카/마스터 분리**: DB 쿼리가 올바른 DB를 사용하는지. 레플리카 fallback이 마스터를 죽일 수 있는지.
- **고트래픽 테이블 비대화**: 빈번 조회 테이블에 불필요한 컬럼/데이터 추가.
- **장애 전파 방지**: 일괄 적용 로직이 추후 맥락 모르는 사람이 작업 시 문제 가능성.
- **DynamoDB Limit+Filter**: Limit는 Filter 적용 전에 동작 → 빈 결과 반환 가능.

## 백엔드 엔지니어링 관점

- **에러 로그 레벨**: error vs warn vs info 적절성.
- **에러 메시지 컨텍스트**: 에러 로그에 event_id, user_id 등 디버깅 정보 포함.
- **에러 wrapping**: 레이어 경계에서 context 추가. `failed to` prefix 중복 방지.
- **API 설계**: boolean 과다 시 filter 구조체 통합, 중복 API.
- **네이밍 명확성**: "end date"보다 "latest end date among line items".
- **중복 로직 추출**: 유사 패턴 반복 → 함수 추출.
- **설계 의도 일치**: secondary write가 primary 성공과 무관하게 실행되어야 하는지.
- **명시성 우선**: default 값으로 버그가 silent하게 성공하지 않는지.
- **필드 명시적 나열**: 동적 탐색보다 하드코딩 (향후 필드 추가 시 의도치 않은 포함 방지).

## 플랫폼/동시성 관점

- **동시성**: non-idempotent 연산의 이중 실행 방지, 타임아웃.
- **트랜잭션 범위**: 불필요하게 넓지 않은지. 읽기/쓰기 분리.
- **DB 타입 적절성**: Decimal vs int, PositiveIntegerField 등 비즈니스 매칭.
- **정산/금액 정확성**: 소수점, 반올림, 통화 처리.

## 데이터/쿼리 관점

- **SQL 쿼리 논리 정합성**: JOIN 순서, GROUP BY/DISTINCT, 1:N 카운팅 중복.
- **데이터 정의 검증**: 쿼리 결과가 비즈니스 정의와 일치하는지.
- **Kafka**: consumer lag, micro-batch, batching 설정(linger.ms, batch.size) 적정성.

## 언어별 전문 관점

### Go
- **에러 래핑**: `fmt.Errorf("...: %w", err)` 패턴. `failed to` 중복.
- **nil/panic 방지**: 타입 단언 nil 체크, 인덱스 경계.
- **타임존 명시성**: `time.Now().UTC()`, 반환값 TZ 함수명 반영.
- **패키지 구조**: 순환참조 체크, 기존 코드 재사용.
- **Optional/nil 구분**: `*int32` vs `int32`, 컴파일타임 인터페이스 검증.

### Python
- **타입 안전성**: 타입 힌트 약화, `# type: ignore`, AI 생성 코드 가드.
- **enum**: char/string 대신 enum, classmethod vs staticmethod.
- **Optional**: 빈 컬렉션 가능하면 Optional 불필요, `from_*` 패턴.
- **관용구**: defaultdict vs setdefault, list vs set.
- **시간 계산**: off-by-one, async blocking.

### Java
- **Kafka Producer**: linger.ms, batch.size 점진적 튜닝.
- **설정값**: 하드코딩 → 환경변수.

## 도메인/비즈니스 관점

- **도메인 로직 정합성**: 코드가 실제 비즈니스 규칙 반영. 하드코딩 값이 합의된 것인지.
- **네이밍 = 도메인 의미**: verbose하더라도 목적이 드러나는 이름. 사용처와 불일치 지적.
- **운영 안전성**: staging 검증, 배포 모니터링, 마이그레이션 누락.
- **하위 호환성**: proto 하위호환성, 다른 팀 승인 필요성.
- **설계 적절성**: 과도한 추상화 vs 실용적 단순성.
- **관측성 유지**: sentry/metric 제거 시 대안, 공통 instrument 패턴.

---

## 출력 형식

각 관점별로 해당하는 이슈가 있으면:
```
### [관점명]: [N건 발견]
- [CRITICAL/INFO] file:line — 설명
```
해당 없으면: `### [관점명]: PASS`
