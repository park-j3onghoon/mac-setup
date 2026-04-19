#!/bin/sh
# Claude Code statusLine 스크립트 - robbyrussell Oh My Zsh 테마 기반

input=$(cat)

cwd=$(echo "$input" | jq -r '.cwd')
dir=$(basename "$cwd")

# ANSI 색상 코드 (터미널 dim 모드에서도 구분 가능)
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
BLUE='\033[1;34m'
RESET='\033[0m'

# git 브랜치 정보 (선택적 잠금 스킵)
git_branch=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" symbolic-ref --short HEAD 2>/dev/null)

if [ -n "$git_branch" ]; then
  # git 상태 확인 (수정된 파일 여부)
  git_dirty=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" status --porcelain 2>/dev/null | head -1)
  if [ -n "$git_dirty" ]; then
    git_info=" ${BLUE}git:(${RED}${git_branch}${BLUE}) ${YELLOW}✗${RESET}"
  else
    git_info=" ${BLUE}git:(${RED}${git_branch}${BLUE})${RESET}"
  fi
else
  git_info=""
fi

printf "${CYAN}%s${RESET}%s\n" "$dir" "$git_info"
