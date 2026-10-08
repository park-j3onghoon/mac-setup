# Design

- Four rules: when design choices conflict, prefer in this order: passes the tests, reveals intention, no duplication, fewest elements.
- DRY of knowledge: give every fact or decision one source of truth: when the same knowledge (a business decision, a discriminating rule) appears a second time, extract it into its domain module; keep code that only looks alike and changes for different reasons as separate copies.
- Abstraction discipline: when a formatting/conversion function would become a cross-module util, wait for the Rule of Three; extracting shared code early for a planned later PR is allowed; keep a function with one call site when it is the single defence point (encapsulating an unsafe cast, a drift guard); extract step functions inside the module freely; in doubt, keep it local.
- YAGNI: build only what the task asks for now, and ask before adding a class variable, function or layer outside the requested change; add a user-facing safeguard only with a PRD/design basis or to prevent irreversible user loss.
- KISS: choose the simplest thing that works, and remove accidental complexity before adding structure.
