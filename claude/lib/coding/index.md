# Coding rules

Read this index, then read only the modules the task touches.

| Task | Read |
|---|---|
| Layers, dependency direction, use cases, entrypoints | `~/.claude/lib/coding/clean-architecture.md` |
| Ports, adapters, repositories, calls to other services | `~/.claude/lib/coding/hexagonal.md` |
| Entities, value objects, aggregates, state and transitions | `~/.claude/lib/coding/ddd.md` |
| Commands vs queries, read models | `~/.claude/lib/coding/cqs.md` |
| Writing or splitting functions | `~/.claude/lib/coding/function.md`, `~/.claude/lib/coding/cqs.md` |
| Naming anything | `~/.claude/lib/coding/naming.md` |
| Placing imports, constants, methods and helpers inside a file | `~/.claude/lib/coding/file-layout.md` |
| Exceptions, error responses, failure aggregation | `~/.claude/lib/coding/errors.md` |
| Comments and docstrings | `~/.claude/lib/coding/comments.md` |
| Tests | `~/.claude/lib/coding/tdd.md` |
| Abstraction, duplication, scope of a change | `~/.claude/lib/coding/simple-design.md` |
| Proposing a change, deviating from an existing pattern, moving files | `~/.claude/lib/coding/change-discipline.md` |
| Python · Django · DRF · Pydantic · pytest | `~/.claude/lib/coding/python.md` |
| React · Vue · TypeScript | `~/.claude/lib/coding/frontend.md`; for the Vue main projects also `~/.claude/lib/coding-rules-vue.md` |
| MySQL schema, transactions, locks | `~/.claude/lib/coding/db.md` |
| proto files | `~/.claude/lib/coding/proto.md` |

- When two rules conflict, follow the higher rung: architecture (clean-architecture, hexagonal, ddd, cqs) > function and file layout > naming.
- A stack file adds detail inside its stack and may narrow a rule here; when it contradicts one, the rule here wins.
