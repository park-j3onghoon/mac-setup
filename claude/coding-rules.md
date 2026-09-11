# Coding Rules: core (every language, every project)

Read this file before writing or modifying code, then read the specifics file for the stack you touch: `coding-rules-python.md` (Python / Django / DRF / Pydantic / pytest), `coding-rules-frontend.md` (React / Vue / TS; Vue + Example main projects such as admin-center also read `coding-rules-vue.md`), `coding-rules-db.md` (MySQL schema). Tool and project know-how stays in memory (`reference_tool_{tool}.md`, `project_{name}.md`). Updated by `/review` Step 9 or by hand.

## 0. Precedence

- **Quality ladder**: Architecture > Module > Class/Object > Function > Naming; when two rules conflict, apply the higher level (a Function rule such as "prefer inline" never justifies breaking the Module rule "no cross-usecase calls").
- **Cross-cutting sections** (Errors, Comments, Tests, Simple Design & Refactoring, Change discipline) apply at every rung of the ladder.
- **Specifics files** (`coding-rules-python.md`, `coding-rules-frontend.md`, `coding-rules-db.md`) add stack detail inside their own scope and never override a rule here; a narrowing is allowed (Python's falsy-sentinel scalars), a contradiction is not.
- **Paradigms** behind these rules: Clean Architecture, Hexagonal (Ports & Adapters), DDD, CQRS/CQS, TDD, Kent Beck Simple Design; a rule tagged (canon) comes from that canon rather than from a past review.

## 1. Architecture

- **Dependency rule**: point every dependency inward: `presentation → application → domain`, and `infrastructure → domain` by implementing the ports the domain defines (DIP); the domain depends on nothing, infrastructure never imports application implementation, and the domain is designed first, never bent to fit a repo signature.
- **Layering** (canon, Cosmic Python): route every request entrypoint (view, servicer, CLI, consumer) → service layer (use case) running inside a unit of work → domain model, with adapters (repositories, gateways, email, publishers) implementing the ports; a use case never touches the ORM or an HTTP client directly.
- **Thin entrypoint**: let a view/servicer only build the use case, map request → payload, call `execute`, and map result → response; even List/Retrieve get their own use case, so no entrypoint calls a repository directly (DRF shape: `coding-rules-python.md` "View shape").
- **Aggregate** (canon): treat one aggregate as one consistency boundary: a unit of work modifies one aggregate root per transaction and references other aggregates by id, never through an object graph.
- **Domain event / message bus** (canon): raise a cross-aggregate side effect (send the approval email, bump a counter on another aggregate) as a domain event on the aggregate and handle it after the unit of work commits, never inline from the first aggregate.
- **CQRS / CQS at the boundary**: give a command its side effects and a minimal return (id/status) and a query no side effects; split read and write models when their shapes or paths diverge, and give an externally served query endpoint its own read model rather than a repository projection.
- **Bounded context** (canon): keep each service/module's own terms and model and translate at the boundary (anti-corruption mapping in the adapter) instead of importing another context's entity or enum into the domain.
- **Validation ladder**: place each check where its criterion lives (type → ①, single value → ②, relation → ③), because one place for everything (all in a DRF Serializer) ties the domain to one entrypoint and misses the next one:
  1. **Type/format → entrypoint** (DRF Serializer, View, Controller): "does raw input parse to the right type": `"abc"` → int fails with 400; (de)serialization lives here and the domain/service never sees JSON or HTTP.
  2. **Single-value invariant → value object constructor**: "is this one value valid": `Quantity(-5)` is rejected in `__post_init__`; this is the last line of defence, kept even when the entrypoint duplicates it (entrypoints multiply: HTTP, CLI, queue, batch, tests).
  3. **Relational rule → domain behaviour**: "given several objects' state, may this operation run": `line.qty > batch.available_quantity` in a `can_xxx()` query or guard raising a domain exception (`OutOfStock`) that the entrypoint translates to an HTTP status.
  - Scope: apply when domain rules are rich; skip for simple CRUD or a thin gateway layer (payments-api gRPC gateway).
- **State stored, not resolved**: persist an explicit state field instead of computing status from other fields; an event-driven action (send an email once) cannot be judged from resolve, and resolve gives a snapshot with no history.
- **Transition diagram first**: fix the transition diagram and terminal conditions before any state design (states rarely change later) and require the diagram before reviewing one.
- **State machine shape**: keep one transition map as the single source of truth, a shared `_transition_to` guard, and named `mark_*` methods carrying intent and per-state logic; expose the map for test reuse so adding a transition is one map line, and guard only transitions that can actually happen, since a guard for a system-impossible state is noise.
- **Gateway / BFF / adapter**: transform and forward only; defaults, field merge/preserve and invariants stay in the service that owns the domain, because a caller-side read-modify-write to "preserve missing fields" scatters the rule, races under concurrency and drifts.
- **Verify before build**: read the dependent service's actual write/merge/error behaviour (its proto, entity, repo, especially cross-repo) before adding RMW field preservation, default mapping or error translation on the caller side; an assumed contract ("upsert is full-replace") turns into partial updates and silently dropped fields.
- **Repository contract**: return aggregates/entities through a domain-defined port by default and allow count/summary/id projections explicitly (Evans DDD; ISP). Do count/existence via a projection method returning e.g. `list[int]` instead of hydrate-then-discard; the return type itself says "projection" (no comment needed) and suits command-internal computation such as a progress denominator.
- **Repo stores the entity as-is**: keep the modifiable-field whitelist/blacklist in the usecase and let infra strip only `id`/`created_at`/`updated_at`; a repo that judges which fields may change blocks approve/reject/cancel usecases from sharing one `update()`; express such rules through DTO design, usecase branching or entity routing.
- **Pagination meta in application**: the repo takes `limit`/`offset` and returns `count` + `items`; compute `num_pages`/`has_next`/`has_previous`/page number in the usecase; a repo that knows `page_number`/`page_size` has a business contract leaking into infra.
- **Timezone anchoring**: when a repo anchors a received `date` to a zone's midnight (`arrow.replace(tzinfo='Asia/Seoul').floor('day')`), pass the calendar date in that zone (`astimezone(tz).date()`); a UTC tz-aware `.date()` alone is off by one during UTC 15:00–23:59; check the repo's actual internals, not its comments or types.
- **`_to_entity` normalization asymmetry**: normalizing raw DB values on read (`schedule/live/pause/close` → canonical `APPROVE`) collides on write when the canonical value is absent from the DB EnumField; normalize in the response payload layer instead, or keep the raw value in the entity and expose the normalized view as a separate field/property.
- **Timeouts**: set explicit connect/read timeouts on every HTTP/gRPC/SMTP/external call (Django `EMAIL_TIMEOUT`, requests `timeout=`, gRPC `timeout=`), above all while a DB transaction or lock is held, so lock hold time never depends on a remote's latency.
- **Lock across network by workload**: with a single-worker batch + rare manual trigger + single-purpose low-contention row, hold `select_for_update` through the SES call (lock-during-send), simpler than a SENDING/IN_PROGRESS state plus reaper, since InnoDB `FOR UPDATE` blocks only locking reads/writes (plain reads use the MVCC snapshot) and releases on session death; with high concurrency (multiple workers) use a committed SENDING state + compare-and-set without a lock.
- **Dedup read under `FOR UPDATE`**: lock all candidate rows and decide after the lock is held; a status filter in the locking read drops a row that turned SENT while waiting and opens a "none, create new" hole.
- **Check-then-insert**: serialize with `GET_LOCK`, a unique constraint or a single entry point; a status value cannot stop a concurrent INSERT.
- **Extension by addition (OCP)**: when the same branch keeps being edited for each new case, introduce a strategy/polymorphism/port so the next case is added code, not modified code.
- **Tracer bullet / vertical slice** (canon): deliver one thin end-to-end slice (entrypoint → usecase → repo → DB → test) first and widen from there, never a whole layer at a time.
- **Ideal architecture first**: propose the ideal DDD/Clean/Layered/CQS/Simple-Design structure first, compare candidates when several are ideal, state scope/legacy/schedule compromises separately afterwards, and never call something "excessive" or "complex" without grounds; check every model design for dependency direction and store-vs-resolve.

## 2. Module

- **Deep module** (canon): offer a small interface over a deep implementation: `repo.save(entity)` hiding ORM mapping, enum conversion and system-field stripping beats `save_fields(dict, mask)` that pushes the work onto every caller.
- **One-way dependencies**: A references B ⇒ B never knows A; a cycle nullifies the split.
- **Imports at the top** of the file, test files included; resolve a circular import by restructuring modules, never by moving the import into a function.
- **Domain vs application placement**: a rule true in every use case → domain (`can_transition_to()`, where APPROVE→DRAFT is never allowed; entity field constraint `title max_length=15`); a rule true only in one flow → application ("all fields required on submit" while a draft may be empty; "start date 2 business days ahead" on create/update); split constants and exceptions the same way (`domain/constants` vs `application/constants`).
- **Module constants** go after imports + logger and before the first function (`_STRATEGY_REGISTRIES`), shared `DEFAULT_*` at module top; make a constant only when the value means something; `_ZERO = Decimal('0')` is inlined as `Decimal('0')`.
- **Interface method order**: list Repository/Port methods in CRUD order `save` → `findBy*`/`findAll*` → `countBy*` → `existsBy*` → `deleteBy*` (or `update`/`revoke`), the same order in every port of a project so the main entrypoint is found at a glance.
- **Abstraction discipline**: extract the same *knowledge* (a business decision, a discriminating rule) at its 2nd occurrence into its domain module; let a formatting/conversion helper that would become a cross-module shared util wait for the Rule of Three / AHA (Avoid Hasty Abstractions), because a wrong coupling costs more than a little duplication; keep a 1-call-site helper when it is a single defence point (encapsulating `as unknown as T` or a drift guard); same-module step helpers are never "over-abstraction" (Function "Length"); in doubt, keep it local.
- **Requested scope only**: add only the structure the task asked for and ask before introducing a ClassVar, helper or layer that did not exist; "why did you add this?" ends in a revert.
- **Team-norm caution**: a shared helper/orchestrator/new layer absent from team practice draws reviewer resistance even past the Rule of Three. Check sibling modules (livecommerce, collaborative) first; if absent, infer why inline/duplication was chosen, confirm the benefit clearly beats resistance + learning curve, start inside one module and propose spreading later, and revert to inline at once on "over-utilized" (that revert is cheap).
- **No cross-usecase calls**: usecase A never calls usecase B; reuse only shared atomic validators (`validate_campaign_request_ownership`, `validate_status_transition`); a lookup repeated across usecases is inlined or given its own private helper.
- **Shared atomic helpers at module level** (`_month_range`, `fetch_org_payout_reports`), never inside a usecase class or a base class, because a base class must sit above its subclasses and breaks step-down order.

## 3. Class / Object

- **SRP**: one reason to change; split a usecase that validates ownership and also renders the notification email.
- **OCP**: see Architecture "Extension by addition".
- **LSP**: make a Fake repository honour the real one's contract (update of a missing row raises `NotFound` in both) so tests and production agree.
- **ISP**: expose narrow port methods (`count_by_status()`) instead of forcing a caller to take `find_all()` for a count.
- **DIP**: a usecase depends on the port abstraction and infrastructure implements it, never the reverse.
- **Value object** (canon): immutable, equal by value, invariants enforced in the constructor (Architecture "Validation ladder" ②).
- **Always-valid entity**: check state transitions inside entity methods and raise a domain exception on an invalid one; never rely on caller checks, which scatter invariants and get missed.
- **Rich domain** (canon): put behaviour that reads or changes an entity's state on the entity (`payout.approve(now)`), not as `if` chains over its fields in a usecase; an anemic entity is acceptable only for plain CRUD.
- **Tell, don't ask / Law of Demeter** (canon): call `order.mark_paid(now)` instead of reading `order.status` and assigning from the usecase; a method talks to its own fields, its parameters and objects it creates, with no `a.b().c().d()` chains.
- **Composition over inheritance** (canon): share behaviour through a collaborator or strategy object, not a base usecase class.
- **Make illegal states unrepresentable**: model a kind/state/mode argument as an enum even with two values (`kind=ExitKind.STOP_LOSS`, not `f(is_take_profit=False)` whose `False` cannot be read as "absent" vs "stop-loss kind"); two booleans (`is_tp` + `is_sl`) create (True,True)/(False,False) contradictions → one enum; an Optional field plus a same-root boolean (`take_profit: Decimal | None` + `is_take_profit`) mixes existence with kind → one field; fields that travel with a variant form a discriminated union (`coding-rules-frontend.md` "Types") and a constrained value gets a constrained type (`coding-rules-python.md` "Types").
- **Boolean only for a true on/off flag** (`verbose`, `dry_run`); when reading any boolean, first name the axis it answers; `False` is the opposite pole of that axis, not "absent".
- **Usecase class structure**: state-holding builders and UseCases are classes (`PayoutStatementTree`, `PayoutStatementSummaryUseCase`); pure orchestration/fetch helpers may be module functions (`resolve_statement_scope`, `build_statement_tree`, `summarize_statement`, `_statement_*`); externally called → public, internal → private instance method, public `@staticmethod` only for pure state-independent computation, never a private classmethod/staticmethod, and all private helpers of one class are one kind.
- **CQS with the entity exception**: accept `Entity.change()` mutating in memory and returning the result (DDD / cosmicpython); everywhere else keep Query and Command apart (Function "SRP + CQS per helper").
- **Immutable copy**: a helper that would mutate a dict/list returns `dict(input)` + modification as a new object.
- **dataclass vs dict**: keep dict kwargs for an entity API in sentinel style (`None` = no change, `unset_xxx` = explicit unset), which distinguishes "explicitly set" from "default"; adopt a dataclass only together with an `UNSET` sentinel / separate-method refactor.
- **Explicit validation over framework magic**: put checks in a `*Validator` class with `@classmethod validate_<field>(value) -> None` and plain `if ...: raise <Domain>InvalidArgumentError` (benefit_contract / booster_contract), called from both repo `create`/`update` and the entity `@validator` that returns the value unchanged (Django model/assignment bypasses validators, so the repo call is mandatory); the Fake repo mirrors the same calls (2-track), tests call the `*Validator` directly, and the entity validator is never dropped as "low-value re-validation"; since `to_entity()` validates on every read, confirm seed/existing rows pass first.
- **Validators never replace the value**: avoid pydantic `constr(...)` and any `@validator` whose return value replaces the field (even `return v.strip()`); a check-raise-return-unchanged validator is fine; strip/normalize at the entrypoint (servicer/view) or not at all, rejecting whitespace-only input via `if not x.strip()` without changing the value.

## 4. Function

- **Length**: 30–40 lines soft limit (Bob Martin < 20, Google soft 40); past it, split by responsibility into private helpers (Composed Method); a helper called only 1–2 times still earns its name, and private → private calls between step helpers are fine (2026-05-19 reversal on the 140-line `batch_update_unit_contracts`).
- **Step-down order**: public main above, helpers below, one abstraction level per step: usecase `execute` on top and `_needs_requeue` below; module-level shared helpers below the usecase classes in call-chain order (`_publish_job_resource` above `_is_publish_stale`); Python's late binding makes helper-after-caller safe.
- **SRP + CQS per helper**: one reason to change; a Query (returns a value, no side effect) and a Command (mutates, returns nothing) never share a function; split one that does both.
- **Guards belong to the caller**: `_verify_value(field, value, registry)` does not open with `if field not in mask: return` / `if not value: return`; the caller loop `continue`s or returns early and the helper does only what its name promises.
- **Same helper N times → table + loop**: turn 2+ explicit calls of one helper with different arguments into an `(argument combination)` list as a module constant iterated in a for-loop; 4 calls + 2 similar mapping-validation calls is where readability tips.
- **Inline up to 100–110 chars**, otherwise a named variable; `return Payload(**repo.create(entity).dict())` is decided by its length.
- **No unnecessary defaults**: remove a parameter default once every call site passes the value explicitly (UI defaults in API payloads: `coding-rules-frontend.md` "UI defaults are FE responsibility").
- **Collection params non-nullable**: an empty collection means "no filter"; scalars may be `None` (Python narrowing: `coding-rules-python.md` "Types").
- **kwargs override order**: put explicit parameters after the spread (`Entity(**payload.dict(), explicit_field=value)`) so the explicit value always wins over a same-named payload key.

## 5. Naming

- **Ubiquitous language**: use the term the codebase/glossary already uses, one word per concept; never `org` here and `publisher` there for the same thing.
- **Function name = business role**: `send_payout_email`, never `send_payout_email_async`/`_in_thread`; mechanism words stay out of the name.
- **Model field = DB column** so a debugging query maps 1:1.
- **Positive predicates**: `can_*`/`is_*`/`has_*` over `blocks_*`/`*_unfinished` (entity `can_retrigger()`); when negation is needed, keep the predicate positive and negate at the call-site guard (`if not …: continue`).
- **Intention-revealing, searchable names** (canon): `remaining_budget` not `rb`, a named constant not a magic number, single letters only in comprehensions/lambdas.
- **Enum naming**: model enum without suffix (`DisplayCampaignStatus`) vs domain enum with `Type` suffix (`DisplayCampaignStatusType`); infra converts via `ModelEnum(domain_enum.value)`.
- **Enum zero value by direction**: a server-filled output/stored enum puts a real domain value at 0 (`STATUS_PLANNED=0`, `PAYOUT_EMAIL_STATUS_PENDING=0`, `PayoutStatus.DRAFT=0`), 1:1 with the DB default and with no UNSPECIFIED in the domain enum; a client-filled input discriminator/view selector keeps `_UNSPECIFIED=0` so an unset value is rejected (INVALID_ARGUMENT) or defaulted; when an enum flips input ↔ output, flip its 0 policy too (ISSUE-000 restored `ACTION_UNSPECIFIED=0`).

## 6. Errors

- **Not-found**: `update`/`delete` on a missing target raise a domain exception (`NotFound`/`EntityNotFound`) and drop `| None` from the return type; `find`/`search` may return `None`. Criterion: the caller expects absence → `None`, existence is a precondition → exception.
- **404 vs 200 + null**: `GET /resources/{id}` → 404 (`NotFound`, REST standard); a condition-based single lookup ("the in-progress amendment") → 200 with a null field, because "looked, none" is a normal path.
- **Catch-all handlers** return a fixed response and log the original error; raw error text never reaches the client (Python cue: `coding-rules-python.md` "Errors").
- **Unreachable branch**: in a pure function return a safe fallback with the comment `정상 경로 도달 불가: ...`; in an async/event handler `throw new Error('unreachable: ...')` so Sentry/console can trace it, because a silent return is a silent failure with no user feedback.
- **Batch/loop failure aggregation**: collect per-item failures and log once after the loop with `logger.error('... %d failed: %s', n, {id: 메시지})` instead of logging each item; this loses per-item `logger.exception` tracebacks, so persist each failed item in a terminal state (run FAILED) for monitoring/reprocessing; nested loops aggregate per level (run loop, org loop), and a claimed item is closed to a terminal state on exception so no zombie stays "in progress".
- **Message style**: English + resource name + id (`raise NotFoundError(f'Campaign request not found: id={request_id}')`, `raise NotFoundError(f'Campaign creative not found: displaycam_id={displaycam_id}')`), with domain exceptions `NotFoundError`/`NotAllowedError`/`ValidationError`; keep usecase context out (stack trace/APM has it) and let the FE map to Korean.

## 7. Comments

- **Why, not what**: default to no comment, since identifiers and signatures carry the "what"; self-check "would a future reader be confused without it?" and delete when the answer is no.
- **Keep** (context the code cannot show):
  - external standard references (AIP-XXX, RFC NNNN, company RFC links)
  - security rationale (enumeration prevention, capability token, XSS vector blocking)
  - architecture decision + the alternatives rejected after review
  - non-obvious algorithm tricks (limit+1 hasNext, microsecond-precision cursor, base64url format)
  - disambiguation between confusable code/types ("vs" comparison)
  - hidden constraints/invariants (DB column type alignment, external API nullability assumption), external-system contracts, circular-import avoidance
  - value rationale only, e.g. `MAX_*=65535  # MySQL unsigned smallint 최대`
- **Delete**:
  - descriptions obvious from the signature; "X용 VO/DTO" labels on data classes
  - change history ("이전에는 Map이었으나...") → git log/PR body; caller info ("X 화면이 이걸 쓴다") → goes stale
  - an identifier paraphrased (`"X 토큰을 생성한다"` over `fun generate(): String`)
  - standard pattern/control-flow narration the structure already shows: `# compare-and-set 으로 중복 claim 방지`, `# try/except 로 한 항목 실패 격리`, `# 예외 시 좀비 방지 FAILED 마감`, `# 전부 SENT면 성공 아니면 실패`, `# 도메인 status → 모델 status 변환`
  - multi-line design essays ("why safe / why this design") → PR body or plan (a 4-line get_or_create justification shrinks to the one line the code cannot show: the UNIQUE constraint is owned by `send_email`); another function's behaviour is never described away from its own code
  - references to deleted migrations (`시드 migration 0108`), fail-fast notes, roadmap/follow-up notes
- **Docstrings follow the same rule (CRITICAL, often broken)**: delete `def mark_in_progress(self): """Start (or restart) this run"""` and avoid `"""Approve payout"""` (payout.py) in new code; a docstring stays only for "why/context"; test docstrings are the one exception (Tests "Naming and structure").
- **Language**: write comments and docstrings in Korean, identifiers and test names in English; an English "what" comment is a double violation.
- **Review shrinks only**: a review AUTO-FIX may shorten or delete a comment, never expand one "for accuracy".
- **Proto files carry shape and signatures only**: contract, validation and rationale live in server code, the PR body and Linear; the one exception is the "why" of a structure that looks like a mistake (an intentionally empty `Foo {}`), removed as soon as a field arrives; `*_UNSPECIFIED = 0` is a value, not a comment.

## 8. Tests (TDD)

- **Red / green / refactor** (canon): write the failing test as the contract first, the minimal code that passes, then refactor under green.
- **Test at the seams** (canon): assert behaviour through the public interface (usecase `execute`, port, HTTP); a private helper or internal dict is exercised through what calls it.
- **Naming and structure**: English method name (`test_rejects_invalid_status_type`), a Korean scenario docstring that is not a name tautology, and `# given` / `# when` / `# then` markers (`# when & then` when mixed; mobile-app uses uppercase with a short note, `# Given: 기본그룹 org + 배정그룹 org`); the deliberate opposite of the production docstring rule, because intent does not show from asserts.
- **Markers beat file-local convention**: new tests carry the docstring and markers even when neighbouring tests do not, while lightly edited existing tests stay untouched; split `assert call().data...` into When (`response = call()`) and Then; a routing-smoke or exception test may combine `# When / Then`; the Then comment never echoes the docstring.
- **Do not test**: ask "is this testing our code or the framework?" and check the sister module's test practice before copying a layer:
  - framework built-ins (field types, Enum, required/optional, Pydantic `Field(gt=0)`, frozenset membership, Django ORM basics)
  - pure data objects ("x=1 → x is 1") and Fake-repo "fields set correctly"
  - snapshots (private dict copy-paste that breaks on refactor)
  - exhaustive invalid cases (set/dict "not in" is a runtime test; valid cases prove the rule)
  - simple-composition UseCases (View/Controller integration via APIClient covers them)
  - log wording (only the functional property, e.g. run_id submit/finish pairing; the wording contract lives in a constant comment)
- **Dedup and helpers**: keep one of a single-field and a multi-field change test proving the same thing; the same rule via different fields is one test; helpers (`create_draft`, `force_status`, `_make_repo_with_usecases`) live in conftest (vitest: shared helper).
- **Domain objects only in fixtures/factories** (Cosmic Python "keep all domain dependencies in fixture functions"): `make_batch()` / `FakeRepository.for_batch(...)`, never inline `Batch(...)`/`OrderLine(...)` in a test body, so a constructor change touches one place.
- **Inject now**: time-dependent code takes `now` as an optional parameter down to usecase `execute` and tests pin it (mechanics: `coding-rules-python.md` "Time").
- **No flaky tests (CRITICAL)**: remove every source of nondeterminism at the test boundary; self-check "same result over 1,000 runs and on a slow CI machine?":
  1. background thread/executor: patch the submit function to run synchronously (autouse fixture when shared, as in payments-api `run_analysis_recalc_inline`), verify real threads only in a dedicated `threading.Event.wait(timeout)` test, wait on events/conditions never `sleep`
  2. time: inject `now`
  3. random/Faker: set every result-affecting value explicitly (Faker unique-constraint seed failures happened)
  4. shared state: no module-level mutables, leftover DB rows or order coupling
- **MC/DC for personal repos only** (linkcart etc.): in `A && (B || C)` each sub-condition flips the decision alone with the others fixed; branch coverage 100% is not enough, n+1 cases usually suffice, and with no JaCoCo-style support the input table is designed by hand; not applied to company repos.
- **Test-only attributes** (`data-testid`) ship in the same PR as the test that queries them (`getByTestId`); otherwise defer the attribute (YAGNI).

## 9. Simple Design & Refactoring

- **Four rules** (Kent Beck, in priority order): ① tests pass ② reveals intention ③ no duplication ④ fewest elements.
- **DRY of knowledge only**: give every fact/decision one source of truth, but leave code that merely looks alike and changes for different reasons (accidental duplication) apart (how much to extract: Module "Abstraction discipline").
- **YAGNI**: build nothing not needed now; defensive logic without PRD/design basis (a cancel-confirmation modal) is left out unless it prevents irreversible user loss; pre-extracting shared code for a planned later PR is a planned split, not a YAGNI violation.
- **KISS**: the simplest thing that works; remove accidental complexity before adding structure.
- **Two hats** (canon): one change either restructures (behaviour unchanged, tests untouched) or changes behaviour (tests change), never both in one commit.
- **Make the change easy, then make the easy change** (canon): when a feature is hard to add, first refactor under green until it is easy, then add it in its own commit.

## 10. Change discipline

- **Existing patterns first**: before proposing a change, `grep -r "<pattern>" adscenter/ --include="*.py"` across sibling modules (id field `default=0`/`gt=0`, `VALID_TRANSITIONS` public/private, `Error` vs `Exception` naming); when the existing pattern differs from the ideal, show both and let the user decide; existing code is not automatically right (livecommerce section-footer placement), so no blind copying.
- **Verify current code before asking**: confirm the target code is not already doing X before proposing X, and frame the question as "currently A, livecommerce does B. Switch or keep?".
- **Review-agent suggestions**: added `assert`s, a duplicate `updated_count` check and a manual `updated_at` were reverted 3 times. Grep the module and its siblings first and route new defensive code to ASK.
- **Verify file state** with `git diff --name-only` / `ls` / `git status` before saying a file exists, changed or was deleted; branch switches and merges change the state.
- **Tests before push**: run the tests of every changed module; a runtime-only error such as the `TYPE_CHECKING` `NameError` passes mypy and the build and fails only in pytest.
- **Build check after moves/import changes**: after `git mv` or an import-path change, check the moved file's relative imports, prefer absolute path aliases (`lib/`, `modules/`), and run `npm run build` (or the project's build); jest resolves leniently, vite/webpack does not (`./escape-html` CI failure); tests passing ≠ build passing.
- **Branch check before commit/merge**: run `git branch --show-current` first in any session that switches branches; a commit on the wrong branch costs a reset and rework.
