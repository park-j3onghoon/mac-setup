## 타입 안전성
- 타입 힌트가 약해지지 않았는지 (`Any` 추가, 구체 타입 → Union 등)
- `dict` 대신 `dataclass`, `NamedTuple` 사용 권장. sentinel 식 entity API의 dict kwargs는 `~/.claude/lib/coding/types-python.md`를 Read하고 그 dataclass vs dict 항목을 따른다
- `# type: ignore` 추가 시 이유가 명확한지
- enum: char/string 필드보다 enum
- `classmethod` vs `staticmethod` 구분 (클래스 연관성 기준)
- 신규 `.py` 는 `from __future__ import annotations` 선언.
- `None`이 들어올 수 있는 매개변수·반환값의 타입에 `None`이 빠져 있으면(`Optional[T]`, `T | None`) 지적한다.
- 클래스 변수에 `ClassVar`가 없으면 지적한다.
- 추상 메서드를 구현한 메서드의 시그니처가 추상 메서드와 다르면 지적한다.
- 같은 값을 `None`과 문자열 `"None"`으로 섞어 쓰면 지적하고 enum으로 바꾸게 한다.

## 관용구
- `defaultdict` vs `setdefault` 적절한 선택
- `list` 대신 `set` (집합 연산 시)
- 팩토리 메서드는 `from_*` 패턴 선호
- `if value:`나 `value or 기본값`이 0·빈 문자열 같은 올바른 값을 없는 값으로 거르면 지적하고 `is None` 비교로 바꾸게 한다.
- set에서 `next(iter(...))`로 아무 원소나 꺼내 쓰면 지적하고 정렬한 뒤 고르게 한다.
- 인스턴스 변수 이름을 대문자 상수 꼴(`self.TOKEN_MANAGER`)로 쓰면 지적한다.
- 다른 클래스의 `_` 속성을 밖에서 읽으면 지적하고 공개 메서드나 생성자 주입으로 바꾸게 한다.
- 이벤트 루프를 직접 만들어 돌리면 지적하고 `asyncio.run`·`asyncio.gather`를 쓰게 한다.
- 요청마다 `aiohttp.ClientSession`을 새로 만들면 지적하고 세션 하나를 나눠 쓰게 한다.
- `date.today()`·`datetime.now().date()`로 날짜를 만들면 지적하고, `timezone.localdate()`나 `datetime.now(ZoneInfo('Asia/Seoul')).date()`로 시간대를 밝히게 한다.

## 예외
- `try`/`except`로 예외를 잡고 `None`을 돌려주는 함수는, 호출자가 없음을 기대하는 조회(`find_*`, `search_*`)가 아니면 지적하고 예외가 올라가게 한다.
- dict 조회 실패를 `KeyError` 그대로 올리면 지적하고, 대상 id·기간을 담은 예외로 바꾸게 한다.

## 리소스/안전성
- cursor.close() 누락, context manager 오용
- async wrapping으로 commit blocking 방지

## 트랜잭션
- `with uow:` 블록 안에서 조회만 하면 지적하고 블록 밖에서 조회하게 한다.
- `transaction.on_commit` 안에서 다른 시스템을 부르고 그 호출이 실패해도 성공 응답을 돌려주면 지적하고, outbox나 먼저 만든 리소스를 지우는 보상 처리로 바꾸게 한다.

## Django 특화
- ORM `.annotate()` 에 새 필드 추가 시, 결과 dict 키와 dataclass 필드 일치 확인
- migration 파일 누락 / 순서 오류
- 다른 시스템이 발급한 id를 범위가 작은 정수 필드(`PositiveSmallIntegerField` 최대 65535, `PositiveIntegerField`)에 저장하면 지적하고 `BigIntegerField`로 바꾸게 한다.
- `.iterator()`는 무거운 엔티티를 대량 스캔하며 스트림으로 소비할 때만 쓴다. 결과를 바로 `list()`로 만들거나 청크로 바운드된 가벼운 projection(`values_list`)에 붙은 `.iterator()`는 지적한다.
- except 블록 직접 return: 예외를 응답으로 바꾸는 데코레이터에서 변수 할당 후 fall-through 대신 각 except 블록에서 직접 `return Response(...)`.
- `bulk_create(update_conflicts=True)`로 행을 갱신하면, `auto_now` 필드(`updated_at`)에 값을 직접 넣고 `update_fields`에 넣었는지와 그걸 확인하는 테스트가 있는지 보고 빠지면 지적한다.
- 모델이 `abstract = True`가 아닌 모델을 상속하면 지적하고, 추상 모델 상속이나 따로 된 모델로 바꾸게 한다.

## 스타일 / 복잡도
- early return 으로 중첩 해소: 함수 본문 기준 들여쓰기 3단계 이내(if·for·while·try·with 블록 한 겹이 1단계)
- `os.path` 대신 `pathlib`
- bare `except:` 대신 구체 예외만 catch
- 1회성 로직에 도입한 ABC/Protocol은 지적한다

## 테스트
- mock의 `side_effect`·`return_value`가 실제 함수가 돌려주는 꼴(여러 번 부를 때의 값 목록, 예외)과 다르면 지적한다.
- 비동기 함수를 손으로 만든 가짜로 대신하면 지적하고 `AsyncMock`을, aiohttp 호출은 `aioresponses`를 쓰게 한다.
- `pytest.mark.parametrize`의 케이스들이 서로 다른 규칙을 확인하면 지적하고 테스트를 나누게 한다.
- 모듈 전역 `Faker()` 인스턴스의 `unique`를 여러 테스트가 함께 쓰면 지적하고 pytest `faker` fixture를 쓰게 한다.
