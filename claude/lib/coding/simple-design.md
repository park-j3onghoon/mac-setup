# Simple Design and refactoring

- Four rules (Kent Beck, in priority order): tests pass, reveals intention, no duplication, fewest elements.
- DRY of knowledge: give every fact or decision one source of truth, and leave apart code that merely looks alike and changes for different reasons (accidental duplication).
- Abstraction discipline: extract the same knowledge (a business decision, a discriminating rule) at its second occurrence into its domain module; let a formatting/conversion helper that would become a cross-module shared util wait for the Rule of Three / AHA (Avoid Hasty Abstractions), because a wrong coupling costs more than a little duplication; keep a one-call-site helper when it is a single defence point (encapsulating an unsafe cast, or a drift guard); same-module step helpers are never "over-abstraction"; in doubt, keep it local.
- Requested scope only: add only the structure the task asked for, and ask before introducing a class variable, helper or layer that did not exist.
- YAGNI: build only what is needed now; add defensive logic (a cancel-confirmation modal) only with a PRD/design basis or to prevent irreversible user loss; pre-extracting shared code for a planned later PR is a planned split, not a YAGNI violation.
- KISS: the simplest thing that works; remove accidental complexity before adding structure.
- Extension by addition (OCP): when the same branch keeps being edited for each new case, introduce a strategy, polymorphism or port so the next case is added code, not modified code.
- Tracer bullet / vertical slice: deliver one thin end-to-end slice (entrypoint → use case → repository → storage → test) first and widen from there, one slice at a time.
- Two hats: one change either restructures (behaviour unchanged, tests untouched) or changes behaviour (tests change), never both in one commit.
- Make the change easy, then make the easy change: when a feature is hard to add, first refactor under green until it is easy, then add it in its own commit.
