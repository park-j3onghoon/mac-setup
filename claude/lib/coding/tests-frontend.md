# Tests: Frontend

- Test-only attributes (`data-testid`) ship in the same PR as the test that queries them (`getByTestId`); otherwise defer the attribute.
- Dedup and shared setup: the shared fixture file is a vitest shared setup module.
