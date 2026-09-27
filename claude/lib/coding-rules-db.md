# Coding Rules: DB schema (MySQL)

Applies when writing schema/migrations for team-style MySQL, together with `coding-rules.md` (core).

## Types

- `user_id` is int.
- Enum where possible: stored internally as an integer.
- Integer columns carry no default: the implicit default is already 0.
- `timestamp`, not `datetime(6)`: microseconds are never needed.
- varchar gets 20–30% headroom over the longest expected value.

## Enum columns

- First enum value is `''` because an unmatched value falls back to the first value.
- Column name `{enum_type}_type` for every enum column.

## Charset

- ascii by default; utf8mb4 only where Korean etc. is stored: a Korean character costs 3 bytes, ascii 1.

## Column order (top → bottom)

- Relations first, facts next, wide values last: FK/relations to other tables → fact values → varchar/json.

## Aggregate counters (cached fields)

- Cache a counter when the aggregated rows reach 1,000 (DBA guide); a user hammering refresh makes per-read COUNT/SUM load scale with read frequency; update the counter at write time and read only the counter, e.g. progress = `total_count` (fixed at run start) / `completed_count` (incremented per item).

## updated_at

- `ON UPDATE CURRENT_TIMESTAMP` is the DDL convention for `updated_at`, applied by the DBA out-of-band; it is absent from repo migrations, so its absence in a grep is not a bug (ORM consequence: `coding-rules-python.md` "Never set updated_at by hand").
- Legacy tables may lack it (a legacy billing table `payout_organization`: `datetime(6)`, no ON UPDATE, `auto_now` only); verify per table via staging `information_schema.COLUMNS.EXTRA` (`on update CURRENT_TIMESTAMP`) before relying on `queryset.update()`.
