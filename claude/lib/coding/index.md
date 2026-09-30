# Coding rules

## Principles

- One owner per business decision: the domain holds business rules, use cases and services hold the flow, and repositories, gateways and callers store, transform or forward.
- Build on verified behaviour: before relying on another service, a repository, the DB schema or a library, read its code or DDL.
- Checks on every path, in layers: put a check that must always hold where every entrypoint (HTTP, CLI, queue, batch, tests) passes, and back it with another layer (a schema constraint, authorization, output encoding).
- Invalid values unrepresentable: shape types and schema constraints so a wrong value cannot enter (an enum over a free string, NOT NULL, UNIQUE, CHECK).
- Reversible steps: split a change so each step rolls back on its own, schema and code separately.
- Queryable storage: store values in shapes a query can analyse later (typed columns and enums rather than free text, a dict or a JSON union).
- When following a rule would defeat one of these principles, show both options and let the user decide.

## Modules

When two rules conflict, the one listed higher wins: first by the module order below, then by the order inside a module.

- `~/.claude/lib/coding/change-discipline.md`: proposing a change, deviating from an existing pattern, moving files
- `~/.claude/lib/coding/clean-architecture.md`: layers, dependency direction, entrypoints, use cases, application services, commands vs queries
- `~/.claude/lib/coding/hexagonal.md`: ports, adapters, repositories, calls to other systems
- `~/.claude/lib/coding/ddd.md`: entities, value objects, aggregates, state and transitions
- `~/.claude/lib/coding/simple-design.md`: abstraction, duplication, scope of a change
- `~/.claude/lib/coding/tdd.md`: tests
- `~/.claude/lib/coding/errors.md`: exceptions, error responses, failure aggregation
- `~/.claude/lib/coding/clean-code.md`: writing or splitting functions, placing code inside a file, comments and docstrings, naming
- `~/.claude/lib/coding/python.md`: Python, Django, DRF, Pydantic, pytest
- `~/.claude/lib/coding/frontend.md`: React, Vue, TypeScript; for the Vue main projects also `~/.claude/lib/coding-rules-vue.md`
- `~/.claude/lib/coding/db.md`: MySQL schema, transactions, locks
- `~/.claude/lib/coding/proto.md`: proto files
