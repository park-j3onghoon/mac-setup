# Python / Django / Pydantic 특화 코딩 규칙

`coding-rules.md` 코어 규칙과 함께 적용한다.
대상: Python 3.x, Django, DRF, Pydantic, pytest.

---

## 타입 / 시그니처

- **컬렉션 default 문법**: `list[str] | None = None` 대신 `list[str] = []`. (코어 규칙: 코어 `coding-rules.md` "컬렉션 파라미터는 non-nullable")
- **도메인 제약이 있는 값은 타입으로 드러낸다**. `list[str]` + validator + 상수 집합보다 `list[EnumA | EnumB]`가 우선. pydantic이 Enum 매칭으로 자동 검증하고, payload/repo 양쪽을 같은 Enum Union 타입으로 맞추면 `list` invariance 이슈도 사라진다. (`class X(str, Enum)` 패턴이면 `use_enum_values=True`로 runtime은 str, Django ORM `__in` 필터도 그대로 동작.)
- **"없음"을 스칼라 falsy 값으로 표현 가능하면 `None` 대신 0/''**. `search_id: int = 0`, `search_name: str = ''`처럼 falsy 값이 자연스럽게 "필터 없음"을 의미할 때 `int | None` 이중 표현을 피한다. (컬렉션은 "none = 0 아이템"이 혼동돼서 여전히 non-nullable empty container 권장.)
- **TYPE_CHECKING import 주의**. 런타임 코드에서 `TYPE_CHECKING` 블록의 심볼을 사용하면 `NameError`. 빌드·타입체크는 통과하고 pytest에서만 잡히므로 push 전 관련 테스트 실행 필수.
- **`**kwargs` spread와 명시적 파라미터 병행 시, 명시적 파라미터를 `**` 뒤에 배치**하여 override를 보장.

## 에러 처리

- **`except Exception` 핸들러에서 `str(e)`를 클라이언트에 노출 금지**. `"Internal Server Error"` 같은 고정 문자열 사용. 원본 에러는 로깅에만 포함.

## 테스팅 (pytest)

- **테스트 메서드명은 영어, docstring만 한글**.
- **Pydantic `Field(gt=0)`, Enum 값 검증 등은 테스트하지 않는다**. 프레임워크가 보장.
- **Fake repo까지 만들어서 "필드가 올바르게 세팅되는가" 검증하는 건 프레임워크 테스트에 가깝다**. 단순 조합 UseCase는 View 통합테스트(APIClient)에서 커버.
- **헬퍼는 `conftest.py`에 집중**. 테스트 파일마다 같은 fixture/factory를 중복하지 않는다.

## Django 스타일

- **`__init__.py`에 불필요한 모듈 설명 docstring 넣지 않는다**. 빈 파일로 둔다.
- **맥락 독립적 로직 → `domain` 레이어, 맥락 의존적 → `application` 레이어**.
- **API 추가 시 OpenAPI YAML 스펙 문서도 함께 업데이트** (프로젝트가 collaborative/adserver 등 스펙 문서 컨벤션을 따른다면).

## 시간 / 외부 의존

- **시간 의존 검증 함수는 `now` 옵셔널 주입 패턴**. 영업일/공휴일 등 flaky 테스트 제거.
- **모델 `updated_at`은 DDL/ORM 자동 처리**에 맡긴다. 수동 세팅 금지 (중복 처리 및 race 위험).
