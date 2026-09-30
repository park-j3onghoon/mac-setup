# File layout

- Imports go at the top of the file, test files included; resolve a circular import by restructuring modules.
- Module constants go after the imports and the logger, before the first function (`_STRATEGY_REGISTRIES`), with shared `DEFAULT_*` first among them.
- Interface method order: list repository/port methods in CRUD order `save` → `findBy*`/`findAll*` → `countBy*` → `existsBy*` → `deleteBy*` (or `update`/`revoke`), in the same order in every port of a project.
- Step-down order: put the public entry above its helpers, one abstraction level per step (use case `execute` on top, `_needs_requeue` below); put shared atomic helpers (`_get_month_range`, `fetch_org_payout_reports`) at module level, outside any use case class or base class, below the classes that call them in call-chain order (`_publish_job_resource` above `_is_publish_stale`).

## Python

- `__init__.py` stays empty.
