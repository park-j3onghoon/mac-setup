# API contracts

- 404 vs 200 + null: `GET /resources/{id}` for a missing resource returns 404 (`NotFound`); a condition-based single lookup ("the in-progress amendment") with no match returns 200 with a null field.
- OpenAPI spec with every endpoint change: a repo's `docs/apis/paths/{console}/{module}/user.yaml|admin.yaml`; a legacy project one yaml per endpoint under `docs/openapi/{app}/` registered by `$ref` in `docs/openapi/root.yaml` `paths:`; add it whenever a similar endpoint is documented; file = top-level `post:`/`get:` + summary/tags/operationId/requestBody·parameters/responses 200/202/400/401/403/500.

## proto

- Enum zero value: a new enum reserves 0 for `{ENUM}_UNSPECIFIED` in requests and responses alike and starts real values at 1; the server always sends a real value, and a receiver treats UNSPECIFIED as an error (`INVALID_ARGUMENT` for a request, a server bug for a response); a domain enum keeps only real values and the proto ↔ domain mapping layer filters UNSPECIFIED; an already published enum keeps its numbering.

## Python

- PATCH DTO convention: HTTP method `patch()`, every field `Optional[T] = None`, `Config.extra='forbid'`, partial merge with `exclude_unset=True`, a pre-validator `_disallow_explicit_null` rejecting explicit null (omitted = no change, null = intentional clear), and cross-field checks (dates/budget) only over fields present in the partial; a check over absent fields re-validates a name-only edit against old values.
