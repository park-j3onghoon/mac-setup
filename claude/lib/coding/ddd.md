# Domain-driven design: the domain model

## Aggregates and boundaries

- Aggregate: change the objects inside an aggregate only through its root, modify one aggregate per transaction, and reference other aggregates by id.
- Domain event: when a change needs a side effect outside its aggregate (the approval email, a counter on another aggregate), raise a domain event on the aggregate and handle it after the unit of work commits.
- Bounded context: when data comes from another service or module, translate it in the adapter into this domain's own entities and enums.

## Entities and values

- Value object: make it immutable, compare it by value, and check its invariants in the constructor.
- Rich domain: put behaviour that reads or changes an entity's state on the entity and change an entity only through its methods (`payout.approve(now)`, `order.mark_paid(now)`); inside a method, use only its own fields, its parameters and objects it creates; keep a data-only entity for plain CRUD only.

## Validation ladder

When domain rules are rich, place each check on the rung below; for simple CRUD or a thin gateway service, check at the entrypoint.

1. Type and format → entrypoint (`"abc"` for an int fails with 400); (de)serialize here and pass the domain no JSON or HTTP objects.
2. Single-value invariant → value object constructor (`Quantity(-5)` is rejected on construction), also when the entrypoint checks the same.
3. Rule over several objects' state → domain behaviour: a `can_xxx()` query or a guard that raises a domain exception (`OutOfStock` when `line.qty > batch.available_quantity`), which the entrypoint maps to an HTTP status.

## State and types

- Store state explicitly: persist a state field instead of computing status from other fields.
- Transition diagram first: fix the transition diagram and terminal conditions before designing state, and ask for the diagram before reviewing a state design.
- State machine shape: check state transitions in entity methods through one transition map and a shared `_transition_to` guard that raises a domain exception on an invalid transition; put intent and per-state logic in named `mark_*` methods; expose the map to tests, and guard only transitions the system can reach.
- Make illegal states unrepresentable: model a kind/state/mode argument as an enum even with two values (`kind=ExitKind.STOP_LOSS`); replace two booleans (`is_tp` + `is_sl`) with one enum; replace an optional field plus a same-root boolean (`take_profit` + `is_take_profit`) with one field; put fields that travel with a variant in a discriminated union; give a constrained value a constrained type.
- Booleans: use a boolean only for an on/off flag (`verbose`, `dry_run`); when reading one, name the axis it answers and read `False` as the opposite pole of that axis.
