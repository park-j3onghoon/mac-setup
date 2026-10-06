# UI: screens, copy and forms

For frontend code, also Read `~/.claude/lib/coding/ui-frontend.md`.

## URL query as the source of truth

- Bare URL entry: give `/path` without a query (bookmark, refresh, external link) a default in the param resolver (`const step = isKnownStep(params.step) ? params.step : "cart";`); when a page moves from local state to URL params, that default is the old initial value.
- Render-time correction + URL correction: when a URL step page corrects the step on deep link/refresh, compute the corrected value for rendering, correct the address bar separately, and comment the split of roles.

## Copy and toasts

- Before writing user-facing copy, cross-check the wording by global grep across 2–3 modules ("다시 시도해 주세요" vs "다시 시도해주세요").
- Single-sentence toast: `title="~에 실패했어요"` + `description="잠시 후 다시 시도해주세요"`; fold extra facts (already saved) into that one sentence.
- One "save": use one "save" wording in copy for both create and update.

## Components and forms

- UI defaults are FE responsibility: set the initial radio/select value in the FE.
- i18n keys ship with the rendering component: add en + ko keys in the PR of the component that renders them and keep a data-layer PR (repo/model/store) at zero i18n; pre-extract only executable code for a planned later PR.

## CSS layout

- Flex scroll container moved into a grid area: give the parent `grid-row` a fixed/bounded height and put `min-height: 0` on every link of the flex chain; an `auto` row grows without bound, and one missing `min-height: 0` breaks auto-scroll without an error.
