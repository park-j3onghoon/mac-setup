# API contracts

For proto files, also Read `~/.claude/lib/coding/api-proto.md`; for Python code, `~/.claude/lib/coding/api-python.md`.

- 404 vs 200 + null: `GET /resources/{id}` for a missing resource returns 404 (`NotFound`); a condition-based single lookup ("the in-progress amendment") with no match returns 200 with a null field.
- Partial update: the request names the fields to change, by `update_mask` in proto and by the keys present in a JSON body. Set each named field to the sent value, clear it when that value is null (JSON) or empty (proto), and leave every other field as it is; a clear on a field that cannot be empty fails with 400 (`INVALID_ARGUMENT`).
- OpenAPI spec with every endpoint change: a repo's `docs/apis/paths/{console}/{module}/user.yaml|admin.yaml`; a legacy project one yaml per endpoint under `docs/openapi/{app}/` registered by `$ref` in `docs/openapi/root.yaml` `paths:`; add it whenever a similar endpoint is documented; file = top-level `post:`/`get:` + summary/tags/operationId/requestBody·parameters/responses 200/202/400/401/403/500.
