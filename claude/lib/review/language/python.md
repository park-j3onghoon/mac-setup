## 타입 안전성
- 타입 힌트가 약해지지 않았는지 (`Any` 추가, 구체 타입 → Union 등)
- `dict` 대신 `dataclass`, `NamedTuple` 사용 권장. sentinel 식 entity API의 dict kwargs는 `~/.claude/lib/coding/types-python.md`를 Read하고 그 dataclass vs dict 항목을 따른다
- `# type: ignore` 추가 시 이유가 명확한지
- enum: char/string 필드보다 enum
- `classmethod` vs `staticmethod` 구분 (클래스 연관성 기준)
- 신규 `.py` 는 `from __future__ import annotations` 선언.

## 관용구
- `defaultdict` vs `setdefault` 적절한 선택
- `list` 대신 `set` (집합 연산 시)
- 팩토리 메서드는 `from_*` 패턴 선호

## 리소스/안전성
- cursor.close() 누락, context manager 오용
- Redis cluster mode에서 서로 다른 slot 조회 불가 → hashtag 또는 단일 key
- Redis TTL 설정 누락
- async wrapping으로 commit blocking 방지

## Django 특화
- ORM `.annotate()` 에 새 필드 추가 시, 결과 dict 키와 dataclass 필드 일치 확인
- migration 파일 누락 / 순서 오류
- `PositiveIntegerField` vs `BigIntegerField` 등 값 범위에 맞는 타입인지
- `.iterator()`는 무거운 엔티티를 대량 스캔하며 스트림으로 소비할 때만 쓴다. 결과를 바로 `list()`로 만들거나 청크로 바운드된 가벼운 projection(`values_list`)에 붙은 `.iterator()`는 지적한다.
- except 블록 직접 return: 예외를 응답으로 바꾸는 데코레이터에서 변수 할당 후 fall-through 대신 각 except 블록에서 직접 `return Response(...)`.

## 스타일 / 복잡도
- early return 으로 중첩 해소: 함수 본문 기준 들여쓰기 3단계 이내(if·for·while·try·with 블록 한 겹이 1단계)
- `os.path` 대신 `pathlib`
- bare `except:` 대신 구체 예외만 catch
- 1회성 로직에 도입한 ABC/Protocol은 지적한다
