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
│   ├── skills/           # plan-review, review, cso, guard, hygiene, investigate,
│   │                     # explain-html, retro, session-review
│   ├── lib/              # 스킬이 포인터로 읽는 하위 공용 모듈 (review 브리프, codex 교차검증)
│   └── commands/sc/      # SuperClaude 명령(미사용이라 install.sh가 링크하지 않는다)
├── scripts/              # 설정 검사 (check-layers · verify · check-pair)
├── example/              # 회사 전용 설정 (gitignore, 클론에 포함되지 않음)
├── codex/                # ~/.codex/ 로 symlink 대상
│   ├── AGENTS.md
│   ├── config.toml
│   ├── hooks.json
│   ├── rules/default.rules
│   └── skills/           # cso, guard, hygiene, plan-review, review, session-review
├── vscode/               # ~/Library/Application Support/Code/User/ 로 symlink 대상
│   ├── settings.json     # PyCharm 스타일, JDK 21, Kotlin/TS/Python 포매터, 파일 중첩 등
│   └── keybindings.json  # PyCharm 단축키 (Cmd+B 토글, Cmd+1/2/4 패널 토글, Cmd+Esc 등)
└── mac/
    ├── zshrc             # oh-my-zsh + 플러그인 + alias + PATH
    ├── zprofile          # brew shellenv
    ├── Brewfile          # brew bundle (앱 + VSCode 확장 포함)
    └── setup-notes.md    # 자동화 안 되는 수동 단계
```

## 스킬

전부 사용자 호출이다. `/이름`으로 실행한다. 회사 전용 스킬 6개는 git이 추적하지 않는 `example/` 트리에 있어 이 목록에 없다.

### engineering

| 스킬 | 하는 일 |
|---|---|
| [`/cso`](claude/skills/engineering/cso/SKILL.md) | Read-only 보안 감사. 시크릿·공급망·CI/CD·OWASP·STRIDE를 훑어 exploitable한 발견만 보고서로 낸다. |
| [`/grill`](claude/skills/engineering/grill/SKILL.md) | 결정을 끝까지 캐묻는다. 사실은 내가 찾고, 갈림길만 라운드로 묶어 묻고, 합의된 결정을 decisions.md로 남긴다. |
| [`/guard`](claude/skills/engineering/guard/SKILL.md) | 이번 세션에 안전 모드를 건다. 위험 명령 경고 + 지정 디렉토리 밖 편집 확인. `off` 로 편집 제한을 푼다. |
| [`/implement`](claude/skills/engineering/implement/SKILL.md) | 확정된 계획을 vertical slice 단위로 구현한다. 안전 모드를 걸고, 코드 규칙을 적재하고, 슬라이스마다 테스트를 green으로 만든다. |
| [`/investigate`](claude/skills/engineering/investigate/SKILL.md) | 버그를 근본 원인까지 추적해 고치고 DEBUG REPORT로 마감한다. |
| [`/plan-review`](claude/skills/engineering/plan-review/SKILL.md) | 구현 계획을 코드 작성 전에 스코프 챌린지·6차원 리뷰·Codex 적대 검증으로 통과시킨다. |
| [`/review`](claude/skills/engineering/review/SKILL.md) | 브랜치 변경을 서브에이전트 3개로 병렬 리뷰하고, 수정을 적용한 뒤 PR 크기 검사와 push 안내까지 끝낸다. |

### productivity

| 스킬 | 하는 일 |
|---|---|
| [`/explain-html`](claude/skills/productivity/explain-html/SKILL.md) | 주제를 조사해 인라인 SVG 도식이 들어간 단일 파일 HTML 해설서를 만들고, ~/plans에 저장한 뒤 브라우저로 연다. |
| [`/skill-review`](claude/skills/productivity/skill-review/SKILL.md) | 스킬이 구조 규약과 문서 기준을 지키는지 점검하고, 어긋난 곳을 고칠 안을 낸다. |

### 공용 하위 모듈

스킬이 포인터로 읽는 파일이다. 직접 호출하지 않는다.

| 모듈 | 내용 |
|---|---|
| [`lib/answer-style.md`](claude/lib/answer-style.md) | 답변·문서 작성 규칙 |
| [`lib/guard.md`](claude/lib/guard.md) | 위험 명령 경고·디렉토리 편집 제한 |
| [`lib/explain-html.md`](claude/lib/explain-html.md) | HTML 해설서 작성 규칙 |
| [`lib/codex-adversarial.md`](claude/lib/codex-adversarial.md) | Codex 교차 검증 실행·회수 |
| [`lib/review/`](claude/lib/review/) | 코드 리뷰 기준 3종(공통·언어별·팀 리뷰어) |

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

**포함**: 언어·프로젝트와 무관한 **범용 개발 환경**: 코딩 룰, 스킬(리뷰/계획/디버깅/보안), CLI 설정, zsh + Homebrew, VSCode 글로벌 설정/키바인딩/확장.

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
