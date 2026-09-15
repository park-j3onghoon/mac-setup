# Coding Rules: Python / Django / DRF / Pydantic / pytest

Applies together with `coding-rules.md` (core); every rule here is a stack-specific narrowing inside the core's scope, never an override.

## Types

- Collection default: `list[str] = []`, not `list[str] | None = None` (core Function "Collection params non-nullable").
- Constrained values get a constrained type: `list[EnumA | EnumB]` over `list[str]` + validator + constant set; pydantic validates by Enum matching, and the same Enum Union on payload and repo removes the `list` invariance issue; with `class X(str, Enum)` set `use_enum_values=True` so runtime stays `str` and Django `__in` filters keep working.
- Falsy sentinel for absent scalars: `search_id: int = 0`, `search_name: str = ''` instead of `int | None` when falsy naturally means "no filter"; collections stay non-nullable empty containers because "none = 0 items" is ambiguous.
- TYPE_CHECKING symbols stay in annotations: using one at runtime raises `NameError`, which mypy and the build pass and only pytest catches (core Change discipline "Tests before push").

## Errors

- `except Exception` handlers return the fixed string `"Internal Server Error"` and log the original; `str(e)` never reaches the client (core Errors "Catch-all handlers").

## pytest

- Explicit pre-change value in given: a Faker fixture that happens to be `currency='KRW'` makes a "change to KRW" test pass vacuously; set `uc.copy(update={'currency': 'USD', ...})` in given, then update.
- `@transaction.atomic` + MagicMock needs `@pytest.mark.django_db`: the decorator itself opens a DB connection, so without the mark the test fails with `RuntimeError: Database access not allowed` even though the mock touches no table.
- Factories accept the instant: `build_request_entity` / `build_campaign_entity` expose `start_at`/`end_at` so one test injects one value; separate `datetime.now(tz=timezone.utc)` calls drift by microseconds and break `result.start_at == old_entity.start_at`.
- Singleton mocking via context manager: a helper returns `mock.patch.object(Foo, 'get_instance', return_value=mock.Mock(spec=Foo))` and is used as `with helper():`; bare `Foo.get_instance().method = Mock(...)` leaks into later tests (order-dependent flakiness); `spec=` turns an unknown method call into `AttributeError`; patching `get_instance` only works when production resolves it per call, otherwise patch the module-level cached variable.
- Deterministic dates for business-day tests: pin a holiday-free Monday such as 2025-01-06 (SouthKoreaWorkalendar) through injected `now`; for other future-time tests prefer relative time over a fixed instant.

## Django / DRF style

- `__init__.py` stays empty: no module docstring.
- View shape (livecommerce `user_view.py`; core Architecture "Thin entrypoint"): ① build the UseCase with the repo ② `_build_user_info(request)` ③ RequestPayload from `**request.query_params.dict()` / `**kwargs` ④ `use_case.execute(user_info, request_payload)` ⑤ `Response(data=response_payload.dict(), status=...)`.
- PATCH DTO convention (livecommerce/display common): HTTP method `patch()`, every field `Optional[T] = None`, `Config.extra='forbid'`, partial merge with `exclude_unset=True`, a pre-validator `_disallow_explicit_null` rejecting explicit null ("omit = no change, null = intentional clear"), and cross-field checks (dates/budget) limited to fields present in the partial so a name-only edit is not re-validated against old values.
- OpenAPI spec with every endpoint change: an ad server repo's `docs/apis/paths/{console}/{module}/user.yaml|admin.yaml` (pattern: `collaborative/`, `livecommerce/`); a legacy project one yaml per endpoint under `docs/openapi/{app}/` registered by `$ref` in `docs/openapi/root.yaml` `paths:`; add it whenever a similar endpoint is documented; file = top-level `post:`/`get:` + summary/tags/operationId/requestBody·parameters/responses 200/202/400/401/403/500.

## Time

- `now` injection mechanics: `now: datetime | None = None` with `now = now or datetime.now(tz=timezone.utc)` (a datetime is always truthy, so `or` is safe); UseCase `execute(..., now=None)` so production uses the default and only tests inject (core Tests "Inject now").
- Never set `updated_at` by hand: `Foo.objects.filter(id=...).update(name='x')` is complete; the DDL `ON UPDATE CURRENT_TIMESTAMP` (`coding-rules-db.md` "updated_at") covers `queryset.update()` where `auto_now` does not fire, and `save()` is covered by `auto_now`; a manual value double-handles and races with other transactions; the only exception is a legacy table with neither `auto_now` nor `ON UPDATE`; check the DDL per table first, then set it explicitly.
