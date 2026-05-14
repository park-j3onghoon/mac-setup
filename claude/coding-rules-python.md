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
- **`@transaction.atomic` 적용 함수를 MagicMock 기반으로 테스트하면 `@pytest.mark.django_db` 필요**. atomic 데코레이터가 DB 연결을 요구해서 mark 없으면 `RuntimeError: Database access not allowed`. MagicMock이 실제 DB를 건드리지 않아도 decorator 자체가 DB를 요구.
- **Fixture factory는 시각 일관성을 호출자가 주입 가능하게**. 여러 factory(예: `build_request_entity`, `build_campaign_entity`)가 각자 `datetime.now(tz=timezone.utc)`를 호출하면 같은 테스트에서 같이 쓸 때 `start_at/created_at` 등이 마이크로초 단위로 어긋나 `result.start_at == old_entity.start_at` 같은 equality assertion이 실패한다. factory에 시간 파라미터(`start_at`, `end_at` 등)를 노출해 호출자가 동일 값을 주입한다.

## Django 스타일

- **`__init__.py`에 불필요한 모듈 설명 docstring 넣지 않는다**. 빈 파일로 둔다.
- **맥락 독립적 로직 → `domain` 레이어, 맥락 의존적 → `application` 레이어**.
- **API 추가 시 OpenAPI YAML 스펙 문서도 함께 업데이트** (프로젝트가 collaborative/adserver 등 스펙 문서 컨벤션을 따른다면).
- **Partial update(PATCH) DTO 관례**: HTTP 메서드는 `patch()`, 모든 필드 `Optional[T] = None`, `Config.extra='forbid'`, `exclude_unset=True`로 partial merge, explicit null을 거부하는 pre-validator(`_disallow_explicit_null`) — "omit = 변경 없음, null = 의도적 지움"을 명확히 분리. 날짜/예산 같은 교차 검증도 "partial에 포함된 필드에 한정"해 돌려 기존 과거 값이 name-only 수정에서 재검증에 걸리는 사례를 막는다. livecommerce/display 공통.

## 시간 / 외부 의존

- **시간 의존 검증 함수는 `now` 옵셔널 주입 패턴**. 영업일/공휴일 등 flaky 테스트 제거.
- **모델 `updated_at`은 DDL/ORM 자동 처리**에 맡긴다. 수동 세팅 금지 (중복 처리 및 race 위험).
  - **buzzvil DB 컨벤션**: `updated_at` 컬럼은 DDL에 `ON UPDATE CURRENT_TIMESTAMP`가 걸려 있어 DB가 자동 갱신한다. 따라서 `queryset.update()`처럼 `auto_now=True` signal이 안 도는 경우에도 코드에서 `updated_at=datetime.now(...)`를 따로 넣지 않는다. (`save()`는 ORM의 `auto_now`로 처리됨.) 코드에서 수동 세팅하면 DB 트리거와 이중 처리되고, 다른 트랜잭션과 race 가능.
  - 적용: `Foo.objects.filter(id=...).update(name='x')` 만으로 충분. `updated_at=...` 인자 추가 금지.
  - 예외: `auto_now`가 없고 `ON UPDATE`도 없는 레거시 테이블이라면 코드에서 명시 세팅 필요. 추가 전 DDL 확인.
