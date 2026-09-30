# Functions and methods

- Length: when a function passes 30–40 lines, split it by responsibility into private helpers, even ones called once or twice; step helpers may call each other.
- One reason to change: a helper does only what its name promises; put guards in the caller, whose loop skips or returns early.
- Query or command: a function either returns a value without side effects or mutates and returns nothing; split one that does both. An entity method such as `entity.change()` may mutate in memory and return the result, and a command use case or a repository `create`/`save` may return the id or entity it produces.
- Same helper N times → table + loop: turn 4+ explicit calls of one helper with different arguments into a module-constant list of argument combinations iterated in a loop.
- Inline an expression up to 100–110 characters; past that, give it a named variable.
- Defaults only where a caller omits the value: remove a parameter default once every call site passes the value explicitly.
- Collection parameters are non-nullable: pass an empty collection for "no filter"; scalars may be null.
- Explicit fields after a spread: when an explicit value must win over a same-named key in the spread, put it after the spread.
- Immutable copy: a helper that would mutate an input map or list returns a modified copy as a new object.

## Python

- Inline length decides a nested call too: `return Payload(**repo.create(entity).dict())`.
- Falsy sentinel for absent scalars: when falsy means "no filter", use `search_id: int = 0`, `search_name: str = ''`.
- Explicit fields after a spread: `Entity(**{**payload.dict(), 'explicit_field': value})`.
- Immutable copy: `dict(input)` + the modification.
- Use case class structure: make state-holding builders and UseCases classes (`PayoutStatementTree`, `PayoutStatementSummaryUseCase`); pure orchestration/fetch helpers may be module functions (`resolve_statement_scope`, `build_statement_tree`, `summarize_statement`, `_statement_*`); make an externally called method public and an internal one a private instance method; use a public `@staticmethod` only for pure state-independent computation and no private classmethod/staticmethod; keep all private helpers of one class the same kind.

## Frontend

- Set-equality utils: state "inputs contain no duplicates" in the function comment of `hasSameMembers` and friends (`[A,A,B]` and `[A,B,B]` compare equal); when duplicates must count, compare sorted copies or count maps.
