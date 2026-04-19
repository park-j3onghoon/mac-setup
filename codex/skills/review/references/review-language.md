# 언어별 공통 리뷰 기준

diff의 변경된 파일 언어를 감지하여 해당 언어의 관용구, 안전성, 플랫폼 특화 이슈를 검증한다.
**해당 언어 파일이 diff에 없으면 해당 섹션을 건너뛴다.**

---

## Python

### 타입 안전성
- 타입 힌트가 약해지지 않았는지 (`Any` 추가, 구체 타입 → Union 등)
- `dict` 대신 `dataclass`, `NamedTuple` 사용 권장
- `# type: ignore` 추가 시 이유가 명확한지
- `Optional` 남용: 기본값으로 빈 컬렉션 사용 가능하면 Optional 불필요
- enum: char/string 필드보다 enum으로 잘못된 입력 방지

### 관용구
- `defaultdict` vs `setdefault` 적절한 선택
- `list` 대신 `set` (집합 연산 시)
- 팩토리 메서드는 `from_*` 패턴 선호

### 리소스/안전성
- cursor.close() 누락, context manager 오용
- 에러 타입: None 반환 vs ValueError — 호출자 디버깅 용이성
- Redis cluster mode에서 서로 다른 slot 조회 불가
- 시간 계산 off-by-one: `floor`/`shift` 경계값 오류

### Django 특화
- ORM `.annotate()` 에 새 필드 추가 시, 결과 dict 키와 dataclass 필드 일치 확인
- migration 파일 누락 / 순서 오류
- `PositiveIntegerField` vs `BigIntegerField` 등 타입 적절성

---

## Go

### 에러 핸들링
- 레이어 경계에서 `fmt.Errorf("...: %w", err)` 패턴 사용
- `failed to` prefix 불필요 중복

### 안전성
- 타입 단언(`ret.Get(0).(*Type)`) 시 nil 체크
- 인덱스 경계 검사
- `*int32` vs `int32`, nil/zero-value 명확 구분
- 컴파일 타임 인터페이스 검증: `var _ Interface = (*Impl)(nil)`

### 관용구
- context 기반 logger 사용
- interface 분리 (ISP)
- `time.Now().UTC()` 명시

### 패키지/구조
- 패키지 간 순환참조 여부
- 기존 코드/라이브러리 재사용 확인

### 인프라 특화
- Kafka: consumer lag, micro-batch, `read_committed` 필요성
- DynamoDB `Limit + FilterExpression`: Limit가 Filter 적용 전에 동작
- proto 하위호환성: gen-go 버전 불일치, 직렬화 번호 변경

---

## Java

### Kafka
- `linger.ms`, `batch.size` 등 batching 설정 적정성

### 설정
- 하드코딩된 설정값은 환경변수로 관리

---

## Kotlin / Spring Boot

### null safety
- `!!` 사용 금지, `?.let` / `?:` / `requireNotNull` 활용
- data class 불변성, copy() 활용
- `@field:NotBlank` 등 어노테이션 정확한 target 지정
- sealed class/interface로 타입 안전 분기

---

## Frontend (JavaScript/TypeScript/Vue/React)

### React
- useEffect 의존성 배열 누락 → Maximum update depth 에러
- 상태 업데이트 batching 이해

### 안전성
- sessionStorage/localStorage: SSR 환경에서 접근 가능한지
- dateRange 검증: start_date/end_date 중 하나만 있을 때 엣지케이스
- API 실패 시 UI 상태 동기화

### 컨벤션
- 새 Vue 컴포넌트는 Composition API (script setup)
- 절대 경로 우선 (path alias 사용)
- 파일 이동 시 import 경로 유효성 + 빌드 검증 필수

---

## 출력 형식

```
### [언어]: [PASS / N건 발견]
- [CRITICAL/INFO] file:line — 설명
```
해당 언어 파일이 diff에 없으면: `[언어]: 해당 없음`
