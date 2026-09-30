# Errors

- Not found: when `update`/`delete` finds no target, raise a domain exception (`NotFound`/`EntityNotFound`) and keep the return type non-nullable; `find`/`search` may return null. When the caller expects absence, return null; when existence is a precondition, raise.
- 404 vs 200 + null: `GET /resources/{id}` for a missing resource returns 404 (`NotFound`); a condition-based single lookup ("the in-progress amendment") with no match returns 200 with a null field.
- Catch-all handlers return a fixed response and log the original error.
- Unreachable branch: in a pure function, return a safe fallback with the comment `정상 경로 도달 불가: ...`; in an async or event handler, throw an error naming the branch (`unreachable: ...`).
- Batch/loop failure aggregation: collect per-item failures and log once after the loop with the failure count and an id → message map; persist each failed item in a terminal state (run FAILED); in nested loops, aggregate per level (run loop, org loop); on exception, close a claimed item to a terminal state.
- Message style: write English + resource name + id (`Campaign request not found: id=42`, `Campaign creative not found: campaign_id=7`), raise it as the domain exceptions `NotFoundError`/`NotAllowedError`/`ValidationError`, leave use case context out, and let the frontend map the message to Korean.
