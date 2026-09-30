# UI: screens, copy and forms

## URL query as the source of truth

- Bare URL entry: give `/path` without a query (bookmark, refresh, external link) a default in the hook/param resolver (`const step = isValidStep(params.step) ? params.step : "settings";`); when a page moves from `useState("...")` to URL params, that default is the old initial value.
- Render-time correction + URL correction: when a URL step page corrects the step on deep link/refresh, compute the corrected value for rendering, keep `useEffect` + `router.replace` only for the address bar, and comment the split of roles; `useEffect` + `router.replace` alone renders one blank frame first:
  ```tsx
  const effectiveStep =
    step === "creative" && state === null ? "settings" : step;

  useEffect(() => {
    if (step === "creative" && state === null) {
      router.replace(settingsUrl);
    }
  }, [step, state, router]);

  // JSX에서는 step 대신 effectiveStep을 쓴다
  ```

## Copy and toasts

- Before writing user-facing copy, cross-check the wording by global grep across 2–3 modules ("다시 시도해 주세요" vs "다시 시도해주세요").
- Single-sentence toast: `title="~에 실패했어요"` + `description="잠시 후 다시 시도해주세요"`; fold extra facts (already saved) into that one sentence.
- One "save": use one "save" wording in copy for both create and update.

## Components and forms

- UI defaults are FE responsibility: set the initial radio/select value in the FE and declare the field required in the BE payload; keep a BE default only when omitting the field is a meaningful business state (`target_age_ranges_json={}` = no targeting, with its reason in a comment); remove a BE default that validation rejects anyway (`budget=0`) or that the UI also defines:
  ```python
  # 지적 대상: UI 초기값을 BE에도 둔다
  revenue_type: CampaignRevenueType = Field(default=CampaignRevenueType.CPC)
  target_sex_type: CampaignTargetSexType = Field(default=CampaignTargetSexType.ALL)
  # 맞는 형태: BE는 받기만 하고 FE가 정한다
  revenue_type: CampaignRevenueType = Field(...)
  target_sex_type: CampaignTargetSexType = Field(...)
  ```
- Form field subscription (TanStack Form): wrap every value-driven toggle/conditional in the `form.Field name="showDailyBudget"` render prop instead of reading `form.state.values.showDailyBudget` directly.
- Icon color prop: `({ color = "currentColor", size = 20, className }: IconProps)` with `fill={color}`.
- bootstrap-vue `v-b-popover`: pass the object form `{ content, html: true }` instead of the `.html` modifier.
- i18n keys ship with the rendering component: add en + ko keys in the PR of the component that renders them and keep a data-layer PR (repo/model/store) at zero i18n; pre-extract only executable code for a planned later PR.

## CSS layout

- Flex scroll container moved into a grid area: give the parent `grid-row` a fixed/bounded height and put `min-height: 0` on every link of the flex chain; an `auto` row grows without bound, and one missing `min-height: 0` breaks auto-scroll without an error.
