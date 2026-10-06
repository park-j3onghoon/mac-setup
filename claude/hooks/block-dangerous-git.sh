#!/usr/bin/env bash
# PreToolUse(Bash): 되돌릴 수 없는 git 명령을 에이전트가 실행하지 못하게 막는다.
# 사용자는 프롬프트에 `! <명령>` 으로 직접 실행할 수 있다. 차단 대상은 ~/.claude/lib/guard.md 가 사용자 실행으로 정한 명령과 같다.

set -uo pipefail
CMD=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0
# 줄 끝 \ 로 이어 쓴 명령은 한 줄로 합쳐 본다.
CMD=${CMD//$'\\\n'/ }

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

# git 과 하위 명령 사이의 전역 옵션(-C <경로>, -c <키>=<값>, --git-dir=<경로>, --no-pager 등)을 건너뛴다.
ARG=$'("[^"]*"|\'[^\']*\'|[^[:space:]"\'|;&])+'
GIT='git([[:space:]]+(-[Cc]|--(git-dir|work-tree|namespace|config-env|attr-source))[[:space:]]+'"$ARG"'|[[:space:]]+-'"$ARG"')*[[:space:]]+'

# force push (--force, -f, --force-with-lease, +refspec)
if printf '%s' "$CMD" | grep -qE "$GIT"'push([[:space:]]+[^|;&]*)?([[:space:]]--force([[:space:]]|=|$)|[[:space:]]--force-with-lease|[[:space:]]-f([[:space:]]|$)|[[:space:]]\+[A-Za-z0-9._/-]+:)'; then
  deny "force push 는 실행하지 않습니다. 필요하면 명령과 절차를 안내할 테니 사용자가 '! <명령>' 으로 직접 실행하세요."
fi

# 커밋되지 않은 작업을 지우는 명령
if printf '%s' "$CMD" | grep -qE "$GIT"'reset[[:space:]]+([^|;&]*[[:space:]])?--hard'; then
  deny "git reset --hard 는 커밋 안 된 작업을 되돌릴 수 없게 지웁니다. 사용자가 '! <명령>' 으로 직접 실행하세요."
fi
if printf '%s' "$CMD" | grep -qE "$GIT"'clean[[:space:]]+[^|;&]*-[a-zA-Z]*f'; then
  deny "git clean -f 는 추적되지 않는 파일을 지웁니다. 지울 대상을 'git clean -n' 으로 먼저 보여드릴 테니, 실행은 사용자가 '! <명령>' 으로 하세요."
fi
if printf '%s' "$CMD" | grep -qE "$GIT"'(checkout|restore)[[:space:]]+\.([[:space:]]|$)'; then
  deny "git checkout . / git restore . 는 워킹트리 변경을 통째로 버립니다. 되살릴 파일을 먼저 확인하고, 실행은 사용자가 '! <명령>' 으로 하세요."
fi
if printf '%s' "$CMD" | grep -qE "$GIT"'branch[[:space:]]+[^|;&]*-D([[:space:]]|$)'; then
  deny "git branch -D 는 머지되지 않은 브랜치를 지웁니다. 사용자가 '! <명령>' 으로 직접 실행하세요."
fi

exit 0
