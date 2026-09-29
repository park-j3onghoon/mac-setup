# File layout: where code sits inside a file

- Imports at the top of the file, test files included; resolve a circular import by restructuring modules so every import stays at the top.
- Module constants go after the imports and the logger, before the first function (`_STRATEGY_REGISTRIES`), with shared `DEFAULT_*` at the module top; make a constant only when the value means something, and keep a bare value such as zero inline.
- Interface method order: list repository/port methods in CRUD order `save` → `findBy*`/`findAll*` → `countBy*` → `existsBy*` → `deleteBy*` (or `update`/`revoke`), the same order in every port of a project so the main entrypoint is found at a glance.
- Step-down order: the public entry sits above its helpers, one abstraction level per step (use case `execute` on top, `_needs_requeue` below); module-level shared helpers sit below the classes that call them, in call-chain order (`_publish_job_resource` above `_is_publish_stale`).
- Shared atomic helpers live at module level (`_month_range`, `fetch_org_payout_reports`), outside any use case class or base class, because a base class must sit above its subclasses and breaks step-down order.
