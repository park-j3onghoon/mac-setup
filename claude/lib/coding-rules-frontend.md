# Coding Rules: Frontend (React / Vue / TypeScript)

Applies together with `coding-rules.md` (core); Vue + main projects (an ads console) also read `coding-rules-vue.md`. Test-only attributes such as `data-testid`: core Tests "Test-only attributes".

## URL query as the source of truth

- Bare URL entry resolves: `/path` without a query (bookmark, refresh, external link) renders instead of `isValid=false`; default in the hook/param resolver: `const step = isValidStep(params.step) ? params.step : "settings";`.
- URL-driven refactors keep the old initial state: a page moving from `useState("...")` to URL params reproduces that initial value at hook level.
- Render-time correction + URL correction: on deep link/refresh into a URL step page, `useEffect` + `router.replace` alone shows one blank frame (no section matches on the first render); compute the corrected value for rendering, keep the effect only for the address bar, and comment the split of roles:
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

- Zod input vs values: `z.input` (pre-transform) and `z.infer` (post-transform) are different types: `defaultValues` takes Input, onSubmit yields Values, so storing Values in state and re-passing them as `defaultValues` is a Values → Input move that passes today only because the transform is "nullable → non-null + validation" and breaks at runtime once `string → Date` is added; encapsulate the move in one helper so TS catches drift there:
  ```ts
  function valuesToSettingsInput(v: Values): Partial<Input> {
    return v as unknown as Partial<Input>;
  }
  ```
- `as unknown as T` is avoided by default and allowed only where a type predicate cannot express the relation (the Zod pre/post-transform round trip), inside that single helper.
- Discriminated union for fields that travel with an action: the caller narrows on `action` instead of asserting `as number`:
  ```ts
  // Before
  type NextAction = "create" | "update" | "skip";
  // caller: updateCampaign({ id: campaignId as number, ... })  ← assertion needed

  // After
  type NextAction =
    | { action: "create" }
    | { action: "update"; campaignId: number }
    | { action: "skip"; campaignId: number };
  // caller: if (a.action === "update") updateCampaign({ id: a.campaignId, ... })
  ```
- Update payload drops create-only fields explicitly: spread bypasses TS excess-property checks, so destructure them out and keep `UpdateRequest = Omit<CreateRequest, "revenueType"> & { id }` aligned with the payload:
  ```ts
  const { revenueType: _revenueType, ...updateBody } = body;
  await mutate({ id, ...updateBody });
  ```
- Set-equality utils state their precondition: `hasSameMembers` and friends carry "inputs contain no duplicates" in the function comment (`[A,A,B]` vs `[A,B,B]` would match); write a duplicate-tolerant comparison as sort-then-compare or a count-map multiset.

## Async handlers and errors

- No throw from an async handler chain (the invariant case is core Errors "Unreachable branch"): a throw in a Promise-returning `onClick`, overlay `onConfirm` or any "call the callback and drop the return" wrapper becomes an unhandled rejection. Grep each layer (`handleConfirm` → `Modal.BottomSheet onClick wrapper` → React `onClick`) for an `await`/`.catch`; with none, catch, toast and return without rethrow (a rethrow adds monitoring noise and global-handler side effects).
- Modals close on their own: never throw to keep a modal open; allow auto-close and route retry through the button (livecommerce practice); `catch {}` without a binding is fine for confirm-modal branching alongside "mutation errors are handled in `onError`".

## Copy and toasts

- Cross-check wording by global grep across 2–3 modules before writing user-facing copy ("다시 시도해 주세요" vs "다시 시도해주세요").
- Single-sentence toast: `title="~에 실패했어요"` + `description="잠시 후 다시 시도해주세요"`; fold extra facts (already saved) into that one sentence, never a second one.
- One "save" in the user's mental model: the internal create/update branch never surfaces in copy ("수정 실패" is out).

## Component and form conventions

- UI defaults are FE responsibility: the initial radio/select value is a UX decision, so the BE payload declares the field required and only a business "omit is a meaningful state" default stays (`target_age_ranges_json={}` = no targeting, with its reason in a comment); a default that validation rejects anyway (`budget=0`) is removed; review question "is this default also defined in the UI?" → remove (core Function "No unnecessary defaults"):
  ```python
  # Bad: the UI initial value duplicated in the BE
  revenue_type: DisplayCampaignRevenueType = Field(default=DisplayCampaignRevenueType.CPC)
  target_sex_type: DisplayCampaignTargetSexType = Field(default=DisplayCampaignTargetSexType.ALL)
  # Good: BE receives, FE decides
  revenue_type: DisplayCampaignRevenueType = Field(...)
  target_sex_type: DisplayCampaignTargetSexType = Field(...)
  ```
- Form field subscription (TanStack Form): `form.state.values.showDailyBudget` read directly is not subscribed and the UI never updates; wrap every value-driven toggle/conditional in the `form.Field name="showDailyBudget"` render prop (cpas `isAutoDailyBudget`).
- Icon color prop: `({ color = "currentColor", size = 20, className }: IconProps)` with `fill={color}`; a hardcoded `fill="currentColor"` ignores `<Icon color="red" />` (the 20+ existing icons follow this).
- bootstrap-vue `v-b-popover` takes the object form `{ content, html: true }` instead of the `.html` modifier; the modifier form spreads raw-HTML popovers with no single place to audit the escaping.
- i18n keys ship with the rendering component: add en + ko keys in the PR of the component that renders them and keep a data-layer PR (repo/model/store) at zero i18n (one PR series, PR1: 3 reviewers flagged unused keys and 443 > 400 lines; moving them made PR2 382); planned pre-extraction applies to executable code only, not to unused keys.

## Layout

- Flex scroll container moved into a grid area: give the parent `grid-row` a fixed/bounded height and put `min-height: 0` on every link of the flex chain; an `auto` row grows without bound as content accumulates, and a missing `min-height: 0` breaks auto-scroll silently (`flex: 1; overflow-y: auto` alone is not enough).
