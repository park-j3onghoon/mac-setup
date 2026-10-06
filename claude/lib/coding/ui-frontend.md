# UI: Frontend

- Bare URL entry: when a page moves from `useState("...")` to URL params, the default in the hook is the old `useState` argument.
- Render-time correction + URL correction: keep `useEffect` + `router.replace` only for the address bar and render from the corrected value; `useEffect` + `router.replace` alone renders one blank frame first:
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
- Form field subscription (TanStack Form): wrap every value-driven toggle/conditional in the `form.Field name="showDailyBudget"` render prop instead of reading `form.state.values.showDailyBudget` directly.
- Icon color prop: `({ color = "currentColor", size = 20, className }: IconProps)` with `fill={color}`.
- bootstrap-vue `v-b-popover`: pass the object form `{ content, html: true }` instead of the `.html` modifier.
