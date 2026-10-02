# Functions and methods

For Python code, also Read `~/.claude/lib/coding/functions-python.md`; for frontend code, `~/.claude/lib/coding/functions-frontend.md`.

- Length: extract the steps of a function into functions, even ones called once, when its body passes 35 lines (blank lines, comments and the docstring not counted) and your change created it or pushed it past 35. Cut at step boundaries: a step comment, a blank-line paragraph, one if/elif branch, one loop body. Name each extracted function with a verb phrase for its step and leave the caller as the ordered calls; extracted functions may call each other. A body that is a single statement (one constructor call, one dict literal, one query) stays whole, and a function already over 35 lines before your change keeps its shape.
- Branches: when a function's cyclomatic complexity passes 10 (each if, elif, for, while, except and match case counts one), move its branches out by what they share: a value-to-value choice becomes a module-constant dict; a choice of behaviour by one value becomes a dict from that value to a function or strategy class, with a test that every enum member has an entry; same-shape blocks per field become one function called per field, or a table and loop (Same call N times); state checks go to the transition map of `~/.claude/lib/coding/domain.md` (State machine shape). A chain whose arms each make one function call with different arguments stays as it is.
- One reason to change: an extracted function does only what its name promises; put guards in the caller, whose loop skips or returns early.
- Query or command: a function either returns a value without side effects or mutates and returns nothing; split one that does both. An entity method such as `entity.change()` may mutate in memory and return the result, a command use case may return what `~/.claude/lib/coding/architecture.md` (Commands and queries) allows, and a repository `create`/`save` may return the id or entity it produces.
- Same call N times → table + loop: turn 4+ explicit calls of one function with different arguments into a module-constant list of argument combinations iterated in a loop.
- Inline an expression up to 100–110 characters; past that, give it a named variable.
- Defaults only where a caller omits the value: remove a parameter default once every call site passes the value explicitly.
- Collection parameters are non-nullable: pass an empty collection for "no filter"; scalars may be null.
- Explicit fields after a spread: when an explicit value must win over a same-named key in the spread, put it after the spread.
- Immutable copy: a function that would mutate an input map or list returns a modified copy as a new object.
