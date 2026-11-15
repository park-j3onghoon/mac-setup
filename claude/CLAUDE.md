`~/.claude/` 아래 파일은 컨텍스트에 없을 때만 Read한다. 세션 중에 바뀐 파일은 다시 Read한다.

Codex에서는 작업 전에 `~/.claude/lib/codex.md`와 이 파일의 `@` 줄이 가리키는 파일을 Read하고 따른다.

@~/.claude/lib/work-style.md
@~/.claude/lib/answer-style.md
@~/.claude/instructions/company.md
