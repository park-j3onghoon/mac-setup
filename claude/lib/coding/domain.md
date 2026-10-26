For Python code, also Read `~/.claude/lib/coding/domain-python.md`.

## Aggregates

- Aggregate: change the objects inside an aggregate only through its root, modify one aggregate per unit of work, and reference other aggregates by id.
- Domain event: when a change needs a reaction outside its aggregate, raise a domain event on the aggregate.

## Entities and values

- Value object: make a domain value immutable and compare it by value; immutability, value equality or reuse alone does not make an application DTO a domain value object.
- Rich domain: put behaviour that reads or changes an entity's state on the entity and change it only through its methods; inside a method, use only its own fields, its parameters and objects it creates. Consider which entity or value object owns a business calculation or creation rule before extracting it; put a rule over several entities on the owner and pass it the others. Keep a data-only entity for plain CRUD only.
- Domain service: use a domain service or module function for an independent business rule with no appropriate entity/value-object owner. Do not force unrelated helpers onto an entity or put workflow/serialization helpers in domain merely because they use business terms.
- Actor rules: when a business rule names who may act (an approver other than the requester), the domain method takes the actor's id and decides; the use case passes the id from the session.
- Factory method: when creating a new entity has rules (initial state, defaults, checks at creation), put them in a named creation method on the entity and create through it; a repository rebuilds a stored entity with the constructor; add a separate factory object only when one creation gathers values from several aggregates.

## State

- Store state explicitly: persist a state field instead of computing status from other fields.
- Transition diagram first: fix the transition diagram and terminal conditions before designing state, and ask for the diagram before reviewing a state design.
- State machine shape: check state transitions in entity methods through one transition map and a shared `_transition_to` guard that raises a domain exception on an invalid transition; put intent and per-state logic in named `mark_*` methods; expose the map to tests, and guard only transitions the system can reach.

## Validation ladder

Place each check on the rung below, in simple CRUD too.

1. Type and format → entrypoint; (de)serialize here and keep the request's JSON and HTTP objects inside the entrypoint.
2. Single-value invariant → value object constructor.
3. Business eligibility or invariant over several objects' state → domain behaviour: a `can_*()` query or a guard that raises a domain exception. The use case may handle or contextualize it according to `errors.md`; presentation maps the exposed failure to the transport status.
4. Application execution precondition → use case: keep the application's coordination rules and their exceptions here. Business eligibility and invariants remain in the domain, regardless of how many objects or operations they involve.
