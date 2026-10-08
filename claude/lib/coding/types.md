For Python code, also Read `~/.claude/lib/coding/types-python.md`; for frontend code, `~/.claude/lib/coding/types-frontend.md`.

- Make illegal states unrepresentable: model a kind/state/mode argument as an enum even with two values (`kind: ExitKind`), and use a boolean only for an on/off flag (`verbose`); replace two booleans (`is_tp` + `is_sl`) with one enum; replace an optional field plus a same-root boolean (`take_profit` + `is_take_profit`) with one field; put fields that travel with a variant in a discriminated union; give a constrained value a constrained type.
