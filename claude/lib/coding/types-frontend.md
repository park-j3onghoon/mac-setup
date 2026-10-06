# Types: Frontend

- Zod input vs values: when Values from `onSubmit` go back into `defaultValues` (Input), convert them in one function and use `as unknown as T` only there, where a type predicate cannot express the relation; the move passes with a "nullable → non-null + validation" transform and breaks at runtime once a `string → Date` transform is added:
  ```ts
  function convertValuesToSettingsInput(values: Values): Partial<Input> {
    return values as unknown as Partial<Input>;
  }
  ```
- Discriminated union for fields that travel with an action: the caller narrows on `action`:
  ```ts
  type QueuedAction =
    | { action: "create" }
    | { action: "update"; bookId: number }
    | { action: "skip"; bookId: number };
  // 호출하는 쪽: if (queuedAction.action === "update") updateBook({ id: queuedAction.bookId, ... })
  ```
- Update request body drops create-only fields explicitly: destructure them out (spread skips TS excess-property checks) and keep `UpdateRequest = Omit<CreateRequest, "loanType"> & { id }` aligned with the body:
  ```ts
  const { loanType: _loanType, ...updateBody } = body;
  await mutate({ id, ...updateBody });
  ```
