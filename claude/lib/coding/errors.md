# Errors

- Not found: when existence is a precondition (`update`/`delete`), raise a domain exception (`NotFound`/`EntityNotFound`) and keep the return type non-nullable; when the caller expects absence (`find`/`search`), return null.
- Catch-all handlers return a fixed response and log the original error.
- Unreachable branch: in a pure function, return a safe fallback with the comment `정상 경로 도달 불가: ...`; in an async or event handler, throw an error naming the branch (`unreachable: ...`).
- Batch/loop failure aggregation: collect per-item failures and log once after the loop with the failure count and an id → message map; persist each failed item in a terminal state (run FAILED); in nested loops, aggregate per level (run loop, org loop); on exception, close a claimed item to a terminal state.
- Message style: write English + resource name + id (`Campaign request not found: id=42`, `Campaign creative not found: displaycam_id=7`), raise it as the domain exceptions `NotFoundError`/`NotAllowedError`/`ValidationError`, leave use case context out, and let the frontend map the message to Korean.

## Python

- Catch-all handlers: `except Exception` returns the fixed string `"Internal Server Error"`.
- Batch/loop failure aggregation: `logger.error('... %d failed: %s', failed_count, {id: message})`.
- Message style: `raise NotFoundError(f'Campaign request not found: id={request_id}')`.

## Frontend

- No throw from an async handler chain: in a Promise-returning `onClick`, an overlay `onConfirm` or a wrapper that calls the callback and drops the return, a throw becomes an unhandled rejection; grep each layer (`handleConfirm` → `Modal.BottomSheet onClick wrapper` → React `onClick`) for an `await`/`.catch`; with none, catch, show a toast and return without rethrowing. An unreachable branch is the one exception and throws `new Error('unreachable: ...')`.
- Modals close on their own: let the modal close and offer retry through the button; `catch {}` without a binding is fine for confirm-modal branching alongside "mutation errors are handled in `onError`".
