# Domain model: aggregates, entities, state and validation

For Python code, also Read `~/.claude/lib/coding/domain-python.md`.

## Aggregates

- Aggregate: change the objects inside an aggregate only through its root, modify one aggregate per unit of work, and reference other aggregates by id.
- Domain event: when a change needs a side effect outside its aggregate (the approval email, a counter on another aggregate), raise a domain event on the aggregate.

## Entities and values

- Value object: make it immutable and compare it by value.
- Rich domain: put behaviour that reads or changes an entity's state on the entity and change an entity only through its methods (`order.mark_paid(now)`); inside a method, use only its own fields, its parameters and objects it creates; put a rule over several entities on the entity that owns the decision and pass it the others; keep a data-only entity for plain CRUD only.
- Actor rules: when a business rule names who may act (only the billing manager confirms a statement), the domain method takes the actor's id and decides; the use case passes the id from the session.
- Factory method: when creating a new entity has rules (initial state, defaults, checks at creation), put them in a named creation method on the entity (`Contract.issue(...)`, `Loan.open(...)`) and create through it; a repository rebuilds a stored entity with the constructor; add a separate factory object only when one creation gathers values from several aggregates.

## State

- Store state explicitly: persist a state field instead of computing status from other fields.
- Transition diagram first: fix the transition diagram and terminal conditions before designing state, and ask for the diagram before reviewing a state design.
- State machine shape: check state transitions in entity methods through one transition map and a shared `_transition_to` guard that raises a domain exception on an invalid transition; put intent and per-state logic in named `mark_*` methods; expose the map to tests, and guard only transitions the system can reach.

## Validation ladder

Place each check on the rung below, in simple CRUD too.

1. Type and format → entrypoint (`"abc"` for an int fails with 400); (de)serialize here and keep the request's JSON and HTTP objects inside the entrypoint.
2. Single-value invariant → value object constructor (`Quantity(-5)` is rejected on construction), also when the entrypoint checks the same.
3. Rule over several objects' state → domain behaviour: a `can_*()` query or a guard that raises a domain exception (`OutOfStock` when `line.qty > batch.available_quantity`), which the entrypoint maps to an HTTP status.
