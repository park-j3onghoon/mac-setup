# 언어별 공통 리뷰 기준

diff의 변경된 파일 언어를 감지하여 해당 언어의 관용구, 안전성, 플랫폼 특화 이슈를 검증한다.
해당 언어 파일이 diff에 없으면 해당 섹션을 건너뛴다.
diff에 Python·프론트엔드·DB 파일이 있으면 `~/.claude/lib/coding-rules-python.md`·`coding-rules-frontend.md`·`coding-rules-db.md` 중 해당 파일을 Read하고 이 기준에 더한다.

---

## Python

### 타입 안전성
- 타입 힌트가 약해지지 않았는지 (`Any` 추가, 구체 타입 → Union 등)
- `dict` 대신 `dataclass`, `NamedTuple` 사용 권장
- `# type: ignore` 추가 시 이유가 명확한지
- enum: char/string 필드보다 enum으로 잘못된 입력 방지
- `classmethod` vs `staticmethod` 구분 (클래스 연관성 기준)
- 신규 `.py` 는 `from __future__ import annotations` 선언.

### 관용구
- `defaultdict` vs `setdefault` 적절한 선택
- `list` 대신 `set` (집합 연산 시)
- 팩토리 메서드는 `from_*` 패턴 선호
- Forward Reference 이유 이해

### 리소스/안전성
- cursor.close() 누락, context manager 오용
- Redis cluster mode에서 서로 다른 slot 조회 불가 → hashtag 또는 단일 key
- Redis TTL 설정 누락
- async wrapping으로 commit blocking 방지

### Django 특화
- ORM `.annotate()` 에 새 필드 추가 시, 결과 dict 키와 dataclass 필드 일치 확인
- migration 파일 누락 / 순서 오류
- `PositiveIntegerField` vs `BigIntegerField` 등 타입 적절성
- `.iterator()`는 무거운 엔티티를 대량 스캔하며 스트림으로 소비할 때만 쓴다. 결과를 바로 `list()`로 만들거나 청크로 바운드된 가벼운 projection(`values_list`)에 붙은 `.iterator()`는 지적한다.

### 스타일 / 복잡도
- early return 으로 중첩 해소: 함수 내 들여쓰기 3단계 이내
- 함수당 분기 5개 이하. 초과 시 헬퍼로 분리
- `os.path` 대신 `pathlib`
- bare `except:` 금지: 구체 예외만 catch
- 1회성 로직에 ABC/Protocol 도입 지양

---

## Go

### 에러 핸들링
- 레이어 경계에서 `fmt.Errorf("...: %w", err)` 패턴 사용
- 다중 에러 체인은 `fmt.Errorf("%w: %w", e1, e2)` 또는 `errors.Join(...)`으로 묶는다. 재시도 제어가 필요하면 `skipRetry` 등 제어용 에러를 join.
- 비핵심 I/O(postback·enrichment 등) 에러를 `log.Warnf`로 기록하고 계속 진행하는 패턴은 정상으로 본다.
- `failed to` prefix 불필요 중복
- 에러 체크 일관성

### 안전성
- 타입 단언(`ret.Get(0).(*Type)`) 시 nil 체크
- 인덱스 경계 검사 (`tokens length check`)
- 형변환 실패 시 panic 가능성
- `*int32` vs `int32`, `optional` proto field로 nil/zero-value 명확 구분
- 컴파일 타임 인터페이스 검증: `var _ Interface = (*Impl)(nil)`
- 방어 코드 제거: 빌드타임에 보장되는 nil 체크·생성자가 보장하는 invariant·도달 불가 경로의 방어 코드, `sync.Once`와 `init()`을 함께 쓴 중복 방어는 잉여 → 제거.
- `&slice[i]` 등 슬라이스 원소 aliasing 지양. append/재할당 시 stale 포인터.

### 관용구
- context 기반 logger 사용
- interface 분리
- 파라미터가 많으면 struct로 관리
- `time.Now().UTC()` 명시. `time.Now()` 사용 시 TZ 불명확
- 함수 반환값의 TZ가 함수명에서 드러나지 않으면 경고
- mapper 대신 생성자(`NewXxx(...)`): entity 변환은 생성자로.
- worker/handler 같은 메커니즘 이름보다 usecase 목적을 드러내는 이름 선호.

### 패키지/구조
- 패키지 간 import 방향: 순환참조 여부
- 불필요한 패키지 분리보다 단순 구조 선호
- 기존 코드/라이브러리 재사용: 이미 구현된 클라이언트 있는지 확인

### 인프라 특화
- Kafka consumer/producer: consumer lag, micro-batch, confluent 라이브러리, `read_committed` 필요성
- DynamoDB `Limit + FilterExpression`: Limit가 Filter 적용 전에 동작 → 빈 결과 가능
- proto 하위호환성: gen-go 버전 불일치, 직렬화 번호 변경

### 테스트
- mock은 mockgen 생성물을 생성자 정식 경로(`NewXxx(..., dep)`)로 주입한다.
- 테스트 상수/구조체는 테스트 전용 리터럴로 alias 선언 + helper 로 생성한다.
- `gomock.Any()` 남용 금지: 검증 대상 필드는 명시적으로 매칭.
- give-when-then 순서. DI 불필요한 domain/entity/util 은 suite 없이 단순 테스트로 충분(최상위 pkg, 무의존).

---

## Java

### Kafka
- `linger.ms`, `batch.size` 등 batching 설정 적정성
- 모니터링 기반 점진적 접근 권장

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
- API 실패 시 UI 상태: finally 블록에서 서버 실패와 불일치 가능

### 컨벤션
- 한 파일만 변경하면 UI 일관성이 깨지는 경우 별도 이슈 제안
- 새 Vue 컴포넌트는 Composition API (script setup)

### Import 경로
- 절대 경로 우선: 프로젝트에 path alias가 있으면 상대 경로 대신 alias 경로 사용
- 파일 이동 시 상대 경로 깨짐 주의: diff에서 파일 이동(`rename`)이 감지되면, 해당 파일 내 상대 경로 import가 전부 유효한지 확인

---

## 출력 형식

```
### [언어]: [PASS / N건 발견]
- [CRITICAL/INFO] file:line · 설명
```
해당 언어 파일이 diff에 없으면: `[언어]: 해당 없음 (변경된 파일 없음)`
