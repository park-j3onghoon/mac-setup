# Functions

- Length: 30–40 lines soft limit; past it, split by responsibility into private helpers (Composed Method); a helper called only once or twice still earns its name, and private → private calls between step helpers are fine.
- One reason to change: a helper does only what its name promises; guards belong to the caller, whose loop skips or returns early.
- Same helper N times → table + loop: turn 4+ explicit calls of one helper with different arguments into a module-constant list of argument combinations iterated in a loop.
- Inline an expression up to 100–110 characters; past that, give it a named variable.
- Defaults only where a caller omits the value: remove a parameter default once every call site passes the value explicitly.
- Collection parameters are non-nullable: an empty collection means "no filter"; scalars may be null.
- Explicit fields after a spread: when building from a spread plus explicit fields, put the explicit fields after the spread so the explicit value wins over a same-named key.
- Immutable copy: a helper that would mutate an input map or list returns a modified copy as a new object.
