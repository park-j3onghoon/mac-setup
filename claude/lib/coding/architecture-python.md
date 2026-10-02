# Architecture: Python

- Thin entrypoint as a DRF view: `_build_user_info(request)` → a command from `**request.query_params.dict()` / `**kwargs` and the user info → `id = bus.handle(command)` → `Response(data={'id': id}, status=...)`, or `Response(data=get_{resource}(id).dict(), status=...)` when the response carries the resource, with `bus` from `bootstrap.bootstrap()`.
- Composition root: `bootstrap.bootstrap(uow=None, ...)` declares the default adapters (`uow or DjangoUnitOfWork()`), takes overrides for tests, injects the dependencies into the handlers and returns the message bus; an entrypoint or a management command calls it once.
- Unit of work in Django: `DjangoUnitOfWork` calls `close_old_connections()` and `transaction.set_autocommit(False)` on enter and `transaction.commit()` in `commit()`, and on exit rolls back, restores autocommit and calls `close_old_connections()`; a use case writes `with uow:` … `uow.commit()` in place of `@transaction.atomic`.
