#!/usr/bin/env bash
# 새 맥 셋업 스크립트
# 실행 방법: bash install.sh
#
# 하는 일:
#   1. Homebrew 및 Brewfile 내 패키지 설치
#   2. Oh My Zsh + zsh 플러그인 설치
#   3. ~/.zshrc, ~/.zprofile symlink
#   4. ~/.claude/ 및 ~/.codex/ 설정 파일 symlink
#   5. 후속 수동 단계 안내
#
# 특징: 멱등성 보장 (여러 번 실행해도 같은 결과).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 색상 출력용
C_GREEN='\033[0;32m'
C_YELLOW='\033[1;33m'
C_BLUE='\033[0;34m'
C_RESET='\033[0m'
log()  { printf "${C_BLUE}[install]${C_RESET} %s\n" "$*"; }
ok()   { printf "${C_GREEN}[ok]${C_RESET} %s\n" "$*"; }
warn() { printf "${C_YELLOW}[warn]${C_RESET} %s\n" "$*"; }

# ---- 1. Homebrew ----
log "Homebrew 설치 확인"
if ! command -v brew >/dev/null 2>&1; then
  log "Homebrew가 없어서 설치합니다"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
else
  ok "Homebrew 감지됨"
fi

# Brewfile 기반 패키지 설치
log "Brewfile 기반 패키지 설치 (시간이 걸립니다)"
brew bundle --file="$REPO_DIR/mac/Brewfile"
ok "Brewfile 완료"

# ---- 2. Oh My Zsh + zsh 플러그인 ----
log "Oh My Zsh 설치 확인"
if [ ! -d "$HOME/.oh-my-zsh" ]; then
  RUNZSH=no KEEP_ZSHRC=yes \
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
else
  ok "Oh My Zsh 감지됨"
fi

# zsh 플러그인은 Brewfile로 설치된다고 가정 (zsh-autosuggestions, zsh-syntax-highlighting).
# 없으면 brew로 설치
for pkg in zsh-autosuggestions zsh-syntax-highlighting zsh-completions; do
  if ! brew list --formula 2>/dev/null | grep -qx "$pkg"; then
    log "누락된 zsh 플러그인 설치: $pkg"
    brew install "$pkg"
  fi
done
ok "zsh 플러그인 준비"

# ---- 3. Shell dotfile symlink ----
link_file() {
  local src="$1"
  local dst="$2"
  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$src" ]; then
    return 0
  fi
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    warn "$dst 가 이미 실제 파일로 존재합니다. $dst.backup 으로 이동"
    mv "$dst" "$dst.backup"
  fi
  ln -sfn "$src" "$dst"
  ok "symlink: $dst -> $src"
}

# 대상이 사라진 심링크 제거 (레포에서 파일을 지우거나 롤백했을 때 자동 정리)
prune_dangling() {
  local dir
  for dir in "$@"; do
    [ -d "$dir" ] || continue
    find "$dir" -maxdepth 1 -type l ! -exec test -e {} \; -print 2>/dev/null | while read -r l; do
      rm -f "$l"
      warn "dangling 제거: $l"
    done
  done
}

log "Shell dotfile symlink"
link_file "$REPO_DIR/mac/zshrc"    "$HOME/.zshrc"
link_file "$REPO_DIR/mac/zprofile" "$HOME/.zprofile"

# ---- 4. Claude 설정 ----
log "~/.claude/ 설정 symlink"
mkdir -p "$HOME/.claude/skills" "$HOME/.claude/lib"

# 규칙 문서·설정·스크립트: 레포에 있는 것을 전부 링크 (파일 추가 시 install.sh 수정 불필요)
for f in "$REPO_DIR"/claude/*.md "$REPO_DIR"/claude/*.sh "$REPO_DIR"/claude/settings.json; do
  [ -e "$f" ] || continue
  link_file "$f" "$HOME/.claude/$(basename "$f")"
done

# 스킬은 레포에서 버킷(engineering/ productivity/)으로 정리하고, 하네스가 찾는
# ~/.claude/skills 에는 평평하게 링크한다(하네스는 한 단계만 탐색한다).
for bucket in "$REPO_DIR/claude/skills"/*/; do
  for skill_dir in "$bucket"*/; do
    [ -d "$skill_dir" ] || continue
    skill_name="$(basename "$skill_dir")"
    link_file "${skill_dir%/}" "$HOME/.claude/skills/$skill_name"
  done
done

# 하위 공용 모듈 (스킬이 포인터로 읽는 파일들)
for lib_entry in "$REPO_DIR/claude/lib"/*; do
  [ -e "$lib_entry" ] || continue
  link_file "$lib_entry" "$HOME/.claude/lib/$(basename "$lib_entry")"
done

mkdir -p "$HOME/.claude/hooks"
for hook in "$REPO_DIR/claude/hooks"/*; do
  [ -e "$hook" ] || continue
  link_file "$hook" "$HOME/.claude/hooks/$(basename "$hook")"
done

prune_dangling "$HOME/.claude" "$HOME/.claude/skills" "$HOME/.claude/lib" "$HOME/.claude/hooks"

# ---- 4b. 회사 전용 설정 (git 미추적, 있을 때만) ----
# 전부 유저 레벨(~/.claude)로만 배포한다. 프로젝트 레벨 .claude 는 쓰지 않는다.
if [ -d "$REPO_DIR/example" ]; then
  log "회사 전용 설정 symlink"
  for f in "$REPO_DIR"/example/claude/*.md; do
    [ -e "$f" ] || continue
    link_file "$f" "$HOME/.claude/$(basename "$f")"
  done
  for skill_dir in "$REPO_DIR/example/claude/skills"/*/; do
    [ -d "$skill_dir" ] || continue
    link_file "${skill_dir%/}" "$HOME/.claude/skills/$(basename "${skill_dir%/}")"
  done
  for lib_entry in "$REPO_DIR/example/claude/lib"/*; do
    [ -e "$lib_entry" ] || continue
    link_file "$lib_entry" "$HOME/.claude/lib/$(basename "$lib_entry")"
  done
  for hook in "$REPO_DIR/example/claude/hooks"/*; do
    [ -e "$hook" ] || continue
    link_file "$hook" "$HOME/.claude/hooks/$(basename "$hook")"
  done
  link_file "$REPO_DIR/example/claude/instructions" "$HOME/.claude/instructions"
else
  warn "example/ 없음: 회사 전용 설정은 건너뜁니다 (새 맥이면 별도로 복사해야 합니다)"
fi

# ---- 5. Codex 설정 ----
log "~/.codex/ 설정 symlink"
mkdir -p "$HOME/.codex/skills" "$HOME/.codex/rules"

for f in AGENTS.md config.toml hooks.json; do
  link_file "$REPO_DIR/codex/$f" "$HOME/.codex/$f"
done

link_file "$REPO_DIR/codex/rules/default.rules" "$HOME/.codex/rules/default.rules"

for skill_dir in "$REPO_DIR/codex/skills"/*/; do
  skill_name="$(basename "$skill_dir")"
  link_file "$REPO_DIR/codex/skills/$skill_name" "$HOME/.codex/skills/$skill_name"
done

prune_dangling "$HOME/.codex" "$HOME/.codex/skills"

# ---- 6. VSCode 설정 ----
log "VSCode 설정 symlink"
VSCODE_USER_DIR="$HOME/Library/Application Support/Code/User"
if [ -d "/Applications/Visual Studio Code.app" ] || command -v code >/dev/null 2>&1; then
  mkdir -p "$VSCODE_USER_DIR"
  link_file "$REPO_DIR/vscode/settings.json"    "$VSCODE_USER_DIR/settings.json"
  link_file "$REPO_DIR/vscode/keybindings.json" "$VSCODE_USER_DIR/keybindings.json"
  ok "VSCode settings.json / keybindings.json symlink 완료"
  ok "확장은 Brewfile의 'vscode \"...\"' 라인으로 자동 설치됨"
else
  warn "VSCode가 아직 설치되지 않았습니다. Brewfile 설치 후 다시 실행하세요"
fi

# ---- 7. 마무리 안내 ----
cat <<'EOF'

========================================================
완료. 남은 수동 단계는 mac/setup-notes.md 를 확인하세요.

요약:
  - 새 터미널 열기 또는 `source ~/.zshrc` 실행
  - Claude Code / Codex CLI 로그인
      claude login
      codex login
  - 기본 설치 외 앱 (mac/setup-notes.md 참고):
      Scroll Reverser, Maccy, Karabiner-Elements,
      Rectangle, Obsidian, KakaoTalk
  - macOS 키보드 단축키 조정 (Command+Esc 등)
========================================================
EOF
