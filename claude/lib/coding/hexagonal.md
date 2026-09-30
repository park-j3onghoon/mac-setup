# Hexagonal architecture: ports and adapters

## Repositories

- Return types: a repository method returns entities or aggregates. When a caller needs only a count, an existence check or ids, add a method that returns just that (`count_by_status()`, a list of ids).
- Mapping: keep ORM mapping, enum conversion and system-field stripping inside the repository; callers pass and receive entities (`repo.save(entity)`).
- Saving: save the entity as given, stripping only `id`/`created_at`/`updated_at`. When only some fields may change, decide which before calling the repository (DTO design, use-case branching or entity routing).
- Pagination: the repository takes `limit`/`offset` and returns `count` + `items`; the use case computes `num_pages`/`has_next`/`has_previous` and the page number.
- Timezone anchoring: when a repository anchors a received date to a zone's midnight, pass the calendar date in that zone, after reading the anchoring in the repository's code.
- Normalized values: when raw DB values need a canonical form (`schedule/live/pause/close` → `APPROVE`), keep the raw value in `_to_entity` and produce the canonical one in the response payload or a separate entity field.

## Adapters to other services

- Gateway / BFF / adapter: transform and forward only; put defaults, field merge/preserve and invariants in the service that owns the domain.
- Verify before build: before adding field preservation, default mapping or error translation on the caller side, read the dependent service's write/merge/error behaviour in its proto, entity and repository.
- Timeouts: set explicit connect/read timeouts on every call to another system (HTTP, gRPC, SMTP).
