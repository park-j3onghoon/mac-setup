For Python code, also Read `~/.claude/lib/coding/naming-python.md`.

- Ubiquitous language: use the term the codebase or glossary already uses, one word per concept and one concept per word, the same term in identifiers, comments, docstrings and API fields.
- Shared words: when the domain uses one word for several concepts in the same module or package, every name built on it carries the context that tells them apart; prefix a constant that sits in the package namespace with its type name (`ItemTypeDirect` beside `SourceDirect`), and check a name copied from another package against the names already in the new one.
- Code terms stay untranslated: in Korean comments and docstrings, write a concept the code names (an identifier, a language keyword, a library or test API) as the code writes it (`contract`, `due_amount`, `adjustment` 생성, `assert` instead of 단언).
- Identifiers are English.
- Functions and methods start with a verb naming the business action (`send_payout_email`, `approve`); a property or computed attribute may be a noun (`total_amount`). Keep mechanism words (async, thread, batch, cron, retry, worker) out of the name.
- Method-bound types: a request, response, result or options type that belongs to one method takes the method's name with its verb (`CalculateShipping` → `CalculateShippingRequest`, `CalculateShippingResult`), and every method-bound type in the module uses the same form.
- Time zone in names: a function or field that returns a time in a fixed zone names the zone (`created_at_utc`, `to_seoul_date`).
- Messages: name a command in the imperative mood (`IssueContract`) and a domain event in the past tense (`ContractIssued`).
- Positive predicates: `can_*`/`is_*`/`has_*` (entity `can_retrigger()`); when negation is needed, keep the predicate positive and negate at the call-site guard (`if not …: continue`).
- Booleans: when reading one, name the axis it answers and read false as the opposite pole of that axis.
- Intention-revealing, searchable names: `remaining_copies`; name a constant when its value means something, in place of a magic number, and keep a bare value such as zero inline; use single letters only in lambdas and comprehensions.
- Value-shape names: make it clear whether an object represents a value, collection, summary or history; use temporal modifiers when they distinguish a meaningful concept, not merely the object's role in the current call.
