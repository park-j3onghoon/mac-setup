# Change discipline

- Ideal first: propose the ideal DDD / Clean Architecture / layered / CQS / Simple Design structure first, compare candidates when several are ideal, state scope/legacy/schedule compromises separately afterwards, and give the grounds whenever you call a design excessive or complex; check every model design for dependency direction and stored-vs-computed state.
- Existing patterns first: before proposing a change, grep sibling modules for the pattern (`grep -r "<pattern>" <app>/`: an id field's default and lower bound, `VALID_TRANSITIONS` public/private, `Error` vs `Exception` naming); when the existing pattern differs from the ideal, show both and let the user decide.
- Pattern-switch questions: frame them as "currently A, a sibling module does B. Switch or keep?".
- Review-agent suggestions: grep the module and its siblings first and route new defensive code (asserts, a duplicate `updated_count` check, a manually set `updated_at`) to ASK.
- Verify file state with `git diff --name-only` / `ls` / `git status` before saying a file exists, changed or was deleted; branch switches and merges change the state.
- Build after moves: after `git mv` or an import-path change, check the moved file's relative imports, prefer absolute imports, and run the project's build, because passing tests do not prove a passing build.
