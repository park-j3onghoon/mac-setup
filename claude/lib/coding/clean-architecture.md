# Clean Architecture: layers and dependency direction

- Dependency rule: every dependency points inward: presentation → application → domain; infrastructure depends on the domain by implementing the ports the domain defines. The domain depends on nothing, infrastructure imports no application implementation, and the domain is designed first, independent of any repository signature.
- One-way dependencies: when A references B, B never knows A; a cycle nullifies the split.
- Layering: every request entrypoint (view, servicer, CLI, consumer) calls a use case that runs inside a unit of work and works on the domain model; adapters (repositories, gateways, email, publishers) implement the ports. A use case reaches the ORM or an HTTP client only through a port.
- Thin entrypoint: an entrypoint only builds the use case, maps request → payload, calls it, and maps result → response. List and retrieve get their own use cases too, so every entrypoint reaches repositories through a use case.
- Domain vs application placement: a rule true in every use case goes to the domain (`can_transition_to()`, where APPROVE → DRAFT is never allowed; an entity field constraint such as a 15-character title); a rule true in one flow goes to the application ("all fields required on submit" while a draft may be empty; "start date 2 business days ahead" on create/update). Split constants and exceptions the same way (`domain/constants` vs `application/constants`).
- One responsibility per use case: split a use case that validates ownership and also renders the notification email.
- Use cases call no other use case: they share only atomic validators (`validate_campaign_request_ownership`, `validate_status_transition`); a lookup repeated across use cases is inlined or given its own private helper.
- Composition over inheritance: share behaviour through a collaborator or strategy object, and keep use cases free of a shared base class.
