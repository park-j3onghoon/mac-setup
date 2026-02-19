# Ralph Workflow

Claude Code + Ralph Loop 기반 Phase 1~8 자동화 파이프라인.
spec 문서를 입력하면 구현 → 리뷰 → 구조 개선 → 엣지케이스 → 통합 테스트 → 적대적 리뷰 → 배포 판정까지 자동 수행한다.

## 설치

### 사전 요구사항

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 설치 및 인증 완료
- [Ralph Loop 플러그인](https://github.com/anthropics/claude-plugins-official) 설치
  ```bash
  claude /install-plugin ralph-loop
  ```

### 설치 방법

```bash
# 1. mac-setup 레포 클론 (이미 있으면 생략)
git clone <your-mac-setup-repo> ~/git/mac-setup

# 2. 실행 권한 부여
chmod +x ~/git/mac-setup/ralph-workflow/run-workflow.sh

# 3. 전역 명령 등록 (~/.local/bin이 PATH에 있어야 함)
mkdir -p ~/.local/bin
ln -sf ~/git/mac-setup/ralph-workflow/run-workflow.sh ~/.local/bin/rw

# 4. PATH 확인 (~/.zshrc에 아래가 있는지 확인)
# export PATH="$HOME/.local/bin:$PATH"
```

설치 확인:
```bash
rw --help
```

### 에이전트 설치

프로젝트 루트에서 `rw --init`을 실행하면 `.claude/agents/`에 symlink가 생성된다:

```bash
cd ~/my-project
rw --init
```

설치되는 에이전트:
| 에이전트 | 역할 | 사용 Phase |
|---------|------|-----------|
| spec-reviewer | spec 대조 리뷰 | 2 |
| side-effect-analyzer | 사이드 이펙트 분석 | 2 |
| structure-optimizer | 구조 최적화 | 3 |
| edge-case-hunter | 엣지케이스 사냥 | 5 |
| integration-verifier | 통합 검증 | 6 |
| adversarial-reviewer | 적대적 리뷰 | 7 |
| deployment-judge | 배포 판정 | 8 |

Phase 2, 4에서 사용하는 `code-reviewer`, `security-reviewer`는
[Everything Claude Code](https://github.com/anthropics/everything-claude-code) 플러그인에 포함되어 있다.

---

## 사용법

### 기본 사용

```bash
# 프로젝트 루트에서 실행
cd ~/my-project

# spec 1개 실행 (Phase 1~8 전체)
rw docs/spec.md -m src/myapp

# 여러 spec 순차 실행
rw docs/spec_1.md docs/spec_2.md docs/spec_3.md -m src/myapp
```

### 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `-m`, `--module PATH` | 구현 대상 모듈 경로. lint/mypy/리뷰 범위 지정 | `.` |
| `-t`, `--test PATH` | 테스트 디렉토리 경로 | `{module}/tests` |
| `-n`, `--max-iterations N` | 이터레이션 비례 스케일링 (아래 참조) | 5 (기본 최대) |
| `--start-phase N` | N번 Phase부터 시작 | 1 |
| `--phase N` | 특정 Phase만 실행 | - |
| `--templates DIR` | 커스텀 템플릿 디렉토리 | - |
| `--dry-run` | 실제 실행 없이 프롬프트만 확인 | - |

### `--module` 이란?

Phase 템플릿에서 `{{MODULE_PATH}}`와 `{{TEST_PATH}}`로 치환되는 경로이다.
lint, type check, 리뷰 에이전트들이 이 경로를 대상으로 작동한다.

```bash
# 예시: Django 프로젝트
rw docs/spec.md -m adscenter/displaycam_partner

# 템플릿 안에서 이렇게 사용됨:
#   uv run ruff check adscenter/displaycam_partner
#   uv run mypy adscenter/displaycam_partner
#   pytest adscenter/displaycam_partner/tests --reuse-db
```

`--module` 미지정 시 `.`(현재 디렉토리)이 되어 프로젝트 전체에 대해 실행된다.

### `--max-iterations` 비례 스케일링

기본 이터레이션 비율 5:5:3:3:3:3:3:2를 유지하면서 스케일링한다 (올림 적용).

```
기본 (--max-iterations 미지정):
  Phase 1~2: 5회, Phase 3~7: 3회, Phase 8: 2회  →  총 27회

--max-iterations 10:
  Phase 1~2: 10회, Phase 3~7: 6회, Phase 8: 4회  →  총 54회

--max-iterations 20:
  Phase 1~2: 20회, Phase 3~7: 12회, Phase 8: 8회  →  총 108회
```

### 사용 예시

```bash
# 기본 실행
rw docs/spec_detail_2.md -m adscenter/displaycam_partner

# 품질 최대치 (이터레이션 늘리기)
rw docs/spec_detail_2.md -m src/myapp -n 15

# Phase 5(엣지케이스)만 다시 실행
rw docs/spec_detail_2.md -m src/myapp --phase 5

# Phase 3부터 이어서
rw docs/spec_detail_2.md -m src/myapp --start-phase 3

# dry-run으로 프롬프트 확인만
rw docs/spec_detail_2.md -m src/myapp --dry-run

# 여러 spec 한 번에 (각각 Phase 1~8 순차)
rw docs/spec_{1..5}.md -m src/myapp -n 10

# 프로젝트별 커스텀 템플릿 사용
rw docs/spec.md -m src/myapp --templates ./my-templates/
```

---

## Phase 상세

| Phase | 이름 | 기본 | 하는 일 | 사용 에이전트 |
|-------|------|------|---------|--------------|
| 1 | 구현 | 5회 | spec 읽고 구현 + 테스트 작성 + 통과 | tester |
| 2 | 리뷰+수정 | 5회 | 다각도 리뷰 후 이슈 수정 | spec-reviewer, python-reviewer, security-reviewer, side-effect-analyzer |
| 3 | 구조 개선 | 3회 | 큰 함수/파일 분리, 재사용, 데드코드 | structure-optimizer |
| 4 | 최종 검증 | 3회 | 전체 변경사항 코드 리뷰 | code-reviewer, python-reviewer |
| 5 | 엣지케이스 | 3회 | 경계값/예외 시나리오 발견 + 테스트 | edge-case-hunter |
| 6 | 통합 테스트 | 3회 | 기존 코드와 충돌 확인 | integration-verifier |
| 7 | 적대적 리뷰 | 3회 | reject 관점에서 결함 탐색 | adversarial-reviewer |
| 8 | 배포 판정 | 2회 | SHIP/NO-SHIP 최종 판정 | deployment-judge |

### Phase 흐름

```
Phase 1: 구현 → 테스트 통과
   ↓
Phase 2: 리뷰 → 이슈 수정 → 리뷰 (이슈 0건까지)
   ↓
Phase 3: 구조 개선 → 테스트 확인
   ↓
Phase 4: 전체 검증 → 미세 수정
   ↓
Phase 5: 엣지케이스 발견 → 테스트 추가 → 코드 수정
   ↓
Phase 6: 통합 검증 → 충돌 해결
   ↓
Phase 7: 적대적 리뷰 → 결함 수정 → APPROVE까지
   ↓
Phase 8: 최종 판정 → SHIP IT
```

---

## 템플릿 탐색 순서

Phase 템플릿(phase1-implement.md 등)은 다음 순서로 탐색된다:

1. `--templates` 옵션으로 지정한 디렉토리
2. 프로젝트 로컬: `{프로젝트 루트}/scripts/ralph-workflow/`
3. 글로벌 기본: `~/git/mac-setup/ralph-workflow/`

프로젝트별로 Phase 프롬프트를 커스터마이징하려면 프로젝트에 `scripts/ralph-workflow/` 디렉토리를 만들고 해당 Phase 파일만 오버라이드하면 된다.

---

## 파일 구조

```
~/git/mac-setup/ralph-workflow/     ← 글로벌 (이 레포)
├── README.md
├── run-workflow.sh                 ← 메인 스크립트
├── phase1-implement.md
├── phase2-review-fix.md
├── phase3-structure.md
├── phase4-verify.md
├── phase5-edge-cases.md
├── phase6-integration.md
├── phase7-adversarial.md
├── phase8-deploy-judge.md
└── agents/                         ← 에이전트 템플릿
    ├── spec-reviewer.md
    ├── side-effect-analyzer.md
    ├── structure-optimizer.md
    ├── edge-case-hunter.md
    ├── integration-verifier.md
    ├── adversarial-reviewer.md
    └── deployment-judge.md

~/.local/bin/rw                     ← 심볼릭 링크 → run-workflow.sh
```

---

## 새 컴퓨터 셋업 체크리스트

1. [ ] Claude Code CLI 설치 및 로그인
2. [ ] Ralph Loop 플러그인 설치: `claude /install-plugin ralph-loop`
3. [ ] mac-setup 레포 클론
4. [ ] `chmod +x ~/git/mac-setup/ralph-workflow/run-workflow.sh`
5. [ ] `ln -sf ~/git/mac-setup/ralph-workflow/run-workflow.sh ~/.local/bin/rw`
6. [ ] `~/.zshrc`에 `export PATH="$HOME/.local/bin:$PATH"` 확인
7. [ ] `rw --help`로 동작 확인
8. [ ] 프로젝트에서 `rw --init`으로 에이전트 설치
