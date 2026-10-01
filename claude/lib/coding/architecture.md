# Architecture: layers and what each holds

## Layers

- Dependency rule: point dependencies only inward: presentation → application → domain, and infrastructure → domain by implementing the ports the domain defines. Between two modules of the same layer, keep the dependency one way too: when A references B, B never references A.
- Convention breaks ties: when these rules allow several placements or structures, follow the one the project already uses.

## Presentation

- Thin entrypoint: an entrypoint (view, servicer, CLI, consumer), list and retrieve included, only checks type and format, builds the use case, maps request → DTO, calls it, and maps result → response.

## Application

- One scenario per use case: a use case runs one user scenario end to end.
- Use cases call no other use case: put the steps several use cases share in a service or an atomic validator (`validate_order_ownership`); a service calls domain methods and ports in a fixed order, runs inside the calling use case's unit of work, and never calls a use case.
- Commands and queries: a command use case has side effects and returns a minimal id/status; a query use case has none. Split read and write models when their shapes or paths diverge, and give an externally served query endpoint its own read model rather than a repository projection.

## Domain

- Domain vs application placement: put every business rule in the domain, including one that only a single operation checks (`request.submit()` requires every field while a draft may stay empty). Services and use cases decide only the order of calls, access control (whether the caller may reach this data: tenant, ownership, held role), the transaction and calls through ports. Split constants and exceptions the same way (`domain/constants` vs `application/constants`).
- Ports: the domain defines an interface (port) for each outside resource, and use cases and services reach the ORM, HTTP clients and email rendering only through ports.

## Infrastructure

- Adapters: a repository (storage), a gateway (another service), a notifier (email) or a publisher (messaging) implements a port; repository rules are in `~/.claude/lib/coding/db.md`.
- Bounded context: when data comes from another service or module, translate it in the adapter into this domain's own entities and enums.
- Gateway / BFF / adapter: transform and forward only; put defaults, field merge/preserve (including a read-modify-write that preserves missing fields) and invariants in the service that owns the domain.

## Python

- Thin entrypoint as a DRF view: build the UseCase with the repo → `_build_user_info(request)` → request DTO from `**request.query_params.dict()` / `**kwargs` → `use_case.execute(user_info, request_dto)` → `Response(data=response_dto.dict(), status=...)`.
