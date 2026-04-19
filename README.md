# mac-setup

새 맥 초기 셋업용 설정 모음. 레포를 clone하고 `install.sh`를 실행하면 zsh·Homebrew·Claude Code·Codex CLI 설정이 한 번에 구성된다.

## 레포 내용물

```
mac-setup/
├── install.sh            # 자동 셋업 스크립트 (symlink 기반)
├── claude/               # ~/.claude/ 로 symlink 대상
│   ├── CLAUDE.md
│   ├── coding-rules*.md
│   ├── settings.json     # MCP 권한, hook, 플러그인 목록
│   ├── statusline-command.sh
│   ├── skills/           # dev-plan, plan-review, review, cso, guard, hygiene, investigate,
│   │                     # explain-html, pr-size-check, retro, session-review, unfreeze
│   └── commands/sc/      # SuperClaude 명령
├── codex/                # ~/.codex/ 로 symlink 대상
│   ├── AGENTS.md
│   ├── config.toml
│   ├── hooks.json
│   ├── rules/default.rules
│   └── skills/           # cso, dev-plan, guard, hygiene, plan-review, review, session-review
└── mac/
    ├── zshrc             # oh-my-zsh + 플러그인 + alias + PATH
    ├── zprofile          # brew shellenv
    ├── Brewfile          # brew bundle dump 결과
    └── setup-notes.md    # 자동화 안 되는 수동 단계
```

## 새 맥에서 사용법

```bash
# 1. clone
git clone git@github.com:park-j3onghoon/mac-setup.git ~/git/mac-setup

# 2. 셋업 스크립트 실행
cd ~/git/mac-setup
bash install.sh

# 3. 새 터미널 열거나
source ~/.zshrc

# 4. 로그인
claude login
codex login

# 5. 수동 단계는 mac/setup-notes.md 확인
```

## 설치 방식: symlink

레포 파일이 `~/.claude/CLAUDE.md`, `~/.zshrc` 등으로 symlink 됩니다. 실 파일을 에디팅하면 레포가 자동으로 바뀌므로 git으로 변경 추적이 바로 됩니다. 로그·캐시(`~/.claude/sessions/`, `~/.codex/history.jsonl` 등)는 `~/.claude`·`~/.codex` 내에 실물 디렉토리로 남아 레포에는 섞이지 않습니다.

## 반영 범위

**포함**: 언어·프로젝트와 무관한 **범용 개발 환경** — 코딩 룰, 스킬(리뷰/계획/디버깅/보안), CLI 설정, zsh + Homebrew.

**제외**:
- 시크릿(Linear API key, Redash config, 인증 토큰)
- 회사/업무 특화 스킬(옵시디언·Linear 통합용 `save-document`·`daily-todo`)
- 프로젝트별 메모리, 세션 로그, 히스토리, 캐시
- 사용자 특정 프로젝트 경로(예: `~/.codex/config.toml`의 `[projects.*]` 엔트리)

## 업데이트 흐름

설정을 바꾸면:

```bash
cd ~/git/mac-setup
git status               # symlink 경유로 수정된 변경사항이 보임
git add ... && git commit -m "설명"
git push
```

새 맥에서는 `git pull`만 하면 symlink가 자동으로 최신 설정을 가리킨다.
