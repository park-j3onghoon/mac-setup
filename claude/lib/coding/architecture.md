# Architecture: layers and what each holds

For Python code, also Read `~/.claude/lib/coding/architecture-python.md`.

## Layers

- Dependency rule: point dependencies only inward: presentation → application → domain, and infrastructure → domain by implementing the ports the domain defines. Between two modules of the same layer, keep the dependency one way too.
- Composition root: only the composition root creates adapters and passes them to use cases and services, which receive ports and the unit of work as parameters; it sits outside the layers (`bootstrap.py` in Python, `cmd/<app>/main.go` in Go, the container configuration in Spring), and entrypoints get what they call from it.
- Utils: a function with no business term and no port is a util; it sits outside the layers, and any layer may call it.
- Convention breaks ties: when these rules allow several placements or structures, follow the one the project already uses.

## Presentation

- Thin entrypoint: an entrypoint (view, servicer, CLI, consumer), list and retrieve included, only checks type and format, maps request → command, passes it to its use case, and maps result → response; a query may call its read model directly, and for a command whose response must carry the resource (AIP Create/Update), read it through the resource's read model with the returned id, on the primary when reads go to a replica.

## Application

- One scenario per use case: a use case runs one user scenario end to end; a command use case is the handler of one command.
- Command and event handlers: each command has one handler, and a failing command handler raises to the caller; after the unit of work commits, each domain event goes to every handler registered for it, and a failing event handler is logged while the other handlers still run; add a reaction to an event as a new event handler.
- Unit of work: a use case runs as one unit of work over the repositories it uses, which saves all of its changes when the use case completes and none when it fails; the unit of work interface sits in the application by default and its database implementation is an adapter; "transaction" names only the database mechanism inside that adapter.
- Use cases call no other use case and share no base class: put the steps several use cases share in a service (`validate_order_ownership`); a service calls domain methods and ports in a fixed order and runs inside the calling use case's unit of work; calls between use cases and services go one way: use case → service.
- Command or query use case: a command use case has side effects and returns only an id/status; a query use case has none.
- CQRS read models: split read and write models when their shapes or paths diverge, and give an externally served query endpoint its own read model rather than a repository projection.

## Domain

- Domain vs application placement: put every business rule in the domain, including one that only a single operation checks (`request.submit()` requires every field while a draft may stay empty). Services and use cases decide only the order of calls, access control (whether the caller may reach this data: tenant, ownership, held role), the unit of work and calls through ports. Split constants and exceptions the same way (`domain/constants` vs `application/constants`).
- Ports: the domain defines a port for each outside resource, and use cases and services reach the ORM, HTTP clients and email rendering only through ports.

## Infrastructure

- Adapters: a repository (storage), a gateway (another system), a notifier (email), a publisher (messaging) or the concrete unit of work (a database transaction) implements a port or the unit of work interface; for repository rules, Read `~/.claude/lib/coding/db.md` and follow them.
- Bounded context: when data comes from another system or module, translate it in the adapter into this domain's own entities and enums.
- Gateway / BFF / adapter: transform and forward only; put defaults, field merge/preserve (including a read-modify-write that preserves missing fields) and invariants in the system that owns the domain.
