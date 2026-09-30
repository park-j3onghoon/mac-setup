# Python / Django / DRF / Pydantic / pytest

## Types

- Collection default: `list[str] = []`.
- Projection return type: a count/existence projection returns e.g. `list[int]`.
- Constrained values get a constrained type: `list[EnumA | EnumB]`, with the same Enum Union on payload and repo; with `class X(str, Enum)`, set `use_enum_values=True`.
- Falsy sentinel for absent scalars: when falsy means "no filter", use `search_id: int = 0`, `search_name: str = ''`.
- TYPE_CHECKING symbols stay in annotations.
- dataclass vs dict: keep dict kwargs for an entity API in sentinel style (`None` = no change, `unset_xxx` = explicit unset); adopt a dataclass only together with an `UNSET` sentinel / separate-method refactor.

## Functions and classes

- Spread then explicit: `Entity(**{**payload.dict(), 'explicit_field': value})`.
- Inline length decides a nested call too: `return Payload(**repo.create(entity).dict())`.
- Immutable copy: `dict(input)` + the modification.
- A bare value such as `Decimal('0')` stays inline instead of becoming a module constant.
- Use case class structure: make state-holding builders and UseCases classes (`ReportTree`, `MonthlyReportUseCase`); pure orchestration/fetch helpers may be module functions (`resolve_statement_scope`, `build_statement_tree`, `summarize_statement`, `_statement_*`); make an externally called method public and an internal one a private instance method; use a public `@staticmethod` only for pure state-independent computation and no private classmethod/staticmethod; keep all private helpers of one class the same kind.

## Validation

- Validation ladder in Django: type/format in the DRF Serializer or view, a single-value invariant in the value object's `__post_init__`, a relational rule in a domain method.
- Explicit validation over framework magic: put checks in a `*Validator` class with `@classmethod validate_<field>(value) -> None` and plain `if ...: raise <Domain>InvalidArgumentError`; call it from both repo `create`/`update` and the entity `@validator`, which returns the value unchanged; make the Fake repo make the same calls; call the `*Validator` directly in tests; keep the entity validator; before adding a validator, confirm seed and existing rows pass it.
- Validators return the value unchanged: skip pydantic `constr(...)` and any `@validator` that returns a replaced value (even `return v.strip()`); a check-raise-return-unchanged validator is fine; strip/normalize at the entrypoint (servicer/view) or not at all, and reject whitespace-only input with `if not x.strip()` without changing the value.

## Errors

- `except Exception` handlers return the fixed string `"Internal Server Error"` and log the original.
- Failure aggregation logs once after the loop: `logger.error('... %d failed: %s', n, {id: 메시지})`.
- Message in an f-string: `raise NotFoundError(f'Campaign request not found: id={request_id}')`, `raise NotFoundError(f'Campaign creative not found: campaign_id={campaign_id}')`.

## pytest

- Shared helpers live in `conftest.py`.
- Background work: patch the submit function to run synchronously (an autouse fixture when shared); a real-thread test waits with `threading.Event.wait(timeout)`.
- Framework built-ins left untested include Pydantic `Field(gt=0)`, frozenset membership and Django ORM basics; test simple-composition UseCases through APIClient view tests.
- Explicit pre-change value in given: when a test changes a value, set the value before the change explicitly in given (`uc.copy(update={'currency': 'USD', ...})`), then update.
- `@transaction.atomic` + MagicMock: when the code under test runs in `@transaction.atomic`, mark the test `@pytest.mark.django_db`, also when every repository is a MagicMock.
- Factories accept the instant: give factories (`build_request_entity` / `build_campaign_entity`) `start_at`/`end_at` parameters and pass one value per test.
- Singleton mocking via context manager: a helper returns `mock.patch.object(Foo, 'get_instance', return_value=mock.Mock(spec=Foo))` and is used as `with helper():`; when production caches the instance in a module-level variable, patch that variable instead.
- Deterministic dates for business-day tests: pin a holiday-free Monday such as 2025-01-06 (SouthKoreaWorkalendar) through injected `now`; for other future-time tests, use relative time over a fixed instant.

## Django / DRF style

- `__init__.py` stays empty.
- View shape: build the UseCase with the repo → `_build_user_info(request)` → RequestPayload from `**request.query_params.dict()` / `**kwargs` → `use_case.execute(user_info, request_payload)` → `Response(data=response_payload.dict(), status=...)`.
- PATCH DTO convention: HTTP method `patch()`, every field `Optional[T] = None`, `Config.extra='forbid'`, partial merge with `exclude_unset=True`, a pre-validator `_reject_explicit_null` rejecting explicit null, and cross-field checks (dates/budget) only over fields present in the partial.
- OpenAPI spec with every endpoint change: a repo's `docs/apis/paths/{console}/{module}/user.yaml|admin.yaml`; a legacy project one yaml per endpoint under `docs/openapi/{app}/` registered by `$ref` in `docs/openapi/root.yaml` `paths:`; add it whenever a similar endpoint is documented; file = top-level `post:`/`get:` + summary/tags/operationId/requestBody·parameters/responses 200/202/400/401/403/500.

## Time and external calls

- `now` injection mechanics: `now: datetime | None = None` with `now = now or datetime.now(tz=timezone.utc)`; UseCase `execute(..., now=None)`.
- Calendar date for a zone-anchored repo: when the repo anchors with `arrow.replace(tzinfo='Asia/Seoul').floor('day')`, pass `astimezone(tz).date()`.
- Timeouts: Django `EMAIL_TIMEOUT`, requests `timeout=`, gRPC `timeout=`.
- `updated_at`: leave it to the DDL `ON UPDATE CURRENT_TIMESTAMP` and `auto_now` (`Foo.objects.filter(id=...).update(name='x')` is complete); set it by hand only on a legacy table with neither `auto_now` nor `ON UPDATE`.
