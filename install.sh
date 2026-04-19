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

log "Shell dotfile symlink"
link_file "$REPO_DIR/mac/zshrc"    "$HOME/.zshrc"
link_file "$REPO_DIR/mac/zprofile" "$HOME/.zprofile"

# ---- 4. Claude 설정 ----
log "~/.claude/ 설정 symlink"
mkdir -p "$HOME/.claude/skills" "$HOME/.claude/commands"

for f in CLAUDE.md coding-rules.md coding-rules-python.md coding-rules-vue.md coding-rules-frontend.md settings.json statusline-command.sh; do
  link_file "$REPO_DIR/claude/$f" "$HOME/.claude/$f"
done

for skill_dir in "$REPO_DIR/claude/skills"/*/; do
  skill_name="$(basename "$skill_dir")"
  link_file "$REPO_DIR/claude/skills/$skill_name" "$HOME/.claude/skills/$skill_name"
done

for cmd_dir in "$REPO_DIR/claude/commands"/*/; do
  cmd_name="$(basename "$cmd_dir")"
  link_file "$REPO_DIR/claude/commands/$cmd_name" "$HOME/.claude/commands/$cmd_name"
done

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

# ---- 6. 마무리 안내 ----
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
