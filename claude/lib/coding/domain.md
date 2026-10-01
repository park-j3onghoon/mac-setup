# Domain model: aggregates, entities, state and validation

## Aggregates

- Aggregate: change the objects inside an aggregate only through its root, modify one aggregate per transaction, and reference other aggregates by id.
- Domain event: when a change needs a side effect outside its aggregate (the approval email, a counter on another aggregate), raise a domain event on the aggregate and handle it after the unit of work commits.

## Entities and values

- Value object: make it immutable and compare it by value.
- Rich domain: put behaviour that reads or changes an entity's state on the entity and change an entity only through its methods (`payout.approve(now)`, `order.mark_paid(now)`); inside a method, use only its own fields, its parameters and objects it creates; keep a data-only entity for plain CRUD only.
- Actor rules: when a business rule names who may act (only the billing manager confirms a statement), the domain method takes the actor's id and decides; the use case passes the id from the session.
- Factory method: when creating a new entity has rules (initial state, defaults, checks at creation), put them in a named creation method on the entity (`Contract.issue(...)`, `create_pending(...)`) and create through it; a repository rebuilds a stored entity with the constructor; add a separate factory object only when one creation gathers values from several aggregates.

## State

- Store state explicitly: persist a state field instead of computing status from other fields.
- Transition diagram first: fix the transition diagram and terminal conditions before designing state, and ask for the diagram before reviewing a state design.
- State machine shape: check state transitions in entity methods through one transition map and a shared `_transition_to` guard that raises a domain exception on an invalid transition; put intent and per-state logic in named `mark_*` methods; expose the map to tests, and guard only transitions the system can reach.

## Validation ladder

Place each check on the rung below, in simple CRUD too.

1. Type and format → entrypoint (`"abc"` for an int fails with 400); (de)serialize here and pass the domain no JSON or HTTP objects.
2. Single-value invariant → value object constructor (`Quantity(-5)` is rejected on construction), also when the entrypoint checks the same.
3. Rule over several objects' state → domain behaviour: a `can_*()` query or a guard that raises a domain exception (`OutOfStock` when `line.qty > batch.available_quantity`), which the entrypoint maps to an HTTP status.

## Python

- Validation ladder in Django: type/format in the DRF Serializer or view, a single-value invariant in the value object's `__post_init__`, a rule over several objects' state in a domain method.
- Explicit validation over framework magic: for an entity field without a value object, put the check in a `*Validator` class with `@classmethod validate_{field}(value) -> None` and plain `if ...: raise {Domain}InvalidArgumentError`; call it from both repo `create`/`update` (Django model creation and attribute assignment skip the entity validator) and the entity `@validator`; make the Fake repo make the same calls; call the `*Validator` directly in tests; keep the entity validator; before adding a validator, confirm seed and existing rows pass it; `to_entity()` runs it on every read.
- Validators return the value unchanged: `Field(...)` constraints that only check (`gt=0`, `max_length=50`) are fine on DTOs and entities; skip pydantic `constr(...)` and any `@validator` that returns a replaced value (even `return v.strip()`); a check-raise-return-unchanged validator is fine; strip/normalize at the entrypoint (servicer/view) or not at all, and reject whitespace-only input with `if not x.strip()` without changing the value.
