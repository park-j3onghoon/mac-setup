# DB (MySQL)

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

- `ON UPDATE CURRENT_TIMESTAMP` is the DDL convention for `updated_at`, applied by the DBA out-of-band, so reviewers confirm it in the live table DDL, its only source.
- Legacy tables may lack it (e.g. a legacy table with a `datetime(6)` column, no ON UPDATE and `auto_now` only); verify per table via staging `information_schema.COLUMNS.EXTRA` (`on update CURRENT_TIMESTAMP`) before relying on `queryset.update()`.

## Transactions and locks

- Lock across the network by workload: with a single-worker batch + rare manual trigger + single-purpose low-contention row, hold `SELECT … FOR UPDATE` (Django `select_for_update`) through the external call such as an SES send (lock-during-send), simpler than a SENDING/IN_PROGRESS state plus reaper, since InnoDB `FOR UPDATE` blocks only locking reads/writes (plain reads use the MVCC snapshot) and releases on session death; with high concurrency (multiple workers) use a committed SENDING state + compare-and-set without a lock.
- Dedup read under `FOR UPDATE`: lock all candidate rows and decide after the lock is held; a status filter in the locking read drops a row that turned SENT while waiting and opens a "none, create new" hole.
- Check-then-insert: serialize with `GET_LOCK`, a unique constraint or a single entry point; a status value cannot stop a concurrent INSERT.
