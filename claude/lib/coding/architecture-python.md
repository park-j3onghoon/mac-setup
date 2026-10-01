# Architecture: Python

- Thin entrypoint as a DRF view: build the UseCase with the repo → `_build_user_info(request)` → request DTO from `**request.query_params.dict()` / `**kwargs` → `use_case.execute(user_info, request_dto)` → `Response(data=response_dto.dict(), status=...)`.
