## 에러 핸들링
- 레이어 경계에서 에러는 `fmt.Errorf("...: %w", err)`로 감싸 올린다.
- 에러 여러 개는 `fmt.Errorf("%w: %w", e1, e2)`나 `errors.Join(...)`으로 묶고, 재시도를 멈춰야 하면 재시도를 멈추는 제어용 에러를 함께 join한다.
- 부가 I/O(postback, enrichment) 에러는 `log.Warnf`로 남기고 처리를 이어 간다.
- 에러 메시지에는 `failed to` 접두어 대신 하던 일만 쓴다(`fmt.Errorf("get user: %w", err)`).
- 반환된 `err`는 `_`로 버리는 대신 검사한다.
- 검사 실패를 알리는 에러는 sentinel 에러에 맥락을 붙여 만든다(`fmt.Errorf("%w: id is empty", ErrInvalidSetting)`).
- 업무 로직은 `panic` 대신 error를 돌려준다.

## 안전성
- type assertion은 ok 값을 받는 꼴(`v, ok := x.(*Type)`)로 쓰고, mock 반환값(`ret.Get(0).(*Type)`)은 nil을 검사한 뒤 쓴다.
- 슬라이스 인덱스는 길이를 검사한 뒤 쓴다(`len(tokens)`).
- 없음과 0을 나눠야 하는 값은 `*int32`나 proto `optional` 필드로 둔다.
- 인터페이스 구현체에는 `var _ Interface = (*Impl)(nil)`로 컴파일 타임 검증을 둔다.
- 빌드 타임에 보장되는 nil 체크, 생성자가 보장하는 invariant의 재검사, 도달할 수 없는 경로의 방어 코드, `sync.Once`와 `init()`을 함께 쓴 중복 방어는 지운다.
- 요청마다 도는 경로에서 struct 원소를 값으로 복사하는 루프(`for _, v := range s`)는 `for i := range s`와 `&s[i]`로 바꾸고, 그 포인터를 쓰는 동안 슬라이스는 append·재할당 없이 둔다.
- 요청 처리 경로에서는 panic하는 함수(`MustGet`) 대신 `Get`과 ok 검사를 쓴다.
- `go.mod`의 `go` 버전이 1.21 이하인 모듈에서 for 루프 변수의 주소(`&v`)를 저장하거나 goroutine·클로저 안에서 루프 변수를 쓰면, 루프 안에서 `v := v`로 복사해 쓴다.

## 관용구
- logger는 context에서 꺼내 쓴다.
- 현재 시각은 `time.Now()` 대신 `time.Now().UTC()`로 쓴다.
- entity 변환은 mapper 대신 생성자(`NewXxx(...)`)로 한다.
- ctx를 받은 함수 안에서는 `context.Background()`를 새로 만드는 대신 받은 ctx를 넘긴다.
- 매개변수·반환 타입은 `interface{}`·`any` 대신 구체 타입이나 제네릭으로 쓴다.
- 패키지 밖에서 쓰지 않는 식별자는 소문자로 시작해 패키지 안에 둔다.
- 없을 수 있는 값을 돌려주는 getter는 값과 존재 여부를 함께 돌려주고, 호출부는 `value, exists := getter()`로 받는다.
- 빈 슬라이스는 `[]string{}` 대신 nil 슬라이스(`var s []string`)로 시작해 append한다. JSON으로 내보내 `[]`가 필요한 슬라이스는 `[]string{}`로 둔다.
- `go.mod`의 `go`·`toolchain` 버전과 protobuf 모듈 버전은 지금 버전 이상으로 둔다.

## 테스트
- mock은 mockgen 생성물을 생성자 정식 경로(`NewXxx(..., dep)`)로 주입한다.
- 테스트 상수·구조체는 테스트 전용 리터럴로 alias를 선언하고 함수로 만든다.
- 검증 대상 필드는 `gomock.Any()` 대신 값을 밝혀 매칭한다.
- DI가 필요 없는 domain·entity·util 테스트는 testify `suite` 없이 평범한 `func TestXxx(t *testing.T)`로 쓴다.
