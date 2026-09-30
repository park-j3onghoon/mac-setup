# proto files

- Comment scope: write only shape and signatures in proto files; put contract, validation and rationale in server code, the PR body and Linear. Comment a structure that looks like a mistake (an intentionally empty `Foo {}`) until a field arrives.
- Enum zero value: a new enum reserves 0 for `{ENUM}_UNSPECIFIED` in requests and responses alike and starts real values at 1; the server always sends a real value, and a receiver treats UNSPECIFIED as an error (`INVALID_ARGUMENT` for a request, a server bug for a response); a domain enum keeps only real values and the proto ↔ domain mapping layer filters UNSPECIFIED; an already published enum keeps its numbering.
