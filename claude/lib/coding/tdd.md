# TDD: tests

## Cycle and scope

- Red / green / refactor: write a failing test first, then the minimal code that passes it, then refactor while the tests stay green.
- Test at the seams: assert behaviour through the public interface (use case entry, port, HTTP); test a private helper or internal map through what calls it.
- Cover the change: give every behaviour the change adds or modifies a test at its public seam; the Leave untested list below holds the only exceptions.
- Leave untested: before copying a test layer, ask "is this testing our code or the framework?" and check the sister module's test practice. Leave these untested:
  - framework built-ins (field types, enum membership, required/optional, declarative constraints, ORM basics)
  - pure data objects ("x=1 → x is 1") and a fake repository's "fields set correctly"
  - snapshots of a private map copied into the test
  - exhaustive invalid cases; test the valid cases
  - simple-composition use cases; test them through an entrypoint integration test
  - log wording; test only the functional property (run_id submit/finish pairing) and keep the wording contract in a constant comment
- MC/DC: in personal repos (linkcart etc.), give each sub-condition of a decision such as `A && (B || C)` a case where it alone flips the result with the others fixed; start from n+1 cases, and without JaCoCo-style support design the input table by hand.

## Shape

- Naming and structure: English method name (`test_rejects_invalid_status_type`), a Korean scenario docstring that says more than the name, and `# given` / `# when` / `# then` markers (`# when & then` when mixed; one legacy project uses uppercase with a short note, `# Given: 기본그룹 org + 배정그룹 org`).
- Markers beat file-local convention: give new tests the docstring and markers even when neighbouring tests lack them, and leave lightly edited existing tests as they are; split `assert call().data...` into When (`response = call()`) and Then; a routing-smoke or exception test may combine `# When / Then`; write in the Then comment only what the docstring does not say.
- Dedup and helpers: keep one of a single-field and a multi-field change test that prove the same thing; test the same rule via different fields once; put helpers (`create_draft`, `force_status`, `_make_repo_with_usecases`) in the suite's shared fixture file.
- Domain objects only in fixtures/factories: build them with `make_batch()` / `FakeRepository.for_batch(...)` instead of inline `Batch(...)`/`OrderLine(...)` in a test body.
- Fakes honour the real contract: make a fake repository behave like the real one (update of a missing row raises `NotFound` in both).

## Determinism

- Inject now: pass the current time as an optional parameter down to the use case entry, and pin it in tests.
- Deterministic tests: remove every source of nondeterminism at the test boundary:
  1. background thread/executor: replace the submit function with a synchronous one (shared by the suite when several tests need it); verify real threads only in a dedicated test that waits on an event with a timeout; wait on events/conditions instead of `sleep`
  2. time: inject now
  3. random/fake data: set every result-affecting value explicitly
  4. shared state: keep every mutable value and DB row test-local
