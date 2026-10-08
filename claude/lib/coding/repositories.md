# Repositories

For Python code, also Read `~/.claude/lib/coding/repositories-python.md`.

- Return types: a repository method returns entities or aggregates. When a caller needs only a count, an existence check or ids, add a method that returns only that: an int count (`count_by_status()`), a bool existence check, a list of int ids.
- Mapping and saving: keep ORM mapping and enum conversion inside the repository, converting an enum by value (`ModelEnum(domain_enum.value)`); callers pass entities (`repo.save(entity)`), and the repository saves each as given, stripping only `id`/`created_at`/`updated_at`. When only some fields may change, decide which before calling the repository (DTO design, use-case branching or entity routing).
- Pagination: the repository takes `limit`/`offset` and returns `count` + `items`; the use case computes `num_pages`/`has_next`/`has_previous` and the page number.
- Timezone anchoring: when a repository anchors a received date to a zone's midnight, pass the calendar date in that zone, after reading the anchoring in the repository's code. A date taken from a UTC instant is a day off during UTC 15:00–23:59 for Asia/Seoul.
- Normalized values: when raw DB values need a canonical form (`schedule/live/pause/close` → `APPROVE`), keep the raw value in `_to_entity` and produce the canonical one in a separate entity field; response DTOs and filter queries use that domain mapping. Normalizing in `_to_entity` breaks the write when the canonical value is missing from the DB enum.
