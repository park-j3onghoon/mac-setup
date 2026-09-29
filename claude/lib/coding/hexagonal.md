# Hexagonal architecture: ports and adapters

## Ports

- The domain defines each port; adapters implement it.
- Narrow ports: expose methods that return exactly what a caller needs (`count_by_status()`).
- Deep module: a small interface over a deep implementation: `repo.save(entity)` hides ORM mapping, enum conversion and system-field stripping from every caller.

## Repositories

- Contract: return aggregates/entities through the domain-defined port by default and add count/summary/id projections explicitly. Count or check existence through a projection method returning e.g. a list of ids instead of hydrating and discarding; the return type itself says "projection" and suits command-internal computation such as a progress denominator.
- Store the entity as given: keep the modifiable-field whitelist/blacklist in the use case and let infrastructure strip only `id`/`created_at`/`updated_at`; a repository that judges which fields may change blocks approve/reject/cancel use cases from sharing one `update()`. Express such rules through DTO design, use-case branching or entity routing.
- Pagination meta in the application: the repository takes `limit`/`offset` and returns `count` + `items`; the use case computes `num_pages`/`has_next`/`has_previous`/page number; a repository that knows `page_number`/`page_size` has a business contract leaking into infrastructure.
- Timezone anchoring: when a repository anchors a received date to a zone's midnight, pass the calendar date in that zone; the date of a UTC instant alone is off by one during UTC 15:00–23:59 for Asia/Seoul. Check the repository's actual internals, beyond its comments or types.
- Normalize in the response layer: normalizing raw DB values on read in `_to_entity` (`schedule/live/pause/close` → canonical `APPROVE`) collides on write when the canonical value is absent from the DB enum; normalize in the response payload layer, or keep the raw value in the entity and expose the normalized view as a separate field.

## Adapters to other services

- Gateway / BFF / adapter: transform and forward only; defaults, field merge/preserve and invariants stay in the service that owns the domain, because a caller-side read-modify-write to "preserve missing fields" scatters the rule, races under concurrency and drifts.
- Verify before build: read the dependent service's actual write/merge/error behaviour (its proto, entity, repository, especially across repos) before adding field preservation, default mapping or error translation on the caller side; an assumed contract ("upsert is full-replace") turns into partial updates and silently dropped fields.
- Timeouts: set explicit connect/read timeouts on every call to another system (HTTP, gRPC, SMTP), above all while a DB transaction or lock is held, so the timeout bounds the lock hold time.
