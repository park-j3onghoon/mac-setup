# OpenCode Workflow

`opencode` 기반 듀얼 lane(impl + review) Phase 0~19 자동 실행 스크립트.

- 구현 lane: 보통 Claude Opus 계열 모델
- 리뷰 lane: 보통 Codex 계열 모델
- 각 phase는 lane 2개를 순차 실행하고, completion marker를 찾으면 종료한다.

## 핵심 규칙

- iteration 기본값: `30`
- iteration 상한: `50`
- 기본값이 적용되면 실행 시작 시 출력
- 상한이 적용되거나(요청 > 50), 상한값(`50`)을 쓰는 경우 실행 시작 시 출력

## 설치

```bash
chmod +x ~/git/mac-setup/opencode-workflow/run-workflow.sh
mkdir -p ~/.local/bin
ln -sf ~/git/mac-setup/opencode-workflow/run-workflow.sh ~/.local/bin/ow
```

확인:

```bash
ow --help
```

## 사용법

```bash
ow -s <session> <spec_paths...> [options]
```

예시:

```bash
# iteration 미지정 -> 기본 30 사용 (출력됨)
ow -s displaycam-pr4 docs/spec.md docs/spec_detail_4.md -m adscenter/displaycam_partner

# 사용자 지정 (상한 미만)
ow -s displaycam-pr4 docs/spec.md -m src/app --iterations 40

# 상한 초과 요청 -> 50으로 제한 (출력됨)
ow -s displaycam-pr4 docs/spec.md -m src/app --iterations 200

# 상한값 50 직접 사용 (출력됨)
ow -s displaycam-pr4 docs/spec.md -m src/app --iterations 50
```

## 옵션

- `-s, --session NAME`: 세션 이름 (필수)
- `-m, --module PATH`: 구현 대상 모듈 경로 (기본 `.`)
- `-t, --test PATH`: 테스트 경로 (기본 `{module}/tests` 있으면 사용, 없으면 `{module}`)
- `-i, --iterations N`: phase별 최대 iteration
- `--from N`: 시작 phase 번호 (`0~19`)
- `--impl-model MODEL`: 구현 lane 모델
- `--review-model MODEL`: 리뷰 lane 모델
- `--impl-agent NAME`: 구현 lane agent
- `--review-agent NAME`: 리뷰 lane agent
- `--impl-effort LEVEL`: 구현 lane 추론 힌트(프롬프트에만 반영)
- `--review-effort LEVEL`: 리뷰 lane 추론 힌트(프롬프트에만 반영)
- `--templates DIR`: 커스텀 phase 템플릿 디렉토리
- `--dry-run`: 실제 실행 없이 phase 계획만 출력

## 모델/에이전트 기본값

스크립트 기본값:

- impl model: `anthropic/claude-opus-4-1`
- review model: `openai/gpt-5-codex`

환경 변수로 기본값을 바꿀 수 있다:

```bash
export OPW_IMPL_MODEL="anthropic/claude-opus-4-1"
export OPW_REVIEW_MODEL="openai/gpt-5-codex"
export OPW_IMPL_AGENT="build"
export OPW_REVIEW_AGENT="code-reviewer"
```

## 템플릿 탐색 순서

phase 템플릿(`phase0-plan.md` 등)은 아래 순서로 찾는다.

1. `--templates DIR`
2. `{project}/scripts/opencode-workflow/`
3. `~/git/mac-setup/opencode-workflow/`
4. `~/git/mac-setup/codex-workflow/` (fallback)
5. `~/git/mac-setup/ralph-workflow/` (fallback)

## 세션 결과물

세션 디렉토리:

`~/git/mac-setup/opencode-workflow/sessions/{session_name}/`

주요 파일:

- `ow-events.log`: phase/lane 이벤트 로그
- `ow-phase-{phase}-iter-{iter}-{lane}.log`: lane 실행 로그
- `ow-phase-{phase}-iter-{iter}-{lane}-prompt.md`: lane 프롬프트 스냅샷
- `state.env`: 세션 상태

