For Python code, also Read `~/.claude/lib/coding/architecture-python.md`; for frontend code, `~/.claude/lib/coding/architecture-frontend.md`.

## Layers

- Dependency rule: point imports only inward: presentation → application → domain, and infrastructure → domain and application by implementing the domain's ports and the application's unit of work interface. Between two modules of the same layer, keep the dependency one way too.
- Composition root: only the composition root creates adapters and hands them to use cases and services, so application code imports only ports; it sits outside the layers, and entrypoints get what they call from it.
- Utils: a function with no business term and no port is a util; it sits outside the layers, and any layer may call it.
- Convention breaks ties: when these rules allow several placements or structures, follow the one the project already uses.

## Presentation

- Thin entrypoint: an entrypoint (view, servicer, CLI, consumer), list and retrieve included, only checks type and format, maps request → command, passes it to its use case, and maps result → response; a query may call its read model directly, and for a create or update command whose response carries the resource, read it through the resource's read model with the returned id, on the primary when reads go to a replica.

## Application

- One scenario per use case: a use case runs one user scenario end to end; a command use case is the handler of one command.
- Command and event handlers: each command has one handler, and a failing command handler raises to the caller; after the unit of work commits, each domain event goes to every handler registered for it, and a failing event handler is logged while the other handlers still run; add a reaction to an event as a new event handler.
- Unit of work: a use case runs as one unit of work over the repositories it uses, which saves all of its changes when the use case completes and none when it fails; the unit of work interface sits in the application by default; "transaction" names only the database mechanism inside its adapter.
- Use cases call no other use case and share no base class: put the steps several use cases share in a service; a service calls domain methods and ports in a fixed order and runs inside the calling use case's unit of work; calls between use cases and services go one way: use case → service.
- What a use case holds: a use case or service holds only the call order, the access check (tenant, ownership, held role), the unit of work and port calls.
- Command or query use case: a command use case has side effects and returns only an id/status; a query use case has none.
- CQRS read models: when a query needs a shape the aggregates do not have (fields from several aggregates, computed totals) or reads from another store (a replica, a denormalized table), serve it from a read model, a query that returns DTOs straight from storage without loading aggregates; give a query endpoint that other systems call its own read model rather than a repository method.

## Domain

- Business rules in the domain: put every business rule in the domain, including one that only a single operation checks. A constant or exception lives with the rule that uses it: the domain holds those of business rules, the application those of the use case flow.
- Ports: the domain defines a port for each outside resource, and use cases and services reach the ORM, HTTP clients and email rendering only through ports.

## Infrastructure

- Adapters: a repository, a gateway, a notifier, a publisher or the concrete unit of work implements a port or the unit of work interface.
- Bounded context: when data comes from another system or module, translate it in the adapter into this domain's own entities and enums.
- Gateway / BFF / adapter: transform and forward only; put defaults, field merge/preserve (including a read-modify-write that preserves missing fields) and invariants in the system that owns the domain.
