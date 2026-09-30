# Clean Code: functions, file layout, comments, naming

## Functions

- Length: when a function passes 30–40 lines, split it by responsibility into private helpers, even ones called once or twice; step helpers may call each other.
- One reason to change: a helper does only what its name promises; put guards in the caller, whose loop skips or returns early.
- Query or command: a function either returns a value without side effects or mutates and returns nothing; split one that does both. An entity method such as `entity.change()` may mutate in memory and return the result.
- Same helper N times → table + loop: turn 4+ explicit calls of one helper with different arguments into a module-constant list of argument combinations iterated in a loop.
- Inline an expression up to 100–110 characters; past that, give it a named variable.
- Defaults only where a caller omits the value: remove a parameter default once every call site passes the value explicitly.
- Collection parameters are non-nullable: pass an empty collection for "no filter"; scalars may be null.
- Explicit fields after a spread: when building from a spread plus explicit fields, put the explicit fields after the spread.
- Immutable copy: a helper that would mutate an input map or list returns a modified copy as a new object.

## File layout

- Imports go at the top of the file, test files included; resolve a circular import by restructuring modules.
- Module constants go after the imports and the logger, before the first function (`_STRATEGY_REGISTRIES`), with shared `DEFAULT_*` at the module top; make a constant only when the value means something, and keep a bare value such as zero inline.
- Interface method order: list repository/port methods in CRUD order `save` → `findBy*`/`findAll*` → `countBy*` → `existsBy*` → `deleteBy*` (or `update`/`revoke`), in the same order in every port of a project.
- Step-down order: put the public entry above its helpers, one abstraction level per step (use case `execute` on top, `_needs_requeue` below); put module-level shared helpers below the classes that call them, in call-chain order (`_publish_job_resource` above `_is_publish_stale`).
- Shared atomic helpers live at module level (`_month_range`, `fetch_org_payout_reports`), outside any use case class or base class.

## Comments and docstrings

- Why, not what: write a comment only for context the code cannot show.
- Keep:
  - external standard references (AIP-XXX, RFC NNNN, company RFC links)
  - security rationale (enumeration prevention, capability token, XSS vector blocking)
  - architecture decision + the alternatives rejected after review
  - non-obvious algorithm tricks (limit+1 hasNext, microsecond-precision cursor, base64url format)
  - disambiguation between confusable code/types ("vs" comparison)
  - hidden constraints/invariants (DB column type alignment, external API nullability assumption), external-system contracts, circular-import avoidance
  - value rationale only, e.g. `MAX_*=65535  # MySQL unsigned smallint 최대`
- Delete:
  - descriptions obvious from the signature; "X용 VO/DTO" labels on data classes
  - change history ("이전에는 Map이었으나...") → git log/PR body; caller info ("X 화면이 이걸 쓴다")
  - an identifier paraphrased (`"X 토큰을 생성한다"` over `fun generate(): String`)
  - standard pattern/control-flow narration the structure already shows: `# compare-and-set 으로 중복 claim 방지`, `# try/except 로 한 항목 실패 격리`, `# 예외 시 좀비 방지 FAILED 마감`, `# 전부 SENT면 성공 아니면 실패`, `# 도메인 status → 모델 status 변환`
  - multi-line design essays ("why safe / why this design") → PR body or plan, keeping only the line the code cannot show (the UNIQUE constraint is owned by `send_email`); a description of another function's behaviour away from its own code
  - references to deleted migrations (`시드 migration 0108`), fail-fast notes, roadmap/follow-up notes
- Docstrings follow the same rule: delete one that restates the name (`mark_in_progress` → "Start (or restart) this run", `approve` → "Approve payout") and keep one only for why/context; test docstrings follow `~/.claude/lib/coding/tdd.md`.
- Language: write comments and docstrings in Korean, identifiers and test names in English.

## Naming

- Ubiquitous language: use the term the codebase or glossary already uses, one word per concept.
- Functions and methods start with a verb naming the business action (`send_payout_email`, `approve`); a property or computed attribute may be a noun (`total_amount`). Keep mechanism words (async, thread, batch, cron, retry, worker) out of the name: `send_payout_email` over `run_email_batch`.
- Positive predicates: `can_*`/`is_*`/`has_*` (entity `can_retrigger()`); when negation is needed, keep the predicate positive and negate at the call-site guard (`if not …: continue`).
- Intention-revealing, searchable names: `remaining_budget`, a named constant instead of a magic number, single letters only in lambdas and comprehensions.
- Model field names follow the DB column names.
- Enum naming: model enum without suffix (`CampaignStatus`) vs domain enum with a `Type` suffix (`CampaignStatusType`); infrastructure converts by value (`ModelEnum(domain_enum.value)`).
