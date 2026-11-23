For Python code, also Read `~/.claude/lib/coding/architecture-python.md`; for frontend code, `~/.claude/lib/coding/architecture-frontend.md`.

## Layers

- Dependency direction: presentation calls application; domain imports neither application, presentation nor concrete adapters; application depends on domain and port contracts rather than concrete adapters. Infrastructure implements those contracts and the composition root wires it in. Between modules of the same layer, keep dependencies one way too.
- Composition root: only the composition root creates adapters and hands them to use cases and services; it sits outside the layers, and entrypoints get what they call from it.
- Utils: a function with no business term and no port is a util; it sits outside the layers. A util called by domain must not import application, presentation or concrete adapters, including transitively.

## Presentation

- Thin entrypoint: an entrypoint (view, servicer, CLI, consumer), list and retrieve included, only checks type and format, maps request → command, passes it to its use case, and maps result → response; a query may call its read model directly, and for a create or update command whose response carries the resource, read it through the resource's read model with the returned id, on the primary when reads go to a replica.

## Application

- One scenario per use case: a use case runs one user scenario end to end; a command use case is the handler of one command.
- Command and event handlers: each command has one handler, and a failing command handler raises to the caller; after the unit of work commits, each domain event goes to every handler registered for it, and a failing event handler is logged while the other handlers still run; add a reaction to an event as a new event handler.
- Unit of work: a use case runs as one unit of work over the repositories it uses, which saves all of its changes when the use case completes and none when it fails; the unit of work interface and its implementation sit in the application; "transaction" names only the database mechanism inside that implementation.
- Use cases call no other use case and share no base class: put the steps several use cases share in a service; a service calls domain methods and ports in a fixed order and runs inside the calling use case's unit of work; calls between use cases and services go one way: use case → service.
- What a use case holds: a use case or service holds the call order, access checks (tenant, ownership, held role), the unit of work, port calls and checks governing the execution of its application scenario. Requests, execution options, work plans and result DTOs belong here when they describe that scenario, even when immutable or shared. Rules defining valid business state and behaviour stay in the domain.
- Command or query use case: a command use case has side effects and returns only an id/status; a query use case has none.
- CQRS read models: when a query needs a shape the aggregates do not have (fields from several aggregates, computed totals) or reads from another store (a replica, a denormalized table), serve it from a read model, a query that returns DTOs straight from storage without loading aggregates; give a query endpoint that other systems call its own read model rather than a repository method.

## Domain

- Business rules in the domain: put business calculations, eligibility and invariants in the domain, including those checked by only one operation. Classify by the meaning and owner of the decision, not by purity, reuse, the number of objects read, domain terms in a type's name, or a type's form or base class. Constants and exceptions live with their rule; changing ownership moves the owned check too, without a domain → application import. Handling or wrapping a domain exception in a use case does not move its domain check.
- Ports: define a domain/application port by the role and contract its consuming domain needs; keep the contract in its owning layer. Keep provider service names, transport details and provider-specific lookup sequences in adapters unless they are part of the consumer's required semantics. Apply this boundary to the port's interface and method names, input/output types and comments, and to the error names and message text of the port and of the use cases that call it; the adapter adds the provider name when it wraps an error. Group methods by a cohesive consumer role, not by the external system they call; do not split mechanically into one interface per method.

## Infrastructure

- Adapters: a repository, gateway, notifier or publisher implements a port and translates client-library failures into the port's exceptions; use cases and entrypoints handle external-resource failures through those exceptions, not client-library types. This does not exclude handling domain or application exceptions.
- Bounded context: when data comes from another system or module, translate it in the adapter into this domain's own entities and enums.
- Gateway / BFF / adapter: transform and forward only; put defaults, field merge/preserve (including a read-modify-write that preserves missing fields) and invariants in the system that owns the domain.
