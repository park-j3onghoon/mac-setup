## 타입 안전성
- 타입 힌트는 `Any`나 Union으로 넓히는 대신 구체 타입으로 쓴다.
- 구조가 정해진 값은 `dict` 대신 `dataclass`나 `NamedTuple`로 둔다. sentinel 식 entity API의 dict kwargs는 `~/.claude/lib/coding/types-python.md`를 Read하고 그 dataclass vs dict 항목을 따른다.
- `# type: ignore`를 더하면 그 이유를 같은 줄 주석에 적는다.
- 종류·상태를 담는 필드는 char·string 대신 enum으로 둔다.
- `cls`를 쓰는 메서드는 `classmethod`로, 클래스도 인스턴스도 쓰지 않는 메서드는 `staticmethod`로 둔다.
- 새 `.py` 파일은 `from __future__ import annotations`로 시작한다.
- `None`이 들어올 수 있는 매개변수·반환값은 타입에 `None`을 넣는다(`Optional[T]`, `T | None`).
- 클래스 변수에는 `ClassVar`를 붙인다.
- 추상 메서드를 구현한 메서드는 추상 메서드와 같은 시그니처로 쓴다.
- 같은 값을 `None`과 문자열 `"None"`으로 섞어 쓰는 대신 enum으로 바꾼다.

## 관용구
- 키마다 값을 모으는 dict는 `defaultdict`로 만들고, 한 키에 기본값을 한 번 넣을 때는 `setdefault`를 쓴다.
- 포함 검사나 집합 연산에 쓰는 모음은 `list` 대신 `set`으로 둔다.
- 팩토리 메서드 이름은 `from_*`으로 짓는다.
- 0·빈 문자열이 올바른 값인 변수는 `if value:`나 `value or 기본값` 대신 `is None`으로 비교한다.
- set에서 원소 하나를 고를 때는 `next(iter(...))` 대신 정렬한 뒤 고른다.
- 인스턴스 변수 이름은 대문자 상수 꼴(`self.TOKEN_MANAGER`) 대신 소문자로 쓴다.
- 다른 클래스의 `_` 속성은 밖에서 읽는 대신 공개 메서드나 생성자 주입으로 받는다.
- 이벤트 루프는 직접 만들어 돌리는 대신 `asyncio.run`·`asyncio.gather`로 돌린다.
- `aiohttp.ClientSession`은 요청마다 새로 만드는 대신 하나를 나눠 쓴다.
- 날짜는 `date.today()`·`datetime.now().date()` 대신 `timezone.localdate()`나 `datetime.now(ZoneInfo('Asia/Seoul')).date()`로 시간대를 밝혀 만든다.

## 예외
- `try`/`except`로 예외를 잡고 `None`을 돌려주는 대신 예외를 올린다. 호출자가 없음을 기대하는 조회(`find_*`, `search_*`)만 `None`을 돌려준다.
- dict 조회 실패는 `KeyError` 그대로 올리는 대신 대상 id·기간을 담은 예외로 바꿔 올린다.

## 리소스/안전성
- DB cursor·파일 같은 자원은 `with` 블록으로 열고 닫는다.
- async 코드의 동기 DB commit은 `sync_to_async`나 `run_in_executor`로 감싸 부른다.

## 트랜잭션
- `with uow:` 블록은 쓰기가 있는 구간에만 쓰고, 조회만 하는 구간은 블록 밖에서 조회한다.
- `transaction.on_commit` 안에서 다른 시스템을 부르면, 호출 실패를 성공 응답으로 덮는 대신 outbox나 먼저 만든 리소스를 지우는 보상 처리를 쓴다.

## Django 특화
- ORM `.annotate()`에 새 필드를 더하면 결과 dict 키와 dataclass 필드 이름을 맞춘다.
- 모델을 바꾸면 migration 파일을 같은 PR에 넣고 번호 순서를 맞춘다.
- 다른 시스템이 발급한 id는 범위가 작은 정수 필드(`PositiveSmallIntegerField` 최대 65535, `PositiveIntegerField`) 대신 `BigIntegerField`에 저장한다.
- `.iterator()`는 무거운 엔티티를 대량 스캔하며 스트림으로 소비할 때만 쓴다. 결과를 바로 `list()`로 만들거나 청크로 바운드된 가벼운 projection(`values_list`)에 붙은 `.iterator()`는 지운다.
- 예외를 응답으로 바꾸는 데코레이터는 변수에 담아 아래로 흘리는 대신 각 except 블록에서 바로 `return Response(...)`한다.
- `bulk_create(update_conflicts=True)`로 행을 갱신하면 `auto_now` 필드(`updated_at`)에 값을 직접 넣고 `update_fields`에 넣으며, 그걸 확인하는 테스트를 둔다.
- 모델은 `abstract = True`가 아닌 구체 모델 대신 추상 모델을 상속한다.

## 스타일 / 복잡도
- 함수 본문의 들여쓰기는 3단계 이내로 두고(if·for·while·try·with 블록 한 겹이 1단계), 넘으면 early return으로 줄인다.
- 경로는 `os.path` 대신 `pathlib`으로 다룬다.
- 예외는 bare `except:` 대신 구체 예외 타입으로 잡는다.
- ABC·Protocol은 구현이 둘 이상이거나 port일 때만 둔다.

## 테스트
- mock의 `side_effect`·`return_value`는 실제 함수가 돌려주는 꼴(여러 번 부를 때의 값 목록, 예외)과 같게 둔다.
- 비동기 함수는 손으로 만든 가짜 대신 `AsyncMock`으로, aiohttp 호출은 `aioresponses`로 대신한다.
- `pytest.mark.parametrize`는 한 규칙의 입력만 바꿀 때 쓰고, 서로 다른 규칙은 테스트를 나눈다.
- `Faker`의 `unique`는 모듈 전역 `Faker()` 인스턴스 대신 pytest `faker` fixture로 쓴다.
