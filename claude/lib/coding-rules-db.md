# Coding Rules: DB schema (MySQL)

Applies when writing schema/migrations for team-style MySQL, together with `coding-rules.md` (core).

## Types

- `user_id` is int.
- Enum where possible: stored internally as an integer.
- Integer columns rely on the implicit default 0.
- Time columns are `timestamp`.
- varchar gets 20–30% headroom over the longest expected value.

## Enum columns

- First enum value is `''` because an unmatched value falls back to the first value.
- Column name `{enum_type}_type` for every enum column.

## Charset

- ascii by default; utf8mb4 only where Korean etc. is stored: a Korean character costs 3 bytes, ascii 1.

## Column order (top → bottom)

- FK/relations to other tables → fact values → varchar/json.

## Aggregate counters (cached fields)

- Cache a counter when the aggregated rows reach 1,000; a user hammering refresh makes per-read COUNT/SUM load scale with read frequency; update the counter at write time and read only the counter, e.g. progress = `total_count` (fixed at run start) / `completed_count` (incremented per item).

## updated_at

- `ON UPDATE CURRENT_TIMESTAMP` is the DDL convention for `updated_at`, applied by the DBA out-of-band, so reviewers confirm it in the live table DDL, its only source (ORM consequence: `coding-rules-python.md` "Never set updated_at by hand").
- Legacy tables may lack it (e.g. a legacy table with a `datetime(6)` column, no ON UPDATE and `auto_now` only); verify per table via staging `information_schema.COLUMNS.EXTRA` (`on update CURRENT_TIMESTAMP`) before relying on `queryset.update()`.
