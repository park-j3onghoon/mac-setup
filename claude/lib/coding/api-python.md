# API contracts: Python

- PATCH DTO: HTTP method `patch()`, every field `Optional[T] = None`, `Config.extra='forbid'`, the named fields read with `dict(exclude_unset=True)` (a key sent as null stays in it), the pre-validator `_reject_explicit_null` only on fields that cannot be empty, a null passed to the entity as `unset_{field}=True`, and cross-field checks (dates/budget) only over fields present in the partial; a check over absent fields re-validates a name-only edit against old values.
