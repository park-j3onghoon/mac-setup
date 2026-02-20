# Ralph Workflow

Claude Code + Ralph Loop 기반 Phase 0~19 자동화 파이프라인.
spec 문서를 입력하면 계획 → 검토 → YAGNI → 구현 → 스펙 검증 → 버그/보안 → 수정 검증 → 구조 개선 → 통합 → 사이드이펙트 → 전체 재검토 → 코드 정리 → 품질 → 성능 → DDD → 사용자 흐름 → 심층 검토 → 배포 판정 → 커밋까지 자동 수행한다.

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

설치되는 에이전트 (22개):

| 에이전트 | 역할 | 사용 Phase |
|---------|------|-----------|
| plan-reviewer | 계획 검토 (spec 대조) | 1 |
| plan-verification-reviewer | 계획 재검증 (meta-review) | 2 |
| yagni-reviewer | 과설계/YAGNI 식별 | 3 |
| spec-compliance-verifier | spec 라인별 적합성 검증 | 5 |
| security-reviewer | 보안 취약점 검토 | 6 |
| logic-error-detector | 비즈니스 로직 오류 탐지 | 6 |
| runtime-safety-checker | 런타임 안전성/성능 패턴 검사 | 6 |
| fix-validator | 수정 사항 정확성 검증 | 7 |
| structure-optimizer | 파일/함수 분리, 재사용 탐색 | 8 |
| integration-verifier | 기존 코드 통합 검증 | 9 |
| side-effect-analyzer | 사이드이펙트/암묵적 의존성 분석 | 10 |
| full-spec-auditor | 전체 spec 감사 | 11 |
| architecture-reviewer | SOLID/CQS/레이어 의존성 검증 | 11 |
| dead-code-analyzer | 미사용 코드/import 식별 | 12 |
| quality-inspector | 타입 힌트/네이밍/코드 스멜/로깅 검사 | 13 |
| performance-reviewer | N+1 쿼리/알고리즘/캐싱 성능 검토 | 14 |
| ddd-reviewer | Aggregate/VO/Event/Repository DDD 심층 검증 | 15 |
| ux-reviewer | 사용자 흐름/에러 메시지/상태 전이 검증 | 16 |
| adversarial-reviewer | Reject 관점 결함 탐색 | 17 |
| edge-case-hunter | 경계값/예외 시나리오 사냥 + 테스트 추가 | 17 |
| test-quality-reviewer | Mock 정확성/Assert 완전성/테스트 격리 검증 | 17 |
| deployment-judge | SHIP/NO-SHIP 최종 판정 | 18 |

---

## 사용법

### 기본 사용

```bash
# 프로젝트 루트에서 실행
cd ~/my-project

# spec 1개 실행 (Phase 0~19 전체)
rw -s pr2-impl docs/spec.md -m src/myapp

# 여러 spec 순차 실행
rw -s big-feature docs/spec_1.md docs/spec_2.md docs/spec_3.md -m src/myapp
```

### 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `-s`, `--session NAME` | 세션 이름 (필수). 로그/상태 파일 구분 | - |
| `-m`, `--module PATH` | 구현 대상 모듈 경로. lint/mypy/리뷰 범위 지정 | `.` |
| `-t`, `--test PATH` | 테스트 디렉토리 경로 | `{module}/tests` |
| `-n`, `--multiplier N` | 이터레이션 배수 (float 허용, 아래 참조) | `1` |
| `--templates DIR` | 커스텀 템플릿 디렉토리 | - |
| `--dry-run` | 실제 실행 없이 프롬프트만 확인 | - |
| `--init` | 프로젝트에 에이전트 symlink 설치 | - |

### `--module` 이란?

Phase 템플릿에서 `{{MODULE_PATH}}`와 `{{TEST_PATH}}`로 치환되는 경로이다.
lint, type check, 리뷰 에이전트들이 이 경로를 대상으로 작동한다.

```bash
# 예시: Django 프로젝트
rw -s pr2-impl docs/spec.md -m adscenter/displaycam_partner

# 템플릿 안에서 이렇게 사용됨:
#   uv run ruff check adscenter/displaycam_partner
#   uv run mypy adscenter/displaycam_partner
#   pytest adscenter/displaycam_partner/tests --reuse-db
```

`--module` 미지정 시 `.`(현재 디렉토리)이 되어 프로젝트 전체에 대해 실행된다.

### `-n` 이터레이션 배수

각 Phase에 base 이터레이션이 있고, `-n` 배수와 spec 줄 수에 따라 조정된다:

```
iterations = ceil((base + floor(spec_lines / 300)) × multiplier)
```

```
-n 1 (기본): 총 ~31회 (300줄 이하 spec 기준)
-n 2:        총 ~62회
-n 0.5:      총 ~16회
```

### 세션 관리

세션 상태는 `~/git/mac-setup/ralph-workflow/sessions/{session_name}/`에 저장된다.
워크플로우가 중단되면 동일 spec으로 다시 실행할 때 자동으로 이어서 진행할 수 있다.

```bash
# 중단된 세션이 있으면 자동 감지
rw -s pr2-impl docs/spec.md -m src/myapp
# → "동일 spec의 미완료 세션 발견: Phase 3에서 중단. 이어서 하시겠습니까? (yes/no)"
```

### 사용 예시

```bash
# 기본 실행
rw -s pr2-impl docs/spec_detail_2.md -m adscenter/displaycam_partner

# 품질 최대치 (이터레이션 2배)
rw -s pr2-quality docs/spec_detail_2.md -m src/myapp -n 2

# dry-run으로 프롬프트 확인만
rw -s test-run docs/spec_detail_2.md -m src/myapp --dry-run

# 여러 spec 한 번에
rw -s big-feature docs/spec_{1..5}.md -m src/myapp -n 1.5

# 프로젝트별 커스텀 템플릿 사용
rw -s custom-run docs/spec.md -m src/myapp --templates ./my-templates/
```

---

## Phase 상세

| Phase | 이름 | Base | 하는 일 | 사용 에이전트 |
|-------|------|------|---------|--------------|
| 0 | 계획 수립 | 3 | spec → REQ 추출 → 체크리스트 → Spec Digest → 기존 구현 매핑 → 구현 계획 | (직접) |
| 1 | 계획 검토 | 1 | 체크리스트/계획 vs spec 대조 | plan-reviewer |
| 2 | 검토 검증 | 1 | 1차 검토 결과 자체를 meta-review | plan-verification-reviewer |
| 3 | 과설계 검토 | 1 | YAGNI + DDD 레이어 필요성 검증 | yagni-reviewer |
| 4 | 구현 | 5 | TDD 사이클 (부정 시나리오 우선) + 품질 원칙 자가 점검 | (직접) |
| 5 | 스펙 검증 | 2 | 체크리스트 기반 대조 + 역방향 spec 전문 순회 | spec-compliance-verifier |
| 6 | 버그/보안 | 2 | 보안 + 로직 오류 + 런타임 안전성 병렬 검토 | security-reviewer, logic-error-detector, runtime-safety-checker |
| 7 | 수정 검증 | 1 | Phase 6 수정이 spec을 깨뜨리지 않는지 검증 | fix-validator |
| 8 | 구조 개선 | 2 | 파일/함수 분리, 재사용 탐색, 확장성 | structure-optimizer |
| 9 | 통합/재사용 | 1 | 기존 코드베이스 충돌 확인 | integration-verifier |
| 10 | 사이드이펙트 | 1 | Hook/Signal 체인, 공유 상태 영향 분석 | side-effect-analyzer |
| 11 | 전체 재검토 | 2 | spec 감사 + SOLID/CQS/아키텍처 검증 | full-spec-auditor, architecture-reviewer |
| 12 | 코드 정리 | 1 | Dead code, 미사용 import 제거 | dead-code-analyzer |
| 13 | 코드 품질 | 1 | 타입 힌트, 네이밍, 코드 스멜, 로깅/관측성 | quality-inspector |
| 14 | 성능 검토 | 1 | N+1 쿼리, 알고리즘 복잡도, 캐싱 | performance-reviewer |
| 15 | DDD 심층 | 1 | Aggregate/VO/Event/Repository/Bounded Context | ddd-reviewer |
| 16 | 사용자 흐름 | 1 | API 흐름, 에러 메시지, 상태 전이 | ux-reviewer |
| 17 | 심층 검토 | 2 | 적대적 리뷰 + 엣지케이스 사냥 + 테스트 품질 | adversarial-reviewer, edge-case-hunter, test-quality-reviewer |
| 18 | 배포 판정 | 1 | SHIP/NO-SHIP (하위 호환성 + DB 마이그레이션 포함) | deployment-judge |
| 19 | 커밋 | 1 | git 커밋 | (직접) |

**Base 합계: 31** (= `-n 1`일 때 기본 이터레이션)

**안전망**: Promise 미감지 시 `iterations × 3`회까지 재시도 후 강제 진행. 완료 시 체크리스트/계획/메모를 세션 디렉토리에 보관 (사후 분석용).

### Phase 흐름

```
Phase  0: 계획 수립 (spec → REQ → 체크리스트 → Spec Digest → 기존 구현 매핑 → 계획)
Phase  1: 계획 검토 (plan-reviewer)
Phase  2: 검토 검증 (plan-verification-reviewer)
Phase  3: 과설계 검토 (yagni-reviewer + DDD 레이어 필요성)
   ↓
Phase  4: 구현 (TDD, 부정 시나리오 우선, 품질 원칙 자가 점검)
Phase  5: 스펙 검증 (체크리스트 대조 + 역방향 spec 전문 순회)
Phase  6: 버그/보안 검토 (security + logic-error + runtime-safety 병렬)
Phase  7: 수정 검증 (fix-validator)
   ↓
Phase  8: 구조 개선 (structure-optimizer)
Phase  9: 통합 검증 (integration-verifier)
Phase 10: 사이드이펙트 분석 (side-effect-analyzer)
Phase 11: 전체 재검토 (full-spec-auditor + architecture-reviewer)
Phase 12: 코드 정리 (dead-code-analyzer)
Phase 13: 코드 품질 (quality-inspector)
Phase 14: 성능 검토 (performance-reviewer)
Phase 15: DDD 심층 (ddd-reviewer)
Phase 16: 사용자 흐름 (ux-reviewer)
   ↓
Phase 17: 심층 검토 (adversarial + edge-case + test-quality 병렬)
Phase 18: 배포 판정 (deployment-judge → SHIP IT)
Phase 19: 커밋
```

---

## 템플릿 탐색 순서

Phase 템플릿(phase0-plan.md 등)은 다음 순서로 탐색된다:

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
├── phase0-plan.md                  ← 계획 수립
├── phase1-plan-review.md           ← 계획 검토
├── phase2-plan-verify.md           ← 검토 검증
├── phase3-yagni.md                 ← 과설계 검토
├── phase4-implement.md             ← 구현
├── phase5-spec-verify.md           ← 스펙 검증
├── phase6-bug-security.md          ← 버그/보안
├── phase7-fix-verify.md            ← 수정 검증
├── phase8-structure.md             ← 구조 개선
├── phase9-integration.md           ← 통합/재사용
├── phase10-side-effects.md         ← 사이드이펙트
├── phase11-full-review.md          ← 전체 재검토
├── phase12-cleanup.md              ← 코드 정리
├── phase13-quality.md              ← 코드 품질
├── phase14-performance.md          ← 성능 검토
├── phase15-ddd-review.md           ← DDD 심층
├── phase16-user-flow.md            ← 사용자 흐름
├── phase17-deep-review.md          ← 심층 검토
├── phase18-deploy-judge.md         ← 배포 판정
├── phase19-commit.md               ← 커밋
├── sessions/                       ← 세션 상태 (gitignore 권장)
│   └── {session-name}/
│       ├── state.env
│       ├── rw-phase-0-prompt.md
│       ├── rw-phase-0.log
│       ├── rw-checklist.md          ← 완료 시 보관
│       ├── rw-spec-digest.md        ← 완료 시 보관 (스펙 요약 인덱스)
│       ├── rw-plan.md               ← 완료 시 보관
│       ├── rw-notes.md              ← 완료 시 보관
│       └── ...
└── agents/                         ← 에이전트 템플릿 (22개)
    ├── adversarial-reviewer.md
    ├── architecture-reviewer.md
    ├── ddd-reviewer.md
    ├── dead-code-analyzer.md
    ├── deployment-judge.md
    ├── edge-case-hunter.md
    ├── fix-validator.md
    ├── full-spec-auditor.md
    ├── integration-verifier.md
    ├── logic-error-detector.md
    ├── performance-reviewer.md
    ├── plan-reviewer.md
    ├── plan-verification-reviewer.md
    ├── quality-inspector.md
    ├── runtime-safety-checker.md
    ├── security-reviewer.md
    ├── side-effect-analyzer.md
    ├── spec-compliance-verifier.md
    ├── structure-optimizer.md
    ├── test-quality-reviewer.md
    ├── ux-reviewer.md
    └── yagni-reviewer.md

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
