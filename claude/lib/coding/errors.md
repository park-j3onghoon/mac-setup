For Python code, also Read `~/.claude/lib/coding/errors-python.md`; for frontend code, `~/.claude/lib/coding/errors-frontend.md`.

- Exception classes: raise the class the project already has for the role (not found, not allowed, invalid argument, already exists), such as `NotFoundError` or `{Entity}NotFoundError`.
- Access control vs business rule: an access-control failure raises the use case's not-allowed exception; a business-rule failure raises a domain exception.
- Not found: when existence is a precondition (`update`/`delete`), raise the not-found exception and keep the return type non-nullable; when the caller expects absence (`find`/`search`), return null.
- Catch-all handlers return a fixed response and log the original error.
- Unreachable branch: in a pure function, return a safe fallback with the comment `정상 경로 도달 불가: ...`; in an async or event handler, throw an error naming the branch (`unreachable: ...`).
- Batch/loop failure aggregation: collect per-item failures and log once after the loop with the failure count and an id → message map; persist each failed item in a terminal state (run FAILED); in nested loops, aggregate per level (run loop, org loop); on exception, close a claimed item to a terminal state.
- Message style: write English + resource name + id (`Campaign request not found: id=42`, `Campaign creative not found: campaign_id=7`), leave use case context out, and let the frontend map the message to Korean.
- Timeouts: set explicit connect/read timeouts on every call to another system (HTTP, gRPC, SMTP).
