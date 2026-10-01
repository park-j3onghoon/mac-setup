# DB (MySQL) and repositories

For Python code, also Read `~/.claude/lib/coding/db-python.md`.

## Types

- `user_id` is int.
- Use an enum where possible.
- Leave integer columns on the implicit default 0.
- Time columns are `timestamp`.
- Give varchar 20–30% headroom over the longest expected value.

## Enum columns

- Make the first enum value `''`. When `''` has a clearly useful meaning, name its member for that meaning (`UNKNOWN`, `ALL`) and keep it in the domain enum; otherwise name it `UNSPECIFIED`, leave it out of the domain enum, and have the repository map it to `None` for an optional field or reject it for a required one.

## Charset

- Use ascii by default and utf8mb4 only for columns that store Korean or other non-ASCII text.

## Column order (top → bottom)

- FK/relations to other tables → fact values → varchar/json.

## Aggregate counters (cached fields)

- When the aggregated rows reach 1,000, cache a counter: update it at write time and read only the counter, e.g. progress = `total_count` (fixed at run start) / `completed_count` (incremented per item).

## updated_at

- Leave `updated_at` to the DDL `ON UPDATE CURRENT_TIMESTAMP`: when a change relies on it, confirm it in the live table DDL (the DBA applies it outside migrations), on a legacy table by checking staging `information_schema.COLUMNS.EXTRA` for `on update CURRENT_TIMESTAMP`; set it by hand only on a legacy table without it.

## Transactions and locks

- Lock across the network by workload: with a single-worker batch, rare manual triggers and a single-purpose low-contention row, hold `SELECT … FOR UPDATE` (Django `select_for_update`) through the external call such as an SES send; with multiple workers, commit a SENDING state and use compare-and-set without a lock.
- Dedup read under `FOR UPDATE`: lock all candidate rows without a status filter and decide after the lock is held.
- Check-then-insert: serialize with `GET_LOCK`, a unique constraint or a single entry point; a status value does not stop a concurrent INSERT.

## Repositories

- Return types: a repository method returns entities or aggregates. When a caller needs only a count, an existence check or ids, add a method that returns only that: an int count (`count_by_status()`), a bool existence check, a list of int ids.
- Mapping and saving: keep ORM mapping and enum conversion inside the repository, converting an enum by value (`ModelEnum(domain_enum.value)`); callers pass entities (`repo.save(entity)`), and the repository saves each as given, stripping only `id`/`created_at`/`updated_at`. When only some fields may change, decide which before calling the repository (DTO design, use-case branching or entity routing).
- Pagination: the repository takes `limit`/`offset` and returns `count` + `items`; the use case computes `num_pages`/`has_next`/`has_previous` and the page number.
- Timezone anchoring: when a repository anchors a received date to a zone's midnight, pass the calendar date in that zone, after reading the anchoring in the repository's code. A date taken from a UTC instant is a day off during UTC 15:00–23:59 for Asia/Seoul.
- Normalized values: when raw DB values need a canonical form (`schedule/live/pause/close` → `APPROVE`), keep the raw value in `_to_entity` and produce the canonical one in a separate entity field; response DTOs and filter queries use that domain mapping. Normalizing in `_to_entity` breaks the write when the canonical value is missing from the DB enum.
