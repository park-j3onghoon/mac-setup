# Naming

- Ubiquitous language: use the term the codebase or glossary already uses, one word per concept.
- Functions and methods start with a verb naming the business action (`send_payout_email`, `approve`); a property or computed attribute may be a noun (`total_amount`). Mechanism words (async, thread, batch, cron, retry, worker) stay out of the name: `send_payout_email` over `run_email_batch`.
- Positive predicates: `can_*`/`is_*`/`has_*` (entity `can_retrigger()`); when negation is needed, keep the predicate positive and negate at the call-site guard (`if not …: continue`).
- Intention-revealing, searchable names: `remaining_budget`, a named constant instead of a magic number, single letters only in lambdas and comprehensions.
- Model field = DB column, so a debugging query maps 1:1.
- Enum naming: model enum without suffix (`DisplayCampaignStatus`) vs domain enum with a `Type` suffix (`DisplayCampaignStatusType`); infrastructure converts by value (`ModelEnum(domain_enum.value)`).
