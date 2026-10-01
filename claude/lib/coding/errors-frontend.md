# Errors: Frontend

- No throw from an async handler chain: in a Promise-returning `onClick`, an overlay `onConfirm` or a wrapper that calls the callback and drops the return, a throw becomes an unhandled rejection; grep each layer (`handleConfirm` → `Modal.BottomSheet onClick wrapper` → React `onClick`) for an `await`/`.catch`; with none, catch, show a toast and return without rethrowing. An unreachable branch is the one exception and throws `new Error('unreachable: ...')`.
- Modals close on their own: let the modal close and offer retry through the button; `catch {}` without a binding is fine for confirm-modal branching alongside "mutation errors are handled in `onError`".
