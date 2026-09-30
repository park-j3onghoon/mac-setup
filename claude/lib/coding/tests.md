# Tests

## Cycle and scope

- Red / green / refactor: write a failing test first, then the minimal code that passes it, then refactor while the tests stay green.
- Test at the seams: assert behaviour through the public interface (use case entry, port, HTTP), and test a simple-composition use case through an entrypoint integration test; test a private helper or internal map through what calls it, while a transition map, a `*Validator` and a value object may be tested directly.
- Cover the change: give every behaviour the change adds or modifies a test at its public seam; the Leave untested list below holds the only exceptions.
- Leave untested: before copying a test layer, ask "is this testing our code or the framework?". Leave these untested:
  - framework built-ins (field types, enum membership, required/optional, declarative constraints, ORM basics)
  - pure data objects ("x=1 → x is 1") and a fake repository's "fields set correctly"
  - snapshots of a private map copied into the test
  - exhaustive invalid cases; test the valid cases
  - log wording; test only the functional property (run_id submit/finish pairing) and keep the wording contract in a constant comment
- MC/DC: in personal repos (linkcart etc.), give each sub-condition of a decision such as `A && (B || C)` a case where it alone flips the result with the others fixed; start from n+1 cases, and without JaCoCo-style support design the input table by hand.

## Shape

- Naming and structure: English method name (`test_rejects_invalid_status_type`), a Korean scenario docstring that says more than the name, and `# given` / `# when` / `# then` markers (a routing-smoke or exception test may combine them as `# when & then`; one legacy project uses uppercase with a short note, `# Given: 기본그룹 org + 배정그룹 org`).
- Markers beat file-local convention: give new tests the docstring and markers even when neighbouring tests lack them, and leave lightly edited existing tests as they are; split `assert call().data...` into When (`response = call()`) and Then; write in the Then comment only what the docstring does not say.
- Dedup and helpers: keep one of a single-field and a multi-field change test that prove the same thing; test the same rule via different fields once; put helpers (`create_draft`, `force_status`, `_make_repo_with_usecases`) in the suite's shared fixture file.
- Domain objects only in fixtures/factories: build them with `make_batch()` / `FakeRepository.for_batch(...)` instead of inline `Batch(...)`/`OrderLine(...)` in a test body.
- Fakes honour the real contract: make a fake repository behave like the real one (update of a missing row raises `NotFound` in both).

## Determinism

- Deterministic tests: remove every source of nondeterminism at the test boundary:
  1. background thread/executor: replace the submit function with a synchronous one (shared by the suite when several tests need it); verify real threads only in a dedicated test that waits on an event with a timeout; wait on events/conditions instead of `sleep`
  2. time: have the use case entry take the current time as a parameter or an injected clock, pin it in tests, and derive other times in the test as offsets from it
  3. random/fake data: set every result-affecting value explicitly, the value before a change included
  4. shared state: keep every mutable value and DB row test-local

## Python

- Dedup and helpers: the shared fixture file is `conftest.py`.
- Background work: an autouse fixture patches the submit function to run synchronously; a real-thread test waits with `threading.Event.wait(timeout)`.
- Leave untested: framework built-ins include Pydantic `Field(gt=0)` and frozenset membership; the entrypoint integration test is an APIClient view test.
- Explicit pre-change value in given: set it with `uc.copy(update={'currency': 'USD', ...})`, then update; a Faker fixture that happens to hold `currency='KRW'` lets a "change to KRW" test pass without exercising the change.
- `@transaction.atomic` + MagicMock: when the code under test runs in `@transaction.atomic`, mark the test `@pytest.mark.django_db`, also when every repository is a MagicMock; without the mark the test fails with `RuntimeError: Database access not allowed`.
- Factories accept the instant: give factories (`build_request_entity` / `build_campaign_entity`) `start_at`/`end_at` parameters and pass one value per test. Separate `datetime.now(tz=timezone.utc)` calls differ by microseconds and break `result.start_at == old_entity.start_at`.
- Singleton mocking via context manager: a helper returns `mock.patch.object(Foo, 'get_instance', return_value=mock.Mock(spec=Foo))` and is used as `with helper():`; when production caches the instance in a module-level variable, patch that variable instead.
- Deterministic dates for business-day tests: pin a holiday-free Monday such as 2025-01-06 (SouthKoreaWorkalendar) through injected `now`.
- `now` injection mechanics: `now: datetime | None = None` with `now = now or datetime.now(tz=timezone.utc)`; UseCase `execute(..., now=None)`.

## Frontend

- Test-only attributes (`data-testid`) ship in the same PR as the test that queries them (`getByTestId`); otherwise defer the attribute.
- Dedup and helpers: the shared fixture file is a vitest shared helper module.
