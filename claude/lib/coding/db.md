# DB (MySQL)

For Python code, also Read `~/.claude/lib/coding/db-python.md`.

## Types

- `user_id` is int.
- Use an enum for a column that holds a kind, state or mode.
- Leave integer columns on the implicit default 0.
- Time columns are `timestamp`.
- Give varchar 20–30% headroom over the longest expected value.

## Enum columns

- Make the first enum value `''`. When `''` has a clearly useful meaning, name its member for that meaning (`UNKNOWN`, `ALL`) and keep it in the domain enum; otherwise name it `UNSPECIFIED`, leave it out of the domain enum, and have the repository map it to null for an optional field or reject it for a required one.

## Charset

- Use ascii by default and utf8mb4 only for columns that store Korean or other non-ASCII text.

## Column order (top → bottom)

- FK/relations to other tables → fact values → varchar/json.

## Aggregate counters

- When the aggregated rows reach 1,000, cache a counter: update it at write time and read only the counter, e.g. progress = `total_count` (fixed at run start) / `completed_count` (incremented per item).

## updated_at

- Leave `updated_at` to the DDL `ON UPDATE CURRENT_TIMESTAMP`: when a change relies on it, confirm it in the live table DDL (the DBA applies it outside migrations), on a legacy table by checking staging `information_schema.COLUMNS.EXTRA` for `on update CURRENT_TIMESTAMP`; set it by hand only on a legacy table without it.

## Transactions and locks

- Lock across the network by workload: with a single-worker batch, rare manual triggers and a single-purpose low-contention row, hold `SELECT … FOR UPDATE` through the external call such as an SES send; with multiple workers, commit a SENDING state and use compare-and-set without a lock.
- Dedup read under `FOR UPDATE`: lock all candidate rows without a status filter and decide after the lock is held.
- Check-then-insert: serialize with `GET_LOCK`, a unique constraint or a single entry point; a status value does not stop a concurrent INSERT.
