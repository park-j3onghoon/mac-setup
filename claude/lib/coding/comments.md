# Comments and docstrings

- Why, not what: write a comment only for context the code cannot show.
- Keep:
  - external standard references (AIP-XXX, RFC NNNN, company RFC links)
  - security rationale (enumeration prevention, capability token, XSS vector blocking)
  - architecture decision + the alternatives rejected after review
  - non-obvious algorithm tricks (limit+1 hasNext, microsecond-precision cursor, base64url format)
  - disambiguation between confusable code/types ("vs" comparison)
  - hidden constraints/invariants (DB column type alignment such as `MAX_*=65535  # MySQL unsigned smallint 최대`, external API nullability assumption), external-system contracts, circular-import avoidance (a `TYPE_CHECKING` import for an annotation-only cycle)
  - a value format the type cannot show, with one example value: in the parser that turns the raw string into a structured type (`# "이름=id,id", 예: "alice=10,11"`), or at the field when no code parses the value (an external id stored and passed on)
- Delete:
  - a description the name or signature already gives (`"X 토큰을 생성한다"` over `fun generate(): String`); "X용 VO/DTO" labels on data classes
  - change history ("이전에는 Map이었으나...") → git log/PR body
  - comments about other code: caller info ("X 화면이 이걸 쓴다"), a description of another function's behaviour away from its own code
  - standard pattern/control-flow narration the structure already shows: `# compare-and-set 으로 중복 claim 방지`, `# try/except 로 한 항목 실패 격리`, `# 예외 시 좀비 방지 FAILED 마감`, `# 전부 SENT면 성공 아니면 실패`, `# 도메인 status → 모델 status 변환`
  - multi-line design essays ("why safe / why this design") → PR body or plan, keeping only the line the code cannot show (the UNIQUE constraint is owned by `send_email`)
  - references to deleted migrations (`시드 migration 0108`), fail-fast notes, roadmap/follow-up notes
- Docstrings follow the same Keep and Delete lists: delete one that restates the name (`mark_in_progress` → "Start (or restart) this run", `approve` → "Approve payout"); test docstrings follow `~/.claude/lib/coding/tests.md`.
- Language: write comments and docstrings in Korean.

## proto

- Comment scope: write only shape and signatures in proto files; put contract, validation and rationale in server code, the PR body and Linear. Comment a structure that looks like a mistake (an intentionally empty `Foo {}`) until a field arrives, and name in a comment the organization that currently fills a role-neutral field (`string manager_name = 6;  // 담당 BD`).
