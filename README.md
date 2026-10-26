# mac-setup

새 맥 초기 셋업용 설정 모음. 레포를 clone하고 `install.sh`를 실행하면 zsh·Homebrew·Claude Code·Codex CLI 설정이 한 번에 구성된다.

## 레포 내용물

```
mac-setup/
├── install.sh            # 자동 셋업 스크립트 (symlink 기반)
├── claude/               # ~/.claude/ 로 symlink 대상
│   ├── CLAUDE.md
│   ├── settings.json     # MCP 권한, hook, 플러그인 목록
│   ├── statusline-command.sh
│   ├── set-tab-title.sh  # 터미널 탭 제목과 세션 이름 설정
│   ├── hooks/            # PreToolUse 훅 (되돌릴 수 없는 git 명령 차단) · PostToolUse 훅 (함수·줄 길이 검사) · SessionStart 훅 (/refresh-session 다음 명령 입력)
│   ├── skills/           # engineering/ · productivity/ 버킷 (스킬 목록은 아래 표)
│   └── lib/              # 스킬이 포인터로 읽는 하위 공용 모듈 (코드 규칙, API 설계, 리뷰 기준·절차, 다른 AI 교차 검증)
├── scripts/              # 설정 검사 (check-layers · verify · check-pair)
├── private/              # 회사 전용 설정 (gitignore, 클론에 포함되지 않음)
├── codex/                # ~/.codex/ 로 symlink 대상
│   ├── AGENTS.md
│   ├── config.toml
│   ├── hooks.json
│   └── skills/           # .system만 추적(install.sh가 링크하지 않음). 공개·회사 스킬 전체는 같은 Claude 원본을 링크
├── vscode/               # ~/Library/Application Support/Code/User/ 로 symlink 대상
│   ├── settings.json     # PyCharm 스타일, JDK 21, Kotlin/TS/Python 포매터, 파일 중첩 등
│   ├── keybindings.json  # PyCharm 단축키 (Cmd+B 토글, Cmd+1/2/4 패널 토글, Cmd+Esc 등)
│   └── extensions/       # 로컬 확장 소스 (goto-declaration-or-usages: Cmd+B 정의 ↔ 사용처). 설치는 setup-notes.md
└── mac/
    ├── zshrc             # oh-my-zsh + 플러그인 + alias + PATH
    ├── zprofile          # brew shellenv
    ├── Brewfile          # brew bundle (앱 + VSCode 확장 포함)
    └── setup-notes.md    # 자동화 안 되는 수동 단계
```

## 스킬

Claude Code에서는 `/이름`, Codex에서는 `$이름`으로 실행한다. 공개·회사 스킬 전체가 같은 원본을 공유하며, 사용자 호출 전용인 스킬은 Codex에서도 같은 제한을 유지한다. 회사 전용 스킬은 git이 추적하지 않는 `private/` 트리에 있어 이 목록에 없다.

### engineering

| 스킬 | 하는 일 |
|---|---|
| [`/cso`](claude/skills/engineering/cso/SKILL.md) | Read-only 보안 감사. 시크릿·공급망·CI/CD·OWASP·STRIDE를 훑어 exploitable한 발견만 보고서로 낸다. |
| [`/grill`](claude/skills/engineering/grill/SKILL.md) | 결정을 끝까지 캐묻는다. 사실은 내가 찾고, 갈림길만 라운드로 묶어 묻고, 합의된 결정을 decisions.md로 남긴다. |
| [`/guard`](claude/skills/engineering/guard/SKILL.md) | 이번 세션에 안전 모드를 건다. 위험 명령 경고 + 지정 디렉토리 밖 편집 확인. `off` 로 편집 제한을 푼다. |
| [`/implement`](claude/skills/engineering/implement/SKILL.md) | 확정된 계획을 vertical slice 단위로 구현한다. 안전 모드와 코드 규칙을 적용하고, 슬라이스마다 테스트 통과 후 커밋하며, 끝에 simplify로 정리한 변경도 검증 후 별도 커밋한다. |
| [`/implement-review`](claude/skills/engineering/implement-review/SKILL.md) | 내 PR이나 구현 커밋을 같은 diff로 병렬 리뷰한다. 발견마다 고치거나 하나씩 물어 반영하고, 테스트 통과 후 수정분을 별도 커밋한다. |
| [`/investigate`](claude/skills/engineering/investigate/SKILL.md) | 버그를 근본 원인까지 추적해 고치고 DEBUG REPORT로 마감한다. |
| [`/plan-review`](claude/skills/engineering/plan-review/SKILL.md) | 구현 계획을 코드 작성 전에 스코프 챌린지·6차원 리뷰·다른 AI 교차 검증으로 통과시킨다. |
| [`/pr-create`](claude/skills/engineering/pr-create/SKILL.md) | push된 브랜치로 Draft PR을 만든다. 크기를 검사하고 제목·본문 초안을 승인받아 만든다. |
| [`/push-commit`](claude/skills/engineering/push-commit/SKILL.md) | 변경을 커밋하고 브랜치를 push한 뒤, PR이 있으면 제목·본문을 코드에 맞춘다. 사람 리뷰를 받기 전이면 Claude가 push하고, 받은 뒤면 사용자가 push한다. |

기본 흐름은 `/implement`(테스트·구현 커밋) → `/implement-review`(테스트·별도 수정 커밋) → `/push-commit` → `/pr-create`(Draft 생성과 크기 검사)다.

### productivity

| 스킬 | 하는 일 |
|---|---|
| [`/explain-html`](claude/skills/productivity/explain-html/SKILL.md) | 주제를 조사해 인라인 SVG 도식이 들어간 단일 파일 HTML 해설서를 만들고, ~/plans에 저장한 뒤 브라우저로 연다. |
| [`/refresh-session`](claude/skills/productivity/refresh-session/SKILL.md) | 다음 작업을 빈 컨텍스트에서 잇는다. Claude Code는 같은 탭의 대화를 비우거나 새 탭 명령을 만들고, Codex는 새 세션 명령과 이어갈 프롬프트를 만든다. |
| [`/skill-review`](claude/skills/productivity/skill-review/SKILL.md) | 스킬이 구조 규약과 실행 기준을 지키는지 점검하고, 어긋난 곳을 고칠 안을 낸다. |

### 공용 하위 모듈

스킬이 포인터로 읽는 파일이다. 직접 호출하지 않는다.

| 모듈 | 내용 |
|---|---|
| [`lib/answer-style.md`](claude/lib/answer-style.md) | 답변·문서 작성 규칙 (`~/.claude/CLAUDE.md`가 import해 모든 답변에 적용) |
| [`lib/document-tone.md`](claude/lib/document-tone.md) | PR 본문·코멘트 같은 문서의 문장 끝 규칙 (`pr-rules.md`가 가리킨다) |
| [`lib/diagram/`](claude/lib/diagram/) | 도식 형식 고르기(코드블록 · markdown 표 · HTML) · HTML 틀 둘(양의 이동을 보이는 생키 도식, 단계별 흐름과 경로를 비교하는 흐름 지도) |
| [`lib/explain/`](claude/lib/explain/) | 개념 설명 서술 방식(공통 규칙 `index.md` · 상황에 맞을 때만 더 읽는 코드 · 비교 · 문서 분할) |
| [`lib/coding/`](claude/lib/coding/) | 코드 규칙. 분야별 모듈(process·architecture·domain·types·design·tests·errors·functions·file-layout·comments·naming·db·repositories·api·ui)이고 스택 규칙은 `{분야}-{스택}.md` 파일(python·frontend·proto)에 있다. 목차 `index.md`가 작업마다 읽을 모듈을 고른다 |
| [`lib/api-aip/`](claude/lib/api-aip/) | API 설계 규칙: 트랙(proto·REST) 선택, 적용/보류 정책, 트랙별 체크. `aip/`는 Google API Improvement Proposals(https://google.aip.dev, CC BY 4.0) 28개를 한국어로 요약한 것 |
| [`lib/guard.md`](claude/lib/guard.md) | 위험 명령 경고·디렉토리 편집 제한 |
| [`lib/grill.md`](claude/lib/grill.md) | 결정 닫기 절차(결정 트리 · 사실 조사 · 질문 라운드) |
| [`lib/explain-html.md`](claude/lib/explain-html.md) | HTML 해설서 작성 규칙 |
| [`lib/cross-check.md`](claude/lib/cross-check.md) | 다른 AI 교차 검증(Claude면 Codex, Codex면 Claude) 실행·회수 |
| [`lib/codex.md`](claude/lib/codex.md) | 공유 스킬의 도구·질문·서브에이전트 호출을 Codex에 맞추는 규칙 |
| [`lib/owasp.md`](claude/lib/owasp.md) | OWASP 5종 점검 항목·source→sink 증명 |
| [`lib/plans-path.md`](claude/lib/plans-path.md) | 작업 산출물 저장 경로 규칙 · HTML 파일 백업·열기 |
| [`lib/pr-rules.md`](claude/lib/pr-rules.md) | 브랜치·커밋·PR 본문·리뷰 대응·stacked PR 규칙 (`/implement`·`/implement-review`·`/push-commit`·`/pr-create`·`/investigate`가 읽는다) |
| [`lib/review/`](claude/lib/review/) | 코드 리뷰 기준(공통·언어별·도구별·관점·보안 게이트) · 리뷰 준비(PR 링크 → diff) · 문제 지점 찾기(리뷰 공통 절차) · 주장 검증 |
| [`lib/skill-writing.md`](claude/lib/skill-writing.md) | 스킬·모듈 작성 규칙 25개 (`/skill-review` 4단계가 읽는다) |

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

`bash install.sh`는 멱등입니다. 레포의 `claude/*.md`·`claude/*.sh`·`settings.json`·`claude/lib/*`·`claude/hooks/*`와 버킷 안 스킬을 각각 symlink하고, 대상이 사라진 symlink는 지웁니다. 공개·회사 스킬은 Codex에도 같은 원본으로 연결합니다. 스킬을 추가하면 이름 목록을 수정할 필요 없이 다음 설치 때 반영됩니다.

전체 맥 셋업 없이 스킬 연결만 갱신할 때는 `python3 scripts/sync-codex-skills.py`를 실행합니다. `--dry-run`은 변경 예정 목록, `--check`는 동기화 상태를 확인합니다. `--project <경로>`를 붙이면 같은 이름의 프로젝트 사본을 해당 프로젝트의 `.codex/skill-backups/` 또는 `.agents/skill-backups/`로 백업하고 공용 스킬을 사용합니다. 프로젝트 전용 이름의 스킬과 Codex 시스템 스킬은 유지합니다.

공유 대상은 이 레포의 공개·회사 스킬입니다. Claude 앱이 자동 배포하는 `synced/` 스킬과 플러그인은 각 제품의 설치·연결 방식으로 관리합니다. `refresh-session`은 Codex에서 새 세션 명령과 이어갈 프롬프트를 만들어 전달하며, Claude 전용 훅을 실행하지 않습니다.

레포 파일이 `~/.claude/CLAUDE.md`, `~/.zshrc` 등으로 symlink 됩니다. 실 파일을 에디팅하면 레포가 자동으로 바뀌므로 git으로 변경 추적이 바로 됩니다. 로그·캐시(`~/.claude/sessions/`, `~/.codex/history.jsonl` 등)는 `~/.claude`·`~/.codex` 내에 실물 디렉토리로 남아 레포에는 섞이지 않습니다.

## 반영 범위

**포함**: 언어·프로젝트와 무관한 **범용 개발 환경**: 코딩 룰, 스킬(리뷰/계획/디버깅/보안), CLI 설정, zsh + Homebrew, VSCode 글로벌 설정/키바인딩/확장.

**제외**:
- 시크릿(Linear API key, Redash config, 인증 토큰)
- 회사/업무 특화 스킬(옵시디언·Linear 통합용 `daily-todo`·`linear-card` 등)
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
