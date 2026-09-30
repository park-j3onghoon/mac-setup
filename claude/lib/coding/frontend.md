# Frontend (React / Vue / TypeScript)

## URL query as the source of truth

- Bare URL entry: give `/path` without a query (bookmark, refresh, external link) a default in the hook/param resolver: `const step = isValidStep(params.step) ? params.step : "settings";`.
- URL-driven refactors keep the old initial state: when a page moves from `useState("...")` to URL params, reproduce that initial value at hook level.
- Render-time correction + URL correction: when a URL step page corrects the step on deep link/refresh, compute the corrected value for rendering, keep `useEffect` + `router.replace` only for the address bar, and comment the split of roles; `useEffect` + `router.replace` alone renders one blank frame first:
  ```tsx
  const effectiveStep =
    step === "creative" && state === null ? "settings" : step;

  useEffect(() => {
    if (step === "creative" && state === null) {
      router.replace(settingsUrl);
    }
  }, [step, state, router]);

  // JSX uses effectiveStep instead of step
  ```

## Types

- Zod input vs values: when Values from `onSubmit` go back into `defaultValues` (Input), convert them in one helper; the move passes with a "nullable → non-null + validation" transform and breaks at runtime once a `string → Date` transform is added:
  ```ts
  function valuesToSettingsInput(v: Values): Partial<Input> {
    return v as unknown as Partial<Input>;
  }
  ```
- `as unknown as T`: use it only where a type predicate cannot express the relation (the Zod pre/post-transform round trip), inside that single helper.
- Discriminated union for fields that travel with an action: the caller narrows on `action`:
  ```ts
  type NextAction =
    | { action: "create" }
    | { action: "update"; campaignId: number }
    | { action: "skip"; campaignId: number };
  // caller: if (a.action === "update") updateCampaign({ id: a.campaignId, ... })
  ```
- Update payload drops create-only fields explicitly: destructure them out (spread skips TS excess-property checks) and keep `UpdateRequest = Omit<CreateRequest, "revenueType"> & { id }` aligned with the payload:
  ```ts
  const { revenueType: _revenueType, ...updateBody } = body;
  await mutate({ id, ...updateBody });
  ```
- Set-equality utils: state "inputs contain no duplicates" in the function comment of `hasSameMembers` and friends (`[A,A,B]` and `[A,B,B]` compare equal); when duplicates must count, compare sorted copies or count maps.

## Async handlers and errors

- No throw from an async handler chain: in a Promise-returning `onClick`, an overlay `onConfirm` or a wrapper that calls the callback and drops the return, a throw becomes an unhandled rejection; grep each layer (`handleConfirm` → `Modal.BottomSheet onClick wrapper` → React `onClick`) for an `await`/`.catch`; with none, catch, show a toast and return without rethrowing. An unreachable branch throws `new Error('unreachable: ...')`.
- Modals close on their own: let the modal close and offer retry through the button; `catch {}` without a binding is fine for confirm-modal branching alongside "mutation errors are handled in `onError`".

## Copy and toasts

- Before writing user-facing copy, cross-check the wording by global grep across 2–3 modules ("다시 시도해 주세요" vs "다시 시도해주세요").
- Single-sentence toast: `title="~에 실패했어요"` + `description="잠시 후 다시 시도해주세요"`; fold extra facts (already saved) into that one sentence.
- One "save": use one "save" wording in copy for both create and update.

## Component and form conventions

- UI defaults are FE responsibility: set the initial radio/select value in the FE and declare the field required in the BE payload; keep a BE default only when omitting the field is a meaningful business state (`target_age_ranges_json={}` = no targeting, with its reason in a comment); remove a BE default that validation rejects anyway (`budget=0`) or that the UI also defines:
  ```python
  # Bad: the UI initial value duplicated in the BE
  revenue_type: CampaignRevenueType = Field(default=CampaignRevenueType.CPC)
  target_sex_type: CampaignTargetSexType = Field(default=CampaignTargetSexType.ALL)
  # Good: BE receives, FE decides
  revenue_type: CampaignRevenueType = Field(...)
  target_sex_type: CampaignTargetSexType = Field(...)
  ```
- Form field subscription (TanStack Form): wrap every value-driven toggle/conditional in the `form.Field name="showDailyBudget"` render prop instead of reading `form.state.values.showDailyBudget` directly.
- Icon color prop: `({ color = "currentColor", size = 20, className }: IconProps)` with `fill={color}`.
- bootstrap-vue `v-b-popover`: pass the object form `{ content, html: true }` instead of the `.html` modifier.
- i18n keys ship with the rendering component: add en + ko keys in the PR of the component that renders them and keep a data-layer PR (repo/model/store) at zero i18n; pre-extract only executable code for a planned later PR.

## Layout

- Flex scroll container moved into a grid area: give the parent `grid-row` a fixed/bounded height and put `min-height: 0` on every link of the flex chain; an `auto` row grows without bound, and one missing `min-height: 0` breaks auto-scroll without an error.

## Tests

- Test-only attributes (`data-testid`) ship in the same PR as the test that queries them (`getByTestId`); otherwise defer the attribute.
- Shared test helpers live in a vitest shared helper module.

## Build

- Build after a move: run `npm run build` and prefer absolute path aliases; jest resolves imports that vite/webpack reject.
