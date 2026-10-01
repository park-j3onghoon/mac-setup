# Types: enums, booleans and constrained values

- Make illegal states unrepresentable: model a kind/state/mode argument as an enum even with two values (`kind=ExitKind.STOP_LOSS`), and use a boolean only for an on/off flag (`verbose`, `dry_run`); replace two booleans (`is_tp` + `is_sl`) with one enum; replace an optional field plus a same-root boolean (`take_profit` + `is_take_profit`) with one field; put fields that travel with a variant in a discriminated union; give a constrained value a constrained type.

## Python

- Collection default: `list[str] = []`.
- Constrained values get a constrained type: `list[EnumA | EnumB]`, with the same Enum Union on the DTO and repo; with `class X(str, Enum)`, set `use_enum_values=True` on the DTO.
- TYPE_CHECKING symbols stay in annotations; a runtime use raises `NameError` that mypy and the build miss and only pytest catches.
- dataclass vs dict: keep dict kwargs for an entity API in sentinel style (`None` = no change, `unset_*` = explicit unset); adopt a dataclass only together with an `UNSET` sentinel / separate-method refactor.

## Frontend

- Zod input vs values: when Values from `onSubmit` go back into `defaultValues` (Input), convert them in one helper and use `as unknown as T` only there, where a type predicate cannot express the relation; the move passes with a "nullable → non-null + validation" transform and breaks at runtime once a `string → Date` transform is added:
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
