# Domain-driven design: the domain model

## Aggregates and boundaries

- Aggregate: one aggregate is one consistency boundary; a unit of work modifies one aggregate root per transaction and references other aggregates by id.
- Domain event: raise a cross-aggregate side effect (send the approval email, bump a counter on another aggregate) as a domain event on the aggregate and handle it after the unit of work commits.
- Bounded context: each service/module keeps its own terms and model and translates at the boundary with an anti-corruption mapping in the adapter, so the domain uses only its own entities and enums.

## Entities and values

- Value object: immutable, equal by value, invariants enforced in the constructor.
- Always-valid entity: entity methods check state transitions and raise a domain exception on an invalid one, so invariants live in one place.
- Rich domain: behaviour that reads or changes an entity's state lives on the entity (`payout.approve(now)`); an anemic entity is acceptable only for plain CRUD.
- Tell, don't ask (Law of Demeter): the use case calls `order.mark_paid(now)`; a method talks to its own fields, its parameters and objects it creates.

## Validation ladder

Place each check where its criterion lives; one place for everything ties the domain to one entrypoint and misses the next one. Apply the ladder when domain rules are rich; simple CRUD or a thin gateway service keeps its checks at the entrypoint.

1. Type/format → entrypoint: "does raw input parse to the right type" (`"abc"` → int fails with 400); (de)serialization lives here and the domain sees no JSON or HTTP.
2. Single-value invariant → value object constructor: "is this one value valid" (`Quantity(-5)` is rejected on construction); keep it even when the entrypoint checks the same, because entrypoints multiply (HTTP, CLI, queue, batch, tests).
3. Relational rule → domain behaviour: "given several objects' state, may this operation run" (`line.qty > batch.available_quantity`) in a `can_xxx()` query or a guard raising a domain exception (`OutOfStock`) that the entrypoint translates to an HTTP status.

## State and types

- Store state explicitly: persist a state field instead of computing status from other fields; an event-driven action (send an email once) needs the stored state, and a computed status keeps no history.
- Transition diagram first: fix the transition diagram and terminal conditions before designing state, and ask for the diagram before reviewing a state design.
- State machine shape: one transition map as the single source of truth, a shared `_transition_to` guard, and named `mark_*` methods carrying intent and per-state logic; expose the map for test reuse so a new transition is one map line, and guard only transitions that can actually happen, since a guard for a state the system cannot reach is noise.
- Make illegal states unrepresentable: model a kind/state/mode argument as an enum even with two values (`kind=ExitKind.STOP_LOSS`); two booleans (`is_tp` + `is_sl`) allow (True, True) and (False, False) → one enum; an optional field plus a same-root boolean (`take_profit` + `is_take_profit`) mixes existence with kind → one field; fields that travel with a variant form a discriminated union, and a constrained value gets a constrained type.
- Boolean only for a true on/off flag (`verbose`, `dry_run`); when reading any boolean, first name the axis it answers, since `False` is the opposite pole of that axis, not "absent".
