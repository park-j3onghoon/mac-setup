# Coding rules

When two rules conflict, the one listed higher wins: first by the module order below, then by the order inside a module.

- `~/.claude/lib/coding/change-discipline.md`: proposing a change, deviating from an existing pattern, moving files
- `~/.claude/lib/coding/clean-architecture.md`: layers, dependency direction, entrypoints, use cases, commands vs queries
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
