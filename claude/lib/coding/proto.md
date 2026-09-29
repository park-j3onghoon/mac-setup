# proto files

- Comment scope: proto files carry shape and signatures only; contract, validation and rationale live in server code, the PR body and Linear. The one exception is the "why" of a structure that looks like a mistake (an intentionally empty `Foo {}`), removed as soon as a field arrives; `*_UNSPECIFIED = 0` is a value, not a comment.
- Enum zero value: a new enum reserves 0 for `{ENUM}_UNSPECIFIED` in requests and responses alike and starts real values at 1; the server always sends a real value, and a receiver treats UNSPECIFIED as an error (`INVALID_ARGUMENT` for a request, a server bug for a response); a domain enum keeps only real values and the proto ↔ domain mapping layer filters UNSPECIFIED; an already published enum keeps its numbering.
