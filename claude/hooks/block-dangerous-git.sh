#!/usr/bin/env bash
# PreToolUse(Bash): 되돌릴 수 없는 git 명령을 에이전트가 실행하지 못하게 막는다.
# 사용자는 프롬프트에 `! <명령>` 으로 직접 실행할 수 있다. 차단 대상은 CLAUDE.md 안전 하드룰과 같다.

set -uo pipefail
CMD=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0

deny() {
  jq -cn --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# force push (--force, -f, --force-with-lease, +refspec)
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+push([[:space:]]+[^|;&]*)?([[:space:]]--force([[:space:]]|=|$)|[[:space:]]--force-with-lease|[[:space:]]-f([[:space:]]|$)|[[:space:]]\+[A-Za-z0-9._/-]+:)'; then
  deny "force push 는 실행하지 않습니다(CLAUDE.md 안전 하드룰). 필요하면 명령과 절차를 안내할 테니 사용자가 '! <명령>' 으로 직접 실행하세요."
fi

# 커밋되지 않은 작업을 지우는 명령
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+reset[[:space:]]+([^|;&]*[[:space:]])?--hard'; then
  deny "git reset --hard 는 커밋 안 된 작업을 되돌릴 수 없게 지웁니다. 사용자가 '! <명령>' 으로 직접 실행하세요."
fi
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+clean[[:space:]]+[^|;&]*-[a-zA-Z]*f'; then
  deny "git clean -f 는 추적되지 않는 파일을 지웁니다. 지울 대상을 'git clean -n' 으로 먼저 보여드릴 테니, 실행은 사용자가 '! <명령>' 으로 하세요."
fi
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+(checkout|restore)[[:space:]]+\.([[:space:]]|$)'; then
  deny "git checkout . / git restore . 는 워킹트리 변경을 통째로 버립니다. 되살릴 파일을 먼저 확인하고, 실행은 사용자가 '! <명령>' 으로 하세요."
fi
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+branch[[:space:]]+[^|;&]*-D([[:space:]]|$)'; then
  deny "git branch -D 는 머지되지 않은 브랜치를 지웁니다. 사용자가 '! <명령>' 으로 직접 실행하세요."
fi

exit 0
