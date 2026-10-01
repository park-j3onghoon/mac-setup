# Tests: Python

- Dedup and helpers: the shared fixture file is `conftest.py`.
- Background work: an autouse fixture patches the submit function to run synchronously; a real-thread test waits with `threading.Event.wait(timeout)`.
- Leave untested: framework built-ins include Pydantic `Field(gt=0)` and frozenset membership; the entrypoint integration test is an APIClient view test.
- Explicit pre-change value in given: set it with `uc.copy(update={'currency': 'USD', ...})`, then update; a Faker fixture that happens to hold `currency='KRW'` lets a "change to KRW" test pass without exercising the change.
- `@transaction.atomic` + MagicMock: when the code under test runs in `@transaction.atomic`, mark the test `@pytest.mark.django_db`, also when every repository is a MagicMock; without the mark the test fails with `RuntimeError: Database access not allowed`.
- Factories accept the instant: give factories (`build_request_entity` / `build_campaign_entity`) `start_at`/`end_at` parameters and pass one value per test. Separate `datetime.now(tz=timezone.utc)` calls differ by microseconds and break `result.start_at == old_entity.start_at`.
- Singleton mocking via context manager: a helper returns `mock.patch.object(Foo, 'get_instance', return_value=mock.Mock(spec=Foo))` and is used as `with helper():`; when production caches the instance in a module-level variable, patch that variable instead.
- Deterministic dates for business-day tests: pin a holiday-free Monday such as 2025-01-06 (SouthKoreaWorkalendar) through injected `now`.
- `now` injection mechanics: `now: datetime | None = None` with `now = now or datetime.now(tz=timezone.utc)`; UseCase `execute(..., now=None)`.
