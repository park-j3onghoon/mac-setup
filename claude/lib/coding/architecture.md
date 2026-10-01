# Architecture: layers, use cases, repositories and adapters

## Layers and use cases

- Dependency rule: point dependencies only inward: presentation → application → domain, and infrastructure → domain by implementing the ports the domain defines. Between two modules of the same layer, keep the dependency one way too: when A references B, B never references A.
- Thin entrypoint: an entrypoint (view, servicer, CLI, consumer), list and retrieve included, only checks type and format, builds the use case, maps request → DTO, calls it, and maps result → response.
- One scenario per use case: a use case runs one user scenario end to end; it reaches the ORM, HTTP clients and email rendering only through ports that adapters (repositories, gateways, notifiers, publishers) implement.
- Use cases call no other use case: put the steps several use cases share in a service or an atomic validator (`validate_order_ownership`); a service calls domain methods and ports in a fixed order, runs inside the calling use case's unit of work, and never calls a use case.
- Domain vs application placement: put every business rule in the domain, including one that only a single operation checks (`request.submit()` requires every field while a draft may stay empty). Services and use cases decide only the order of calls, access control (whether the caller may reach this data: tenant, ownership, held role), the transaction and calls through ports. Split constants and exceptions the same way (`domain/constants` vs `application/constants`).
- Commands and queries: a command use case has side effects and returns a minimal id/status; a query use case has none. Split read and write models when their shapes or paths diverge, and give an externally served query endpoint its own read model rather than a repository projection.

## Repositories

- Return types: a repository method returns entities or aggregates. When a caller needs only a count, an existence check or ids, add a method that returns just that (`count_by_status()`, a list of ids).
- Mapping and saving: keep ORM mapping and enum conversion inside the repository, converting an enum by value (`ModelEnum(domain_enum.value)`); callers pass entities (`repo.save(entity)`), and the repository saves each as given, stripping only `id`/`created_at`/`updated_at`. When only some fields may change, decide which before calling the repository (DTO design, use-case branching or entity routing).
- Pagination: the repository takes `limit`/`offset` and returns `count` + `items`; the use case computes `num_pages`/`has_next`/`has_previous` and the page number.
- Timezone anchoring: when a repository anchors a received date to a zone's midnight, pass the calendar date in that zone, after reading the anchoring in the repository's code. A date taken from a UTC instant is a day off during UTC 15:00–23:59 for Asia/Seoul.
- Normalized values: when raw DB values need a canonical form (`schedule/live/pause/close` → `APPROVE`), keep the raw value in `_to_entity` and produce the canonical one in a separate entity field; response DTOs and filter queries use that domain mapping. Normalizing in `_to_entity` breaks the write when the canonical value is missing from the DB enum.

## Adapters to other systems

- Bounded context: when data comes from another service or module, translate it in the adapter into this domain's own entities and enums.
- Gateway / BFF / adapter: transform and forward only; put defaults, field merge/preserve (including a read-modify-write that preserves missing fields) and invariants in the service that owns the domain.
- Verify before build: before adding field preservation, default mapping or error translation on the caller side, read the dependent service's write/merge/error behaviour in its proto, entity and repository (for example, whether an upsert replaces the whole record or merges fields).
- Timeouts: set explicit connect/read timeouts on every call to another system (HTTP, gRPC, SMTP).

## Python

- Thin entrypoint as a DRF view: build the UseCase with the repo → `_build_user_info(request)` → request DTO from `**request.query_params.dict()` / `**kwargs` → `use_case.execute(user_info, request_dto)` → `Response(data=response_dto.dict(), status=...)`.
- Return types: an id projection returns `list[int]`, a count `int`, an existence check `bool`.
- Timezone anchoring: when the repo anchors with `arrow.replace(tzinfo='Asia/Seoul').floor('day')`, pass `astimezone(tz).date()`.
- Timeouts: Django `EMAIL_TIMEOUT`, requests `timeout=`, gRPC `timeout=`.
