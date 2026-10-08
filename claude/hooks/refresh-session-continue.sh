#!/bin/bash
# SessionStart(matcher: clear) 훅. /refresh-session이 남긴 표시 파일이 있으면 그 프롬프트를 이 cmux 탭에 입력한다.
# 표시 파일은 탭마다 하나(~/.claude/state/refresh-session/<CMUX_SURFACE_ID>)이고, 10분이 지난 것은 입력하지 않고 지운다.
# 훅이 도는 동안 입력된 프롬프트는 훅이 끝난 뒤 제출된다.
cat >/dev/null
[ -n "${CMUX_SURFACE_ID:-}" ] || exit 0
marker="$HOME/.claude/state/refresh-session/$CMUX_SURFACE_ID"
[ -f "$marker" ] || exit 0
if [ -n "$(find "$marker" -mmin +10)" ]; then
  rm -f "$marker"
  exit 0
fi
prompt=$(cat "$marker")
rm -f "$marker"
[ -n "$prompt" ] || exit 0
cmux send --surface "$CMUX_SURFACE_ID" -- "$prompt" >/dev/null && cmux send-key --surface "$CMUX_SURFACE_ID" enter >/dev/null
