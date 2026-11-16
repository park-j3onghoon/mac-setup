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
│   ├── hooks/            # PreToolUse 훅 (되돌릴 수 없는 git 명령 차단) · SessionStart 훅 (/refresh-session 다음 명령 입력)
│   ├── skills/           # engineering/ · productivity/ 버킷 (스킬 목록은 아래 표)
│   ├── lib/              # 스킬이 포인터로 읽는 하위 공용 모듈 (코드 규칙, API 설계, 리뷰 기준·절차, 다른 AI 교차 검증)
│   └── account-switcher/ # 사용률에 따라 Claude Code 로그인 계정을 자동 전환 (설정은 claude/account-switcher/README.md)
├── scripts/              # 설정 검사 (check-layers · verify · check-pair) · 스킬 연결 (sync-codex-skills)
├── private/              # 회사 전용 설정 (gitignore, 클론에 포함되지 않음)
├── codex/                # ~/.codex/ 로 symlink 대상
│   ├── AGENTS.md
│   ├── config.toml       # symlink 대신 없을 때만 복사
│   ├── hooks.json
│   ├── hooks/            # Claude의 deny 규칙을 Codex에 적용하는 훅
│   ├── chrome-devtools/  # Codex chrome-devtools MCP 공유 연결 브리지 (config.toml이 실행)
│   ├── account-switcher/ # 사용률에 따라 Codex 로그인 계정을 자동 전환 (설정은 codex/account-switcher/README.md)
│   └── skills/           # .system만 추적(install.sh가 링크하지 않음). 공개·회사 스킬 전체는 같은 Claude 원본을 링크
├── vscode/               # ~/Library/Application Support/Code/User/ 로 symlink 대상
│   ├── settings.json     # PyCharm 스타일, JDK 21, Kotlin/TS/Python 포매터, 파일 중첩 등
│   ├── keybindings.json  # PyCharm 단축키 (Cmd+B 토글, Cmd+1/2/4 패널 토글, Cmd+Esc 등)
│   └── extensions/       # 로컬 확장 소스 (goto-declaration-or-usages: Cmd+B 정의 ↔ 사용처). 설치는 setup-notes.md
├── rancher/              # Rancher Desktop을 쉬는 동안 끄는 launchd 에이전트 (설치는 rancher/README.md)
├── cmux/                 # cmux 알림 필터 (등록은 cmux/README.md)
└── mac/
    ├── zshrc             # oh-my-zsh + 플러그인 + alias + PATH
    ├── zprofile          # brew shellenv
    ├── Brewfile          # brew bundle (앱 + VSCode 확장 포함)
    └── setup-notes.md    # 자동화 안 되는 수동 단계
```

## 스킬

Claude Code에서는 `/이름`, Codex에서는 `$이름`으로 실행한다. 공개·회사 스킬 전체가 같은 원본을 공유하며, 두 도구 모두 요청에 맞는 스킬을 AI가 스스로 고를 수도 있다. 회사 전용 스킬은 git이 추적하지 않는 `private/` 트리에 있어 이 목록에 없다.

### engineering

| 스킬 | 하는 일 |
|---|---|
| [`/ai-review`](claude/skills/engineering/ai-review/SKILL.md) | 다른 사람의 PR에 리뷰를 달아 달라고 할 때, PR을 위험도에 맞춘 리뷰어로 리뷰하고 코드는 고치지 않은 채 결과를 GitHub 리뷰 한 건으로 단다. CRITICAL이 없으면 승인하며 나머지 코멘트를 달고, 있으면 CRITICAL 코멘트만 달아 수정을 요청한다. 올리기 전에 초안을 승인받는다. 내 PR을 고치는 리뷰와 GitHub에 올리지 않는 읽기 전용 리뷰에는 쓰지 않는다. |
| [`/cso`](claude/skills/engineering/cso/SKILL.md) | 레포 전체 보안 감사를 해 달라고 할 때, Read-only로 시크릿·공급망·CI/CD·OWASP·STRIDE를 훑어 exploitable한 발견만 보고서로 낸다. 브랜치 변경분만 보는 보안 점검에는 쓰지 않는다. |
| [`/grill`](claude/skills/engineering/grill/SKILL.md) | 계획·초안·주제의 결정을 확인해 달라고 할 때 결정을 끝까지 캐묻는다. 사실은 내가 찾고, 갈림길은 한 턴에 하나씩 묻고, 합의된 결정을 decisions.md로 남긴다. 답이 하나로 정해지는 사실 질문에는 쓰지 않는다. |
| [`guard`](claude/skills/engineering/guard/SKILL.md) | 코드·설정을 고치는 작업을 시작할 때 이번 세션에 안전 모드를 건다. 위험 명령을 경고하고, 고칠 디렉토리 밖을 편집할 때 확인한다. 범위 밖을 고쳐야 하면 `off`로 편집 제한을 푼다. 읽기만 하는 조사·답변에는 쓰지 않는다. |
| [`/implement`](claude/skills/engineering/implement/SKILL.md) | 확정된 계획이나 정한 범위를 구현해 달라고 할 때, 계획을 vertical slice 단위로 구현한다. 안전 모드와 코드 규칙을 적용하고, 슬라이스마다 테스트 통과 후 커밋하며, 끝에 simplify로 정리한 변경도 검증 후 별도 커밋한다. 원인을 모르는 버그 수정에는 쓰지 않는다. |
| [`/implement-review`](claude/skills/engineering/implement-review/SKILL.md) | 내 PR이나 구현 커밋을 리뷰해 달라고 할 때 위험도에 맞춘 리뷰어로 리뷰한다. 다시 리뷰할 때는 직전 리뷰 뒤 커밋만 보고, `--full`이면 처음부터 다시 본다. 발견마다 고치거나 하나씩 물어 반영하고, 테스트 통과 후 수정분을 별도 커밋한다. 다른 사람의 PR 리뷰에는 쓰지 않는다. |
| [`/investigate`](claude/skills/engineering/investigate/SKILL.md) | 버그·에러·장애의 원인을 모를 때 근본 원인까지 추적해 고치고 DEBUG REPORT로 마감한다. 원인과 고칠 곳이 이미 정해진 수정에는 쓰지 않는다. |
| [`/plan-review`](claude/skills/engineering/plan-review/SKILL.md) | 구현 계획을 리뷰해 달라고 할 때, 계획을 코드 작성 전에 스코프 챌린지·6차원 리뷰·다른 AI 교차 검증으로 통과시킨다. 이미 구현한 코드의 리뷰에는 쓰지 않는다. |
| [`/pr-create`](claude/skills/engineering/pr-create/SKILL.md) | push된 브랜치로 PR을 만들어 달라고 할 때 Draft PR을 만든다. 받을 리뷰(CodeRabbit·사내 AI 리뷰 봇)를 추천과 함께 고르게 한 뒤, 제목·본문 초안을 승인받아 만들고 고른 리뷰를 CodeRabbit → 사내 AI 리뷰 봇 순서로 요청해 끝날 때까지 기다린 뒤 지적에 모두 대응한다. push 전인 변경과 이미 PR이 있는 브랜치에는 쓰지 않는다. |
| [`/push-commit`](claude/skills/engineering/push-commit/SKILL.md) | 사용자가 push를 요청할 때 변경을 커밋하고 브랜치를 push한 뒤, PR이 있으면 제목·본문을 코드에 맞춘다. 사람 리뷰를 받기 전이면 Claude가 push하고, 받은 뒤면 사용자가 push한다. push 요청이 없는 로컬 커밋에는 쓰지 않는다. |

기본 흐름은 `/implement`(테스트·구현 커밋) → `/implement-review`(테스트·별도 수정 커밋) → `/push-commit` → `/pr-create`(Draft 생성, 고른 경우 CodeRabbit → 사내 AI 리뷰 봇 리뷰를 받고 지적 대응)다.

### productivity

| 스킬 | 하는 일 |
|---|---|
| [`/explain-html`](claude/skills/productivity/explain-html/SKILL.md) | 개념·설계·코드 흐름을 그림이 든 HTML 해설서로 설명해 달라고 할 때, 주제를 조사해 인라인 SVG 도식이 들어간 단일 파일 HTML 해설서를 만들고 ~/plans에 저장한 뒤 브라우저로 연다. 채팅 답으로 충분한 설명에는 쓰지 않는다. |
| [`/mastery-tutor`](claude/skills/productivity/mastery-tutor/SKILL.md) | 슬랙 스레드나 개념을 사전지식부터 블록별로 정복하고 진척 퍼센트를 표시한다. 학습 정리·오답·진행 상황을 Codex와 Claude 공용 로컬 기록에 저장해 중복 지식은 재사용하고 약점을 우선 재검증하며, 중단 뒤 이어서 할 수 있다. 질문별로 답을 받고 남은 질문을 즉시 수정·제거하며, 자세한 채점·해설은 나중에 공개한다. "완전히 이해할 때까지 질문해", "퀴즈로 공부하자", "사전지식부터 정복하자", "전에 하던 학습 이어서"에 쓴다. 단순 요약이나 일회성 개념 설명에는 적용하지 않는다. |
| [`/refresh-session`](claude/skills/productivity/refresh-session/SKILL.md) | 사용자가 새 세션에서 이어 가자고 할 때, 다음 작업을 새 프로세스의 빈 컨텍스트에서 잇는다. Claude Code·Codex 둘 다 지금 세션을 끄고 같은 cmux 탭에서 다시 띄우거나(Claude Code는 설치된 최신 버전으로) 새 탭 명령을 만든다. 지금 세션에서 이어 하는 작업에는 쓰지 않는다. |
| [`/rules-refresh`](claude/skills/productivity/rules-refresh/SKILL.md) | AI 규칙을 다시 짜거나 주기 갱신·PR 대조를 해 달라고 할 때, AI 규칙(진입 파일·lib·instructions·스킬·검사 스크립트)을 개발 방법론과 Simple Design 기준에 맞춰 다시 짜고, 매주 바뀐 것만 갱신하며, 매달 지난달 머지 PR로 리뷰 규칙을 리뷰봇·사람 리뷰와 대조한다. 정해진 문장을 고치는 요청에는 쓰지 않는다. |

### 공용 하위 모듈

스킬이 포인터로 읽는 파일이다. 직접 호출하지 않는다.

| 모듈 | 내용 |
|---|---|
| [`lib/work-style.md`](claude/lib/work-style.md) | 일하는 규칙: 묻는 범위(시스템·데이터 레벨만), 요청 읽기, 알리기, 맡기기, 운영 (`~/.claude/CLAUDE.md`가 import해 모든 작업에 적용) |
| [`lib/answer-style.md`](claude/lib/answer-style.md) | 답변·문서 작성 규칙 (`~/.claude/CLAUDE.md`가 import해 모든 답변에 적용) |
| [`lib/debug.md`](claude/lib/debug.md) | 문제 원인을 찾고 고치는 순서: 증상 → 이론과 코드 → 원인 후보 → 실험 → 수정 → 판정 |
| [`lib/document-tone.md`](claude/lib/document-tone.md) | PR 본문·RFC·카드 같은 문서의 문장 끝 규칙 |
| [`lib/comment-tone.md`](claude/lib/comment-tone.md) | 내 계정으로 다는 리뷰 코멘트·리뷰 본문·답글의 말투 (직접 쓴 GitHub 코멘트에서 뽑은 문장 끝·묻는 법·nit·LGTM·감사 표현) |
| [`lib/diagram/`](claude/lib/diagram/) | 도식 형식 고르기(코드블록 · markdown 표 · HTML) · HTML 틀 둘(양의 이동을 보이는 생키 도식, 단계별 흐름과 경로를 비교하는 흐름 지도) |
| [`lib/explain/`](claude/lib/explain/) | 개념 설명 서술 방식 |
| [`lib/coding/`](claude/lib/coding/) | 코드 규칙. 분야별 모듈(process·architecture·domain·types·design·tests·errors·functions·file-layout·comments·naming·db·repositories·api·ui)이고 스택 규칙은 `{분야}-{스택}.md` 파일(python·frontend·proto)에 있다. 목차 `index.md`가 작업마다 읽을 모듈을 고른다 |
| [`lib/api-aip/`](claude/lib/api-aip/) | API 설계 규칙: 트랙(proto·REST) 선택, 적용/보류 정책, 트랙별 체크. `aip/`는 Google API Improvement Proposals(https://google.aip.dev, CC BY 4.0)를 한국어로 요약한 것 |
| [`lib/guard.md`](claude/lib/guard.md) | 위험 명령 경고·디렉토리 편집 제한 |
| [`lib/grill.md`](claude/lib/grill.md) | 결정 닫기 절차(결정 트리 · 사실 조사 · 질문 라운드) |
| [`lib/explain-html.md`](claude/lib/explain-html.md) | HTML 해설서 작성 규칙 |
| [`lib/cross-check.md`](claude/lib/cross-check.md) | 다른 AI 교차 검증(Claude면 Codex, Codex면 Claude) 실행·회수 |
| [`lib/codex.md`](claude/lib/codex.md) | 공유 스킬의 도구·질문·서브에이전트 호출을 Codex에 맞추는 규칙 |
| [`lib/owasp.md`](claude/lib/owasp.md) | OWASP 5종 점검 항목·source→sink 증명 |
| [`lib/plans-path.md`](claude/lib/plans-path.md) | 작업 산출물 저장 경로 규칙 · HTML 파일 백업·열기 |
| [`lib/pr-rules.md`](claude/lib/pr-rules.md) | 브랜치·커밋·PR 본문·리뷰 대응·stacked PR 규칙 |
| [`lib/push.md`](claude/lib/push.md) | 대상 확정(브랜치·저장소·PR), push(사람 리뷰 여부로 push할 사람을 정함·stacked 전파), PR 제목·본문 갱신 절차 |
| [`lib/review/`](claude/lib/review/) | 코드 리뷰 기준(공통·언어별·도구별·관점·보안 게이트) · 리뷰 준비(PR 링크 → diff) · 문제 지점 찾기(리뷰 공통 절차) · 지적 반영(AUTO-FIX·ASK) · 주장 검증 |
| [`lib/skill-writing.md`](claude/lib/skill-writing.md) | 스킬·모듈 작성 규칙 25개 |

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

Claude 앱이 자동 배포하는 `synced/` 스킬과 플러그인은 각 제품의 설치·연결 방식으로 관리합니다.

레포 파일이 `~/.claude/CLAUDE.md`, `~/.zshrc` 등으로 symlink 됩니다. 실 파일을 에디팅하면 레포가 자동으로 바뀌므로 git으로 변경 추적이 바로 됩니다. 로그·캐시(`~/.claude/sessions/`, `~/.codex/history.jsonl` 등)는 `~/.claude`·`~/.codex` 내에 실물 디렉토리로 남아 레포에는 섞이지 않습니다.

## 반영 범위

**포함**: 언어·프로젝트와 무관한 **범용 개발 환경**: 코딩 룰, 스킬(리뷰/계획/디버깅/보안), CLI 설정, zsh + Homebrew, VSCode 글로벌 설정/키바인딩/확장.

**제외**:
- 시크릿(Linear API key, Redash config, 인증 토큰)
- 회사/업무 특화 스킬(옵시디언·Linear 통합용 `linear-card` 등)
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
