# Codex Workflow

`ralph-workflow`를 참고해 만든 Codex 전용 Phase 0~19 자동화 워크플로우.

핵심 동작:
- spec 문서를 기준으로 20개 Phase를 순차 실행
- 각 Phase는 `max-iterations` 내에서 반복 실행
- 각 이터레이션은 로그 기반 정체 감지 + token limit(0-토큰) 자동 재시도 안전망으로 보호
- 각 Phase는 `<promise>...</promise>` 완료 마커를 우선 검증하며, 미검출 시 제한된 재시도 후 강제 진행

기본 실행 모델/추론:
- 모델: `gpt-5.3-codex`
- 추론 강도: `xhigh` (미지정 시 최상)
- 리뷰 assistant 기본값: `codex` (`--assistant claude`로 Claude 리뷰 가능)

## 요구사항

- Codex CLI 설치 + 로그인 완료
- Git 저장소 루트에서 실행

## 설치

```bash
chmod +x ~/git/mac-setup/codex-workflow/run-workflow.sh
mkdir -p ~/.local/bin
ln -sf ~/git/mac-setup/codex-workflow/run-workflow.sh ~/.local/bin/cw
```

확인:

```bash
cw --help
```

## 사용법

```bash
# 기본 실행
cd ~/my-project
cw -s pr2-impl docs/spec.md -m src/myapp

# 여러 spec을 하나의 세션으로 처리
cw -s big-feature docs/spec_1.md docs/spec_2.md -m src/myapp

# 이터레이션 배수 조정
cw -s pr2-quality docs/spec.md -m src/myapp -n 1.5

# 모델/추론 강도 지정 (기본값과 동일)
cw -s pr2-impl docs/spec.md -m src/myapp --model gpt-5.3-codex --reasoning-effort xhigh

# 특정 Phase부터 시작
cw -s pr2-impl docs/spec.md -m src/myapp --from 4

# 큰 spec 분할
cw --spec-split docs/large-spec.md --max-lines 500 --review-hours 1.5

# 완료된 세션 리뷰 시작
cw --review -s pr2-impl --assistant codex

# dry-run (프롬프트/단계만 확인)
cw -s dry docs/spec.md -m src/myapp --dry-run
```

## 옵션

- `-s, --session NAME`: 세션 이름 (필수)
- `-m, --module PATH`: 구현 대상 모듈 경로 (기본 `.`)
- `-t, --test PATH`: 테스트 경로 (기본: `{module}/tests` 있으면 그 경로, 없으면 `{module}`)
- `-n, --multiplier N`: 이터레이션 배수 (float 허용)
- `--from N`: 시작 phase 번호 (0~19)
- `--model MODEL`: `codex exec --model`로 전달할 모델 (기본 `gpt-5.3-codex`)
- `--reasoning-effort LEVEL`: `codex exec -c model_reasoning_effort="..."`로 전달할 추론 강도 (기본 `xhigh`, 미지정 시 최상)
- `--spec-split FILE`: 큰 spec을 PR 단위로 분할 (`--max-lines N`, `--review-hours H`, 기본 1.5h)
- `--review`: 세션 리뷰 파일 생성 + 리뷰 세션 시작 (`-s` 필요)
  - 세션이 기본 경로에 없으면, 프로젝트 로컬(`scripts/codex-workflow`, `scripts/ralph-workflow`)과 글로벌 `ralph-workflow/sessions`까지 자동 탐색
- `--assistant NAME`: `--review` 실행 도우미 (`codex`, `claude`, `none`, 기본 `codex`)
- `--templates DIR`: 커스텀 Phase 템플릿 디렉토리
- `--dry-run`: 실행 없이 각 Phase 프롬프트만 점검
- `--init`: 프로젝트 `AGENTS.md`에 cw 가이드 블록 설치/업데이트
- `--clean`: 저장된 세션 디렉토리 정리

## 이터레이션 계산

Phase별 이터레이션 수:

```text
iterations = ceil((base + floor(spec_lines / 300)) × multiplier)
```

Base 합계는 `53`이다.

## 세션/재개

세션 상태 저장 위치:

```text
~/git/mac-setup/codex-workflow/sessions/{session_name}/
```

동일 spec fingerprint의 미완료 세션이 있으면 자동으로 재개 여부를 물어본다.
`--from`을 지정하면 자동 재개 감지를 건너뛰고 지정한 phase부터 시작한다.
`--from`으로 시작할 때 `.codex/cw-*.md` 컨텍스트 파일이 비어 있으면 같은 fingerprint 세션에서 자동 복원한다.

주요 로그/산출물:

- 이벤트 로그: `~/git/mac-setup/codex-workflow/sessions/{session_name}/cw-events.log`
- 이터레이션 로그: `cw-phase-{phase}-iter-{iter}.log`
- 0-토큰 재시도 로그: `cw-phase-{phase}-iter-{iter}-zt-{retry}.log`
- 프롬프트 스냅샷: `cw-phase-{phase}-iter-{iter}-prompt.md`

`cw --review -s <name>`는 위 기본 경로가 없으면 아래 순서로 세션 디렉토리를 자동 탐색한다.
1. `{프로젝트 루트}/scripts/codex-workflow/sessions/{name}`
2. `{프로젝트 루트}/scripts/ralph-workflow/sessions/{name}`
3. `~/git/mac-setup/codex-workflow/sessions/{name}`
4. `~/git/mac-setup/ralph-workflow/sessions/{name}`

## 종료 조건 (Phase 단위)

각 Phase 반복에서 아래 순서로 판정한다:

1. 이터레이션 로그에서 phase별 promise(`PLAN DONE`, `IMPL DONE` 등)를 우선 검증
2. promise 미검출이면 `max-iterations` 범위를 반복 실행
3. 그래도 미검출이면 `iterations × 3`(최대 9회)까지 phase 재시도
4. 재시도 한도 초과 시 경고를 남기고 강제 진행(요약에 미검출 phase 표기)
5. 이터레이션 실행 실패(정체 강제 종료 포함)면 워크플로우 중단

즉, 코드 변경 유무(`no-change`)는 보조 신호로만 쓰고, 완료 마커 계약을 기준으로 단계 전환한다.

## 실행 안전망 (정체 감지 / 0-토큰)

`run-workflow.sh`는 각 이터레이션을 백그라운드로 실행하고 로그를 폴링하며, 다음 안전망을 적용한다.

- 장시간 실행 경고 주기: `STALL_THRESHOLD=900` (15분)
- 로그 성장 체크 주기: `LOG_GROWTH_CHECK_INTERVAL=900` (15분)
- 의미 있는 로그 성장 기준: `LOG_MEANINGFUL_GROWTH=102400` (100KB)
- 로그 무성장 강제 종료 기준: `STALL_KILL_THRESHOLD=3600` (60분)
- 0-토큰 대기 시간: `ZERO_TOKEN_WAIT=600` (10분)
- 0-토큰 최대 재시도: `MAX_ZERO_TOKEN_RETRIES=60` (최대 약 10시간)

동작 요약:

1. 로그에서 rate/token limit 패턴을 주기적으로 탐지한다.
2. 이터레이션 결과가 `0 tokens`이고 token limit 패턴이면 10분 대기 후 **같은 iter를 재시도**한다.
3. 0-토큰 재시도는 phase의 일반 `max-iterations`와 별도로 관리된다.
4. 로그가 장시간 의미 있게 증가하지 않으면 해당 이터레이션을 강제 종료하고 실패 처리한다.

## Codex 네이티브 운영

- Codex는 `.codex/agents`를 표준 자동 로딩 경로로 보지 않는다.
- `cw`는 phase 템플릿에 `Task(subagent_type='...')`가 있으면, 해당 이름의 문서(`agents/<name>.md`)를 자동으로 찾아 프롬프트에 첨부한다.
- 우선순위:
  1. `--templates DIR/agents/<name>.md`
  2. `scripts/codex-workflow/agents/<name>.md` (프로젝트 로컬 override)
  3. `codex-workflow/agents/<name>.md` (기본 템플릿)
- `cw --init`은 `.codex/agents` 링크를 만들지 않고, 프로젝트 `AGENTS.md`에 cw 운용 블록을 설치/업데이트한다.

## 파일 구성

```text
codex-workflow/
├── run-workflow.sh
├── phase0-plan.md
├── ...
├── phase19-commit.md
└── agents/
```
