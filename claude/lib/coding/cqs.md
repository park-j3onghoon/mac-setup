# CQRS / CQS: commands and queries

- At the boundary: a command has side effects and a minimal return (id/status); a query has no side effects. Split read and write models when their shapes or paths diverge, and give an externally served query endpoint its own read model rather than a repository projection.
- Per function: a function is either a query (returns a value, no side effect) or a command (mutates, returns nothing); split one that does both.
- Entity exception: `entity.change()` may mutate in memory and return the result; everywhere else queries and commands stay apart.
