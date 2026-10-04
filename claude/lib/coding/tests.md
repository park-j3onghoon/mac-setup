# Tests

For Python code, also Read `~/.claude/lib/coding/tests-python.md`; for frontend code, `~/.claude/lib/coding/tests-frontend.md`.

## Cycle and scope

- Red / green / refactor: write a failing test first, then the minimal code that passes it, then refactor while the tests stay green.
- Test at the seams: assert behaviour through the public interface (the use case entry, a port, HTTP), and test a simple-composition use case through an entrypoint integration test; test an extracted function or internal map through what calls it, while a transition map, a `*Validator` and a value object may be tested directly.
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
- One behaviour per test: a test proves one rule and fails for one reason; split a test whose name or docstring joins two rules with "and" (`test_persists_adjustments_and_skips_on_rerun` → `test_persists_adjustment_row` + `test_rerun_creates_no_new_adjustment_row`), and keep in each test only the assertions that prove its own rule.
- Markers beat file-local convention: give new tests the docstring and markers even when neighbouring tests lack them, and leave lightly edited existing tests as they are; split `assert call().data...` into When (`response = call()`) and Then; write in the Then comment only what the docstring does not say.
- Dedup and shared setup: keep one of a single-field and a multi-field change test that prove the same thing; test the same rule via different fields once; put functions several tests share (`create_draft`, `force_status`, `_make_repo_with_usecases`) in the suite's shared fixture file.
- Domain objects only in fixtures/factories: build them with `make_batch()` / `FakeRepository.for_batch(...)` instead of inline `Batch(...)`/`OrderLine(...)` in a test body.
- Test doubles: give a port that holds state a fake (a working in-memory implementation), a call that only needs an answer a stub (a fixed return value), and use a mock (a check on the call itself) only when the call is the outcome (an email sent exactly once).
- Fakes honour the real contract: make a fake repository behave like the real one (update of a missing row raises `NotFound` in both).

## Determinism

- Deterministic tests: remove every source of nondeterminism at the test boundary:
  1. background thread/executor: replace the submit function with a synchronous one (shared by the suite when several tests need it); verify real threads only in a dedicated test that waits on an event with a timeout; wait on events/conditions instead of `sleep`
  2. time: have the use case entry take the current time as a parameter or an injected clock, pin it in tests, and derive other times in the test as offsets from it
  3. random/fake data: set every result-affecting value explicitly, the value before a change included
  4. shared state: keep every mutable value and DB row test-local, so each test passes alone and in any order
