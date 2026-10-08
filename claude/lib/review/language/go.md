## 에러 핸들링
- 레이어 경계에서 `fmt.Errorf("...: %w", err)` 패턴 사용
- 다중 에러 체인은 `fmt.Errorf("%w: %w", e1, e2)` 또는 `errors.Join(...)`으로 묶는다. 재시도 제어가 필요하면 재시도를 멈추는 제어용 에러를 join.
- 비핵심 I/O(postback·enrichment 등) 에러를 `log.Warnf`로 기록하고 계속 진행하는 패턴은 정상으로 본다.
- `failed to` prefix 불필요 중복
- 반환된 `err`를 `_`로 버리거나 검사하지 않고 넘어가는 호출은 지적한다.

## 안전성
- type assertion(`ret.Get(0).(*Type)`) 시 nil 체크
- 인덱스 경계 검사 (`tokens length check`)
- 형변환 실패 시 panic 가능성
- `*int32` vs `int32`, `optional` proto field로 nil/zero-value 명확 구분
- 컴파일 타임 인터페이스 검증: `var _ Interface = (*Impl)(nil)`
- 방어 코드 제거: 빌드타임에 보장되는 nil 체크·생성자가 보장하는 invariant·도달 불가 경로의 방어 코드, `sync.Once`와 `init()`을 함께 쓴 중복 방어는 잉여 → 제거.
- `&slice[i]` 등 슬라이스 원소 aliasing은 지적한다. append/재할당 시 stale 포인터.

## 관용구
- context 기반 logger 사용
- `time.Now()` 대신 `time.Now().UTC()` 명시
- mapper 대신 생성자(`NewXxx(...)`): entity 변환은 생성자로.

## 테스트
- mock은 mockgen 생성물을 생성자 정식 경로(`NewXxx(..., dep)`)로 주입한다.
- 테스트 상수/구조체는 테스트 전용 리터럴로 alias 선언 + 함수로 생성한다.
- 검증 대상 필드는 `gomock.Any()` 대신 명시적으로 매칭.
- DI가 필요 없는 domain·entity·util 테스트는 testify `suite` 없이 평범한 `func TestXxx(t *testing.T)`로 쓴다.
