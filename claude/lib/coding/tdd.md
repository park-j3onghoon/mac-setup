# TDD: tests

## Cycle and scope

- Red / green / refactor: write the failing test as the contract first, then the minimal code that passes, then refactor under green.
- Test at the seams: assert behaviour through the public interface (use case entry, port, HTTP); a private helper or internal map is exercised through what calls it.
- Cover the change: every behaviour the change adds or modifies gets a test at its public seam; the Leave untested list below names the only exceptions.
- Leave untested: ask "is this testing our code or the framework?" and check the sister module's test practice before copying a layer:
  - framework built-ins (field types, enum membership, required/optional, declarative constraints, ORM basics)
  - pure data objects ("x=1 → x is 1") and a fake repository's "fields set correctly"
  - snapshots (a private map copied into the test, which breaks on refactor)
  - exhaustive invalid cases (a "not in" check is a runtime test; valid cases prove the rule)
  - simple-composition use cases (an entrypoint integration test covers them)
  - log wording (only the functional property, e.g. run_id submit/finish pairing; the wording contract lives in a constant comment)
- MC/DC for personal repos only (linkcart etc.): in `A && (B || C)` each sub-condition flips the decision alone with the others fixed; 100% branch coverage is not enough, start from n+1 cases, and without JaCoCo-style support design the input table by hand.

## Shape

- Naming and structure: English method name (`test_rejects_invalid_status_type`), a Korean scenario docstring that is not a name tautology, and `# given` / `# when` / `# then` markers (`# when & then` when mixed; one legacy project uses uppercase with a short note, `# Given: 기본그룹 org + 배정그룹 org`); this is the deliberate opposite of the production docstring rule, because intent does not show from asserts.
- Markers beat file-local convention: new tests carry the docstring and markers even when neighbouring tests do not, while lightly edited existing tests stay untouched; split `assert call().data...` into When (`response = call()`) and Then; a routing-smoke or exception test may combine `# When / Then`; the Then comment adds what the docstring does not say.
- Dedup and helpers: keep one of a single-field and a multi-field change test proving the same thing; the same rule via different fields is one test; helpers (`create_draft`, `force_status`, `_make_repo_with_usecases`) live in the suite's shared fixture file.
- Domain objects only in fixtures/factories: `make_batch()` / `FakeRepository.for_batch(...)` instead of inline `Batch(...)`/`OrderLine(...)` in a test body, so a constructor change touches one place.
- Fakes honour the real contract: a fake repository behaves like the real one (update of a missing row raises `NotFound` in both), so tests and production agree.

## Determinism

- Inject now: time-dependent code takes the current time as an optional parameter down to the use case entry, and tests pin it.
- Deterministic tests: remove every source of nondeterminism at the test boundary so a test gives the same result in any order and on any machine:
  1. background thread/executor: replace the submit function with a synchronous one (shared by the suite when several tests need it); verify real threads only in a dedicated test that waits on an event with a timeout; wait on events/conditions, never `sleep`
  2. time: inject now
  3. random/fake data: set every result-affecting value explicitly
  4. shared state: keep every mutable value and DB row test-local
