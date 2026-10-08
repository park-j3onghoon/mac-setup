# Process: Frontend

- Build after moves: the build is `npm run build`, an absolute import is a path alias, and jest resolves imports that vite/webpack reject.
- Building against an unfinished backend: keep every unconfirmed part of the contract (request, response, status, errors, permission, idempotency) in one type, transform and fixture; generate the fixtures from the proto or OpenAPI samples, and make a staging contract smoke test a merge blocker.
- Live screens on an unverified backend: ship them as a new component behind a feature flag that shows an error state on 404, 403 and 500, and keep the old component until the flag is removed.
