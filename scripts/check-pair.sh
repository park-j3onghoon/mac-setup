#!/usr/bin/env bash
# CLAUDE.md ↔ AGENTS.md 페어의 섹션 구성이 같은지 본다(도구별 문장 차이는 허용).
# 사용: bash scripts/check-pair.sh

set -uo pipefail
fail=0

check() {
  local a="$1" b="$2"
  if [ ! -e "$a" ] || [ ! -e "$b" ]; then
    echo "SKIP $a ↔ $b (없음)"; return
  fi
  local d
  d=$(diff <(grep -E '^#{1,3} ' "$a") <(grep -E '^#{1,3} ' "$b"))
  if [ -n "$d" ]; then
    echo "DRIFT $a ↔ $b"; echo "$d" | sed 's/^/    /'; fail=1
  else
    local la lb
    la=$(wc -l <"$a" | tr -d ' '); lb=$(wc -l <"$b" | tr -d ' ')
    echo "OK $(basename "$(dirname "$a")")  섹션 일치 (${la}줄 / ${lb}줄)"
  fi
}

check "$HOME/.claude/CLAUDE.md" "$HOME/.codex/AGENTS.md"
check "$HOME/example/CLAUDE.md" "$HOME/example/AGENTS.md"
check "$HOME/example_analysis/CLAUDE.md" "$HOME/example_analysis/AGENTS.md"

[ "$fail" -eq 0 ] && { echo "PASS"; exit 0; }
echo "FAIL"; exit 1
