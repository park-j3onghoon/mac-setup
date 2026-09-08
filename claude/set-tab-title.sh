#!/usr/bin/env bash
# 터미널 탭 제목과 Claude Code 세션 이름을 같은 값으로 설정한다
# (Claude Code·Codex 의 Bash 도구에서 호출).
#
# 탭 제목 — cmux 안에서는 `cmux rename-tab` 을 쓴다. OSC 2 로 건 제목은 셸 통합이나
# 실행 중인 프로그램이 덮어쓸 수 있지만 cmux 커스텀 제목은 유지된다.
# CMUX_TAB_ID 는 값이 워크스페이스 ID 와 같아 `--tab` 기본값으로 쓰면 not_found 가
# 나므로 CMUX_SURFACE_ID 로 타겟팅한다.
#
# 탭 제목 (cmux 밖) — 왜 PTY 에 직접 쓰나: Bash 도구는 stdout 을 파이프로 캡처하므로
# (`tty` 가 "not a tty") stdout 으로 보낸 OSC 시퀀스는 터미널에 닿지 않는다. 그래서
# 부모 프로세스 체인을 거슬러 올라가 실제 PTY 를 가진 첫 조상(Ghostty 가 붙어 있는
# 셸/CLI)을 찾아 그 장치에 쓴다. 탭 번호(ttys###)는 세션마다 달라져 하드코딩 불가.
#
# 세션 이름 — Claude Code 의 /rename 은 인터랙티브(local-jsx) 명령이라 에이전트가
# 호출할 수 없다. 대신 /rename 이 남기는 것과 동일한 custom-title 엔트리를
# 트랜스크립트에 직접 append 한다. 실행 중인 세션의 프롬프트 박스에도 즉시 반영된다.
#
# 사용법: set-tab-title.sh "1698 review"
set -uo pipefail

title="${1:?usage: set-tab-title.sh <title>}"
rc=0

set_title_via_osc() {
  local p=$PPID device="" t
  for _ in 1 2 3 4 5 6; do
    { [ -z "$p" ] || [ "$p" = 0 ] || [ "$p" = 1 ]; } && break
    t=$(ps -o tty= -p "$p" | tr -d ' ')
    case "$t" in
      ttys*) device="/dev/$t"; break ;;
    esac
    p=$(ps -o ppid= -p "$p" | tr -d ' ')
  done
  [ -n "$device" ] || return 1
  printf '\033]2;%s\007' "$title" > "$device"
}

if [ -n "${CMUX_SURFACE_ID:-}" ] && command -v cmux >/dev/null 2>&1 \
   && cmux rename-tab --surface "$CMUX_SURFACE_ID" "$title" >/dev/null 2>&1; then
  :
elif ! set_title_via_osc; then
  echo "set-tab-title: 탭 제목 설정 실패 (PTY 를 가진 조상 프로세스를 못 찾음)" >&2
  rc=1
fi

if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  transcript=""
  for f in "$HOME"/.claude/projects/*/"$CLAUDE_CODE_SESSION_ID".jsonl; do
    [ -f "$f" ] && { transcript="$f"; break; }
  done

  if [ -n "$transcript" ]; then
    TITLE="$title" SID="$CLAUDE_CODE_SESSION_ID" TRANSCRIPT="$transcript" python3 - <<'PY' || rc=1
import json, os

entry = {
    "type": "custom-title",
    "customTitle": os.environ["TITLE"],
    "sessionId": os.environ["SID"],
}
with open(os.environ["TRANSCRIPT"], "a") as f:
    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
PY
  else
    echo "set-tab-title: 세션 트랜스크립트를 못 찾음 ($CLAUDE_CODE_SESSION_ID)" >&2
    rc=1
  fi
fi

exit $rc
