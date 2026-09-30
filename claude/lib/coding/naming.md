# Naming

- Ubiquitous language: use the term the codebase or glossary already uses, one word per concept and one concept per word, the same term in identifiers, comments, docstrings and API fields.
- Domain terms stay untranslated: in Korean comments and docstrings, write a concept the code names as its identifier (`unit_contract`, `target_amount`, `adjustment` 생성).
- Identifiers are English.
- Functions and methods start with a verb naming the business action (`send_payout_email`, `approve`); a property or computed attribute may be a noun (`total_amount`). Keep mechanism words (async, thread, batch, cron, retry, worker) out of the name: `send_payout_email` over `run_email_batch`.
- Positive predicates: `can_*`/`is_*`/`has_*` (entity `can_retrigger()`); when negation is needed, keep the predicate positive and negate at the call-site guard (`if not …: continue`).
- Booleans: when reading one, name the axis it answers and read `False` as the opposite pole of that axis.
- Intention-revealing, searchable names: `remaining_budget`; name a constant when its value means something, in place of a magic number, and keep a bare value such as zero inline; use single letters only in lambdas and comprehensions.
- Model field names follow the DB column names; name every enum column `{enum_type}_type`.
- Enum naming: model enum without suffix (`DisplayCampaignStatus`) vs domain enum with a `Type` suffix (`DisplayCampaignStatusType`).

## Python

- Intention-revealing, searchable names: `Decimal('0')` is a bare value.
