#!/usr/bin/env bash
# 설치·포인터·frontmatter 검사. 사용: bash scripts/verify.sh  (문제가 있으면 exit 1)

set -uo pipefail
fail=0
note() { echo "  $*"; }

echo "== 1. 깨진 심링크"
for d in "$HOME/.claude" "$HOME/.claude/skills" "$HOME/.codex" "$HOME/.codex/skills" "$HOME/.claude/lib"; do
  [ -d "$d" ] || continue
  while IFS= read -r l; do
    note "DANGLING $l -> $(readlink "$l")"; fail=1
  done < <(find "$d" -maxdepth 1 -type l ! -exec test -e {} \; -print 2>/dev/null)
done
[ "$fail" -eq 0 ] && note "없음"

echo "== 2. SKILL.md frontmatter"
while IFS= read -r f; do
  head=$(awk 'NR>1 && /^---/{exit} NR>1{print}' "$f")
  grep -q '^name:' <<<"$head"        || { note "name 없음: $f"; fail=1; }
  grep -q '^description:' <<<"$head" || { note "description 없음: $f"; fail=1; }
  grep -q '^disable-model-invocation: true' <<<"$head" || { note "disable-model-invocation 없음: $f"; fail=1; }
  grep -q '^version:' <<<"$head"     && { note "version 잔존: $f"; fail=1; }
  grep -q '^context:' <<<"$head"     && { note "context 잔존: $f"; fail=1; }
done < <(find "$HOME/git/mac-setup/claude/skills" "$HOME/.claude/skills" "$HOME/example/.claude/skills" -maxdepth 2 -name SKILL.md 2>/dev/null)

echo "== 3. 포인터 경로 해소 (백틱 안의 ~/ · /Users 경로)"
missing=0
while IFS= read -r f; do
  while IFS= read -r p; do
    case "$p" in *'{'*|*'*'*|*'<'*|*' '*|*'…'*|*'|'*) continue;; esac
    exp="${p/#\~/$HOME}"
    [ -e "$exp" ] || { note "MISSING $exp  ($f)"; missing=$((missing+1)); fail=1; }
  done < <(grep -oE '`(~/|/Users/teddy\.park/)[^`]*`' "$f" | tr -d '`' | sort -u)
done < <(find "$HOME/git/mac-setup/claude" "$HOME/.claude/skills" "$HOME/example/.claude" -name '*.md' 2>/dev/null | grep -vE '/plans/|/commands/')
[ "$missing" -eq 0 ] && note "모두 존재"

echo "== 4. JSON 유효성"
for j in "$HOME/git/mac-setup/claude/settings.json" "$HOME/git/mac-setup/codex/hooks.json"; do
  jq -e . "$j" >/dev/null 2>&1 && note "OK $j" || { note "INVALID $j"; fail=1; }
done

echo "== 5. 훅 존재"
jq -e '.hooks.PreToolUse[] | select(.matcher=="Bash")' "$HOME/git/mac-setup/claude/settings.json" >/dev/null 2>&1 \
  && note "push/PR 훅 있음" || { note "push/PR 훅 없음"; fail=1; }
jq -e '.hooks.PreToolUse[] | select(.matcher=="ExitPlanMode")' "$HOME/git/mac-setup/claude/settings.json" >/dev/null 2>&1 \
  && note "plan 훅 있음" || { note "plan 훅 없음"; fail=1; }

echo "== 6. 항상 로드되는 파일 크기"
for f in "$HOME/.claude/CLAUDE.md" "$HOME/example/CLAUDE.md"; do
  [ -e "$f" ] && note "$(wc -c <"$f" | tr -d ' ') bytes  $f"
done

[ "$fail" -eq 0 ] && { echo "PASS"; exit 0; }
echo "FAIL"; exit 1
