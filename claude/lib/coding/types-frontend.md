# Types: Frontend

- Zod input vs values: when Values from `onSubmit` go back into `defaultValues` (Input), convert them in one function and use `as unknown as T` only there, where a type predicate cannot express the relation; the move passes with a "nullable → non-null + validation" transform and breaks at runtime once a `string → Date` transform is added:
  ```ts
  function convertValuesToSettingsInput(values: Values): Partial<Input> {
    return values as unknown as Partial<Input>;
  }
  ```
- Discriminated union for fields that travel with an action: the caller narrows on `action`:
  ```ts
  type NextAction =
    | { action: "create" }
    | { action: "update"; campaignId: number }
    | { action: "skip"; campaignId: number };
  // 호출하는 쪽: if (nextAction.action === "update") updateCampaign({ id: nextAction.campaignId, ... })
  ```
- Update request body drops create-only fields explicitly: destructure them out (spread skips TS excess-property checks) and keep `UpdateRequest = Omit<CreateRequest, "revenueType"> & { id }` aligned with the body:
  ```ts
  const { revenueType: _revenueType, ...updateBody } = body;
  await mutate({ id, ...updateBody });
  ```
