# Coding rules

## Principles

- One owner per business decision: the domain holds business rules, use cases and services hold the flow, and repositories, gateways and callers store, transform or forward.
- Build on verified behaviour: before relying on another service, a repository, the DB schema or a library, read its code or DDL.
- Checks on every path, in layers: put a check that must always hold where every entrypoint (HTTP, CLI, queue, batch, tests) passes, and back it with another layer (a schema constraint, authorization, output encoding).
- Invalid values unrepresentable: shape types and schema constraints so a wrong value cannot enter (an enum over a free string, NOT NULL, UNIQUE, CHECK).
- Reversible steps: split a change so each step rolls back on its own, schema and code separately.
- Queryable storage: store values in shapes a query can analyse later (typed columns and enums rather than free text, a dict or a JSON union).
- When following a rule would defeat one of these principles, show both options and let the user decide.

## Rule files

When two rules conflict, a rule in a stack section (Python, Frontend, proto) wins over the general rule it narrows; otherwise the one listed higher wins: first by the file order below, then by the order inside a file.

- `~/.claude/lib/coding/process.md`: proposing a change, following existing patterns, verifying another system before compensating for it, file state, moves and builds, slices and commits
- `~/.claude/lib/coding/architecture.md`: layers and dependency direction, convention as the tie-breaker, entrypoints, use cases and services, commands and queries, ports and adapters
- `~/.claude/lib/coding/domain.md`: aggregates, domain events, value objects, entities and factory methods, state and transitions, the validation ladder
- `~/.claude/lib/coding/types.md`: enums and booleans, constrained types, type forms per stack
- `~/.claude/lib/coding/design.md`: duplication, abstraction and extraction, scope, simplicity, extension
- `~/.claude/lib/coding/tests.md`: tests
- `~/.claude/lib/coding/errors.md`: exceptions, failure aggregation, error messages, errors in async handlers, timeouts on calls to other systems
- `~/.claude/lib/coding/functions.md`: writing or splitting functions and methods
- `~/.claude/lib/coding/file-layout.md`: imports, constants, method and helper order inside a file
- `~/.claude/lib/coding/comments.md`: comments and docstrings
- `~/.claude/lib/coding/naming.md`: names and terms
- `~/.claude/lib/coding/db.md`: MySQL column types, charset and order, counters, `updated_at`, transactions and locks, repositories: return types, mapping and saving, pagination, dates, normalized values
- `~/.claude/lib/coding/api.md`: HTTP responses, proto contracts, partial updates, OpenAPI docs
- `~/.claude/lib/coding/ui.md`: frontend screens: URL state, copy, components and forms, CSS layout; for the Vue main projects also `~/.claude/lib/coding-rules-vue.md`
