# Python / Django / DRF / Pydantic / pytest

## Types

- Collection default: `list[str] = []`.
- Constrained values get a constrained type: `list[EnumA | EnumB]`; pydantic validates by Enum matching, and the same Enum Union on payload and repo removes the `list` invariance issue; with `class X(str, Enum)` set `use_enum_values=True` so runtime stays `str` and Django `__in` filters keep working.
- Falsy sentinel for absent scalars: `search_id: int = 0`, `search_name: str = ''` when falsy naturally means "no filter".
- TYPE_CHECKING symbols stay in annotations: using one at runtime raises `NameError`, which mypy and the build pass and only pytest catches.
- dataclass vs dict: keep dict kwargs for an entity API in sentinel style (`None` = no change, `unset_xxx` = explicit unset), which distinguishes "explicitly set" from "default"; adopt a dataclass only together with an `UNSET` sentinel / separate-method refactor.

## Functions and classes

- Spread then explicit: `Entity(**payload.dict(), explicit_field=value)`.
- Late binding makes a module-level helper below its caller safe (step-down order).
- Use case class structure: state-holding builders and UseCases are classes (`ReportTree`, `MonthlyReportUseCase`); pure orchestration/fetch helpers may be module functions (`resolve_statement_scope`, `build_statement_tree`, `summarize_statement`, `_statement_*`); externally called → public, internal → private instance method, public `@staticmethod` only for pure state-independent computation, never a private classmethod/staticmethod, and all private helpers of one class are one kind.

## Validation

- Validation ladder in Django: type/format in the DRF Serializer or view, a single-value invariant in the value object's `__post_init__`, a relational rule in a domain method.
- Explicit validation over framework magic: put checks in a `*Validator` class with `@classmethod validate_<field>(value) -> None` and plain `if ...: raise <Domain>InvalidArgumentError`, called from both repo `create`/`update` and the entity `@validator` that returns the value unchanged (Django model/assignment bypasses validators, so the repo call is mandatory); the Fake repo mirrors the same calls (2-track), tests call the `*Validator` directly, and the entity validator is never dropped as "low-value re-validation"; since `to_entity()` validates on every read, confirm seed/existing rows pass first.
- Validators return the value unchanged: this rules out pydantic `constr(...)` and any `@validator` whose return value replaces the field (even `return v.strip()`); a check-raise-return-unchanged validator is fine; strip/normalize at the entrypoint (servicer/view) or not at all, rejecting whitespace-only input via `if not x.strip()` without changing the value.

## Errors

- `except Exception` handlers return the fixed string `"Internal Server Error"` and log the original.
- Failure aggregation logs once after the loop: `logger.error('... %d failed: %s', n, {id: 메시지})`.

## pytest

- Shared helpers live in `conftest.py`.
- Background work: patch the submit function to run synchronously (an autouse fixture when shared); a real-thread test waits with `threading.Event.wait(timeout)`.
- Framework built-ins left untested include Pydantic `Field(gt=0)`, frozenset membership and Django ORM basics; APIClient view tests cover simple-composition UseCases.
- Explicit pre-change value in given: a Faker fixture that happens to be `currency='KRW'` makes a "change to KRW" test pass vacuously; set `uc.copy(update={'currency': 'USD', ...})` in given, then update.
- `@transaction.atomic` + MagicMock needs `@pytest.mark.django_db`: the decorator itself opens a DB connection, so without the mark the test fails with `RuntimeError: Database access not allowed` even though the mock touches no table.
- Factories accept the instant: `build_request_entity` / `build_campaign_entity` expose `start_at`/`end_at` so one test injects one value; separate `datetime.now(tz=timezone.utc)` calls drift by microseconds and break `result.start_at == old_entity.start_at`.
- Singleton mocking via context manager: a helper returns `mock.patch.object(Foo, 'get_instance', return_value=mock.Mock(spec=Foo))` and is used as `with helper():`; `spec=` turns an unknown method call into `AttributeError`; patching `get_instance` only works when production resolves it per call, otherwise patch the module-level cached variable.
- Deterministic dates for business-day tests: pin a holiday-free Monday such as 2025-01-06 (SouthKoreaWorkalendar) through injected `now`; for other future-time tests prefer relative time over a fixed instant.

## Django / DRF style

- `__init__.py` stays empty.
- View shape: build the UseCase with the repo → `_build_user_info(request)` → RequestPayload from `**request.query_params.dict()` / `**kwargs` → `use_case.execute(user_info, request_payload)` → `Response(data=response_payload.dict(), status=...)`.
- PATCH DTO convention: HTTP method `patch()`, every field `Optional[T] = None`, `Config.extra='forbid'`, partial merge with `exclude_unset=True`, a pre-validator `_reject_explicit_null` rejecting explicit null ("omit = no change, null = intentional clear"), and cross-field checks (dates/budget) limited to fields present in the partial so a name-only edit is not re-validated against old values.
- OpenAPI spec with every endpoint change: a repo's `docs/apis/paths/{console}/{module}/user.yaml|admin.yaml`; a legacy project one yaml per endpoint under `docs/openapi/{app}/` registered by `$ref` in `docs/openapi/root.yaml` `paths:`; add it whenever a similar endpoint is documented; file = top-level `post:`/`get:` + summary/tags/operationId/requestBody·parameters/responses 200/202/400/401/403/500.

## Time and external calls

- `now` injection mechanics: `now: datetime | None = None` with `now = now or datetime.now(tz=timezone.utc)` (a datetime is always truthy, so `or` is safe); UseCase `execute(..., now=None)` so production uses the default and only tests inject.
- Calendar date for a zone-anchored repo: when the repo anchors with `arrow.replace(tzinfo='Asia/Seoul').floor('day')`, pass `astimezone(tz).date()`; a UTC tz-aware `.date()` alone is off by one during UTC 15:00–23:59.
- Timeouts: Django `EMAIL_TIMEOUT`, requests `timeout=`, gRPC `timeout=`.
- Never set `updated_at` by hand: `Foo.objects.filter(id=...).update(name='x')` is complete; the DDL `ON UPDATE CURRENT_TIMESTAMP` covers `queryset.update()` where `auto_now` does not fire, and `save()` is covered by `auto_now`; a manual value double-handles and races with other transactions; the only exception is a legacy table with neither `auto_now` nor `ON UPDATE`, where you set it explicitly.
