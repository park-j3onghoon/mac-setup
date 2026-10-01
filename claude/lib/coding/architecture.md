# Architecture: layers and what each holds

For Python code, also Read `~/.claude/lib/coding/architecture-python.md`.

## Layers

- Dependency rule: point dependencies only inward: presentation → application → domain, and infrastructure → domain by implementing the ports the domain defines. Between two modules of the same layer, keep the dependency one way too: when A references B, B never references A.
- Composition root: only the composition root creates adapters and passes them to use cases and services, which receive ports and the unit of work as parameters; it sits outside the layers (`bootstrap.py` in Python, `cmd/<app>/main.go` in Go, the container configuration in Spring), and entrypoints get the message bus from it.
- Utils: a function with no business term and no port is a util; it sits outside the layers, and any layer may call it.
- Convention breaks ties: when these rules allow several placements or structures, follow the one the project already uses.

## Presentation

- Thin entrypoint: an entrypoint (view, servicer, CLI, consumer), list and retrieve included, only checks type and format, maps request → command, hands it to the message bus, and maps result → response; a query may call its read model directly.

## Application

- One scenario per use case: a use case runs one user scenario end to end; a command use case is the handler of one command.
- Message bus: the message bus hands each command to its one handler and, after the unit of work commits, each domain event to every handler registered for it; a failing command handler raises to the caller, while a failing event handler is logged and the other handlers still run; add a reaction to an event as a new event handler.
- Unit of work: a use case opens one unit of work over the repositories it uses and commits it explicitly, and leaving it without a commit rolls back; the unit of work interface belongs to the application and its database implementation is an adapter; "transaction" names only the database mechanism inside that adapter.
- Use cases call no other use case and share no base class: put the steps several use cases share in a service (`validate_order_ownership`); a service calls domain methods and ports in a fixed order, runs inside the calling use case's unit of work, and never calls a use case.
- Commands and queries: a command use case has side effects and returns a minimal id/status; a query use case has none. Split read and write models when their shapes or paths diverge, and give an externally served query endpoint its own read model rather than a repository projection.

## Domain

- Domain vs application placement: put every business rule in the domain, including one that only a single operation checks (`request.submit()` requires every field while a draft may stay empty). Services and use cases decide only the order of calls, access control (whether the caller may reach this data: tenant, ownership, held role), the unit of work and calls through ports. Split constants and exceptions the same way (`domain/constants` vs `application/constants`).
- Ports: the domain defines an interface (port) for each outside resource, and use cases and services reach the ORM, HTTP clients and email rendering only through ports.
- Commands and events: commands and domain events are domain classes (`domain/commands.py`, `domain/events.py`).

## Infrastructure

- Adapters: a repository (storage), a gateway (another service), a notifier (email), a publisher (messaging) or the concrete unit of work (a database transaction) implements a port or the unit of work interface; repository rules are in `~/.claude/lib/coding/db.md`.
- Bounded context: when data comes from another service or module, translate it in the adapter into this domain's own entities and enums.
- Gateway / BFF / adapter: transform and forward only; put defaults, field merge/preserve (including a read-modify-write that preserves missing fields) and invariants in the service that owns the domain.
