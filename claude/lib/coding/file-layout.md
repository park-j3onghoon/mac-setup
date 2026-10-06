# File layout

For Python code, also Read `~/.claude/lib/coding/file-layout-python.md`.

- Imports go at the top of the file, test files included; resolve a circular import by restructuring modules.
- Module constants go after the imports and the logger, before the first function (`_EXPORTERS_BY_FORMAT`), with shared `DEFAULT_*` first among them.
- Interface method order: list repository/port methods in CRUD order `save` → `findBy*`/`findAll*` → `countBy*` → `existsBy*` → `deleteBy*` (or `update`/`revoke`), in the same order in every port of a project.
- Step-down order: put a function above the functions it calls, one abstraction level per step (use case `execute` on top, `_needs_requeue` below); put a service or util that several use cases of the module share (`build_report_tree`, `_parse_date_window`) at module level, outside any use case class, below the classes that call them in call-chain order (`_publish_job_resource` above `_is_publish_stale`).
