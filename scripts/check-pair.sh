#!/usr/bin/env bash
# Claude 진입 파일과 Codex 진입 파일이 같은 원본 하나를 가리키는지 본다.
# 사용: bash scripts/check-pair.sh

set -uo pipefail

real() { python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }

claude=$(real "$HOME/.claude/CLAUDE.md")
codex=$(real "$HOME/.codex/AGENTS.md")
if [ -f "$claude" ] && [ "$claude" = "$codex" ]; then
  echo "OK 같은 원본: $claude ($(wc -l <"$claude" | tr -d ' ')줄)"
  echo "PASS"; exit 0
fi
echo "DRIFT ~/.claude/CLAUDE.md -> $claude, ~/.codex/AGENTS.md -> $codex"
echo "FAIL"; exit 1
