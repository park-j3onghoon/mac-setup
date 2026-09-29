# Comments and docstrings

- Why, not what: default to no comment, since identifiers and signatures carry the "what"; write one only for context the code cannot show.
- Keep:
  - external standard references (AIP-XXX, RFC NNNN, company RFC links)
  - security rationale (enumeration prevention, capability token, XSS vector blocking)
  - architecture decision + the alternatives rejected after review
  - non-obvious algorithm tricks (limit+1 hasNext, microsecond-precision cursor, base64url format)
  - disambiguation between confusable code/types ("vs" comparison)
  - hidden constraints/invariants (DB column type alignment, external API nullability assumption), external-system contracts, circular-import avoidance
  - value rationale only, e.g. `MAX_*=65535  # MySQL unsigned smallint 최대`
- Delete:
  - descriptions obvious from the signature; "X용 VO/DTO" labels on data classes
  - change history ("이전에는 Map이었으나...") → git log/PR body; caller info ("X 화면이 이걸 쓴다") → goes stale
  - an identifier paraphrased (`"X 토큰을 생성한다"` over `fun generate(): String`)
  - standard pattern/control-flow narration the structure already shows: `# compare-and-set 으로 중복 claim 방지`, `# try/except 로 한 항목 실패 격리`, `# 예외 시 좀비 방지 FAILED 마감`, `# 전부 SENT면 성공 아니면 실패`, `# 도메인 status → 모델 status 변환`
  - multi-line design essays ("why safe / why this design") → PR body or plan (a 4-line get_or_create justification shrinks to the one line the code cannot show: the UNIQUE constraint is owned by `send_email`); a description of another function's behaviour away from its own code
  - references to deleted migrations (`시드 migration 0108`), fail-fast notes, roadmap/follow-up notes
- Docstrings follow the same rule: delete one that restates the name (`mark_in_progress` → "Start (or restart) this run", `approve` → "Approve payout") and keep one only for why/context; test docstrings are the one exception (`~/.claude/lib/coding/tdd.md`).
- Language: write comments and docstrings in Korean, identifiers and test names in English.
