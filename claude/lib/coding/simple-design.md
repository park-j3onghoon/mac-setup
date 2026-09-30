# Simple Design and refactoring

- Four rules: when design choices conflict, prefer in this order: tests pass, intention shows, no duplication, fewest elements.
- DRY of knowledge: give every fact or decision one source of truth: when the same knowledge (a business decision, a discriminating rule) appears a second time, extract it into its domain module; keep code that only looks alike and changes for different reasons as separate copies.
- Abstraction discipline: when a formatting/conversion helper would become a cross-module shared util, wait for the Rule of Three; keep a one-call-site helper that is a single defence point (encapsulating an unsafe cast, a drift guard); split into same-module step helpers freely; in doubt, keep it local.
- YAGNI: build only what the task asks for now, and ask before introducing a class variable, helper or layer that did not exist; add defensive logic (a cancel-confirmation modal) only with a PRD/design basis or to prevent irreversible user loss; extracting shared code early for a planned later PR is allowed.
- KISS: choose the simplest thing that works, and remove accidental complexity before adding structure.
- Extension by addition: when the same branch keeps being edited for each new case, introduce a strategy, polymorphism or port and add the next case as new code; share behaviour through a collaborator or strategy object, and keep use cases free of a shared base class.
- Tracer bullet / vertical slice: deliver one thin end-to-end slice (entrypoint → use case → repository → storage → test) first and widen from there, one slice at a time.
- Two hats: put restructuring (behaviour unchanged, tests untouched) and behaviour changes (tests change) in separate commits; when a feature is hard to add, first restructure under green until it is easy, then add the feature in its own commit.
