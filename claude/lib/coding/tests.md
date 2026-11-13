For Python code, also Read `~/.claude/lib/coding/tests-python.md`; for frontend code, `~/.claude/lib/coding/tests-frontend.md`.

## Cycle and scope

- Red / green / refactor: write a failing test first, then the minimal code that passes it, then refactor while the tests stay green. When running the code or looking at the screen verifies a behaviour more directly than a test (a layout, a deploy step, a one-off script), verify it that way and record the command or screen and its result.
- Tests in sentences: before writing tests, write one sentence per check, and name the single most important test of the change.
- Test at the seams: assert behaviour through the public interface (the use case entry, a port, HTTP), and test a simple-composition use case through an entrypoint integration test; test an extracted function or internal map through what calls it, while a transition map, a `*Validator` and a value object may be tested directly.
- Cover the change: give every behaviour the change adds or modifies a test at its public seam; the Leave untested list below holds the only exceptions.
- Results over steps: a UI test checks the screen shown after the action succeeds; two screens of the same action get tests of the same shape.
- Sending once: for code that sends (mail, notification, payment), test first that a resend, a restart and a manual send overlapping each other send once.
- External services: replace calls to AI and other external services with a double at the call path; keep a test that calls a real external service in a separate script outside the suite.
- Refactoring equivalence: identify the outputs, writes, error conditions and external/persisted contracts that must remain unchanged, including enum values, serialization and verification tokens/signatures. Verify with existing behavioural tests or representative before/after comparisons proportional to risk; distinguish approved differences from unverified cases. Green tests alone do not prove equivalence, and changing expected values is not evidence of preservation.
- Before deploy: when a change touches a shared path (code that many flows pass through), compare its before/after outputs on production data read-only before deploying, in addition to the checks after deploy.
- Before commit: for code changes, run the changed modules' full tests on the final code, read the output itself (counts, failures, warnings) and fix failures before creating a commit; after a file move or import-path change, run the project build too; run a migration that uses DBMS-specific SQL on that DBMS; check a screen change in a browser and measure the sizes and positions it changes. Record the commands and results. If required local checks cannot run, report the blocker and leave the changes uncommitted. When the full suite runs only in CI, pass the runnable local checks and retain the CI gate.
- Leave untested: before copying a test layer, ask "is this testing our code or the framework?". Leave these untested, and delete existing tests of these kinds in the test files the change touches:
  - framework built-ins (field types, enum membership, required/optional, declarative constraints, ORM basics)
  - pure data objects ("x=1 → x is 1") and a fake repository's "fields set correctly"
  - snapshots of a private map copied into the test
  - exhaustive invalid cases; test the valid cases
  - log wording; test only the functional property (run_id submit/finish pairing) and keep the wording contract in a constant comment
- MC/DC: in personal repos (linkcart etc.), give each sub-condition of a decision such as `A && (B || C)` a case where it alone flips the result with the others fixed; start from n+1 cases, and without coverage-tool support design the input table by hand.

## Shape

- Naming and structure: English method name (`test_rejects_invalid_status_type`), a Korean scenario docstring that says more than the name, and `# given` / `# when` / `# then` markers (a routing-smoke or exception test may combine them as `# when & then`; in a project whose tests already write the markers in uppercase with a short note, keep that form, `# Given: 대출 중인 책 + 반납된 책`).
- One flow per test: put the assertions of one flow (one input and everything it changes) in one test, and give separate flows separate tests.
- Markers: follow the form the test file already uses; in a file without an established form, give new tests the docstring and markers. Leave an existing test's docstring and markers as they are when your change edits only part of its body; split `assert call().data...` into When (`response = call()`) and Then; write in the Then comment only what the docstring does not say.
- Dedup and shared setup: keep one of a single-field and a multi-field change test that prove the same thing; test the same rule via different fields once; put functions several tests share (`create_loan`, `set_loan_state`, `_make_repo_with_usecases`) in the suite's shared fixture file.
- Domain objects only in fixtures/factories: build them with `make_batch()` / `FakeRepository.for_batch(...)` instead of inline `Batch(...)`/`OrderLine(...)` in a test body.
- Test doubles: give a port that holds state a fake (a working in-memory implementation), a call that only needs an answer a stub (a fixed return value), and use a mock (a check on the call itself) only when the call is the outcome (an email sent exactly once).
- Fakes honour the real contract: make a fake repository behave like the real one (update of a missing row raises `NotFoundError` in both).

## Determinism

- Deterministic tests: remove every source of nondeterminism at the test boundary:
  1. background thread/executor: replace the submit function with a synchronous one (shared by the suite when several tests need it); verify real threads only in a dedicated test that waits on an event with a timeout; wait on events/conditions instead of `sleep`
  2. time: have the use case entry take the current time as a parameter or an injected clock, pin it in tests, and derive other times in the test as offsets from it
  3. random/fake data: set every result-affecting value explicitly, the value before a change included
  4. shared state: keep every mutable value and DB row test-local; each test passes alone and in any order
