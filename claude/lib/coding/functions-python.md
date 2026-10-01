# Functions and methods: Python

- Inline length decides a nested call too: `return ResponseDTO(**repo.create(entity).dict())`.
- Falsy sentinel for absent scalars: when falsy means "no filter", use `search_id: int = 0`, `search_name: str = ''`.
- Explicit fields after a spread: `Entity(**{**request_dto.dict(), 'explicit_field': value})`.
- Immutable copy: `dict(input)` + the modification.
- Use case class structure: make state-holding builders and UseCases classes (`ReportTree`, `MonthlyReportUseCase`); services and utils may be module functions (`resolve_report_scope`, `build_report_tree`, `_parse_month_range`); make an externally called method public and an internal one a private instance method; use a public `@staticmethod` only for pure state-independent computation and no private classmethod/staticmethod; keep all private methods of one class the same kind.
