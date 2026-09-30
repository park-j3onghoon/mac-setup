# Coding rules

Modules sit in `~/.claude/lib/coding/`. When two rules conflict, the module listed higher wins.

- `change-discipline.md`: proposing a change, deviating from an existing pattern, moving files
- `clean-architecture.md`: layers, dependency direction, use cases, entrypoints
- `hexagonal.md`: ports, adapters, repositories, calls to other services
- `ddd.md`: entities, value objects, aggregates, state and transitions
- `cqs.md`: commands vs queries, read models, writing or splitting functions
- `simple-design.md`: abstraction, duplication, scope of a change
- `tdd.md`: tests
- `errors.md`: exceptions, error responses, failure aggregation
- `function.md`: writing or splitting functions
- `file-layout.md`: placing imports, constants, methods and helpers inside a file
- `comments.md`: comments and docstrings
- `naming.md`: naming anything
- `python.md`: Python, Django, DRF, Pydantic, pytest
- `frontend.md`: React, Vue, TypeScript; for the Vue main projects also `~/.claude/lib/coding-rules-vue.md`
- `db.md`: MySQL schema, transactions, locks
- `proto.md`: proto files
