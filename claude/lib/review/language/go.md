## 에러 핸들링
- 레이어 경계에서 `fmt.Errorf("...: %w", err)` 패턴 사용
- 다중 에러 체인은 `fmt.Errorf("%w: %w", e1, e2)` 또는 `errors.Join(...)`으로 묶는다. 재시도 제어가 필요하면 재시도를 멈추는 제어용 에러를 join.
- 비핵심 I/O(postback·enrichment 등) 에러를 `log.Warnf`로 기록하고 계속 진행하는 패턴은 정상으로 본다.
- `failed to` prefix 불필요 중복
- 반환된 `err`를 `_`로 버리거나 검사하지 않고 넘어가는 호출은 지적한다.
- 검사 실패를 알리는 에러는 sentinel 에러에 맥락을 붙여 만들게 한다(`fmt.Errorf("%w: id is empty", ErrInvalidSetting)`).
- 업무 로직에서 `panic`을 부르면 지적하고 error를 돌려주게 한다.

## 안전성
- type assertion(`ret.Get(0).(*Type)`) 시 nil 체크
- 인덱스 경계 검사 (`tokens length check`)
- 형변환 실패 시 panic 가능성
- `*int32` vs `int32`, `optional` proto field로 nil/zero-value 명확 구분
- 컴파일 타임 인터페이스 검증: `var _ Interface = (*Impl)(nil)`
- 방어 코드 제거: 빌드타임에 보장되는 nil 체크·생성자가 보장하는 invariant·도달 불가 경로의 방어 코드, `sync.Once`와 `init()`을 함께 쓴 중복 방어는 잉여 → 제거.
- 요청마다 도는 경로에서 struct 원소를 값으로 복사하는 루프(`for _, v := range s`)는 `for i := range s`와 `&s[i]`로 바꾸게 하고, 그 포인터를 들고 있는 동안 슬라이스에 append하거나 다시 할당하면 지적한다.
- 요청 처리 경로에서 panic하는 함수(`MustGet`)를 부르면 지적하고 `Get`과 ok 검사로 바꾸게 한다.
- `go.mod`의 `go` 버전이 1.21 이하인 모듈에서 for 루프 변수의 주소(`&v`)를 저장하거나 goroutine·클로저 안에서 루프 변수를 쓰면 지적하고, 루프 안에서 `v := v`로 복사하게 한다.

## 관용구
- context 기반 logger 사용
- `time.Now()` 대신 `time.Now().UTC()` 명시
- mapper 대신 생성자(`NewXxx(...)`): entity 변환은 생성자로.
- ctx를 받은 함수 안에서 `context.Background()`를 새로 만들면 지적하고 받은 ctx를 넘기게 한다.
- `interface{}`·`any`를 매개변수나 반환 타입으로 새로 쓰면 지적하고 구체 타입이나 제네릭으로 바꾸게 한다.
- 패키지 밖에서 쓰지 않는 식별자를 대문자로 공개하면 지적한다.
- 없을 수 있는 값을 돌려주는 getter는 값과 존재 여부를 함께 돌려주게 하고, 호출부는 `value, exists := getter()`로 받게 한다.
- 빈 슬라이스를 `[]string{}`로 만들어 append하면 지적하고 nil 슬라이스(`var s []string`)로 시작하게 한다. JSON으로 내보내 `[]`가 필요한 슬라이스는 그대로 둔다.
- `go.mod`의 `go`·`toolchain` 버전이나 protobuf 모듈 버전을 낮추면 지적한다.

## 테스트
- mock은 mockgen 생성물을 생성자 정식 경로(`NewXxx(..., dep)`)로 주입한다.
- 테스트 상수/구조체는 테스트 전용 리터럴로 alias 선언 + 함수로 생성한다.
- 검증 대상 필드는 `gomock.Any()` 대신 명시적으로 매칭.
- DI가 필요 없는 domain·entity·util 테스트는 testify `suite` 없이 평범한 `func TestXxx(t *testing.T)`로 쓴다.
