#!/bin/zsh
# Ralph Workflow - Phase 1~8 자동 체이닝 스크립트 (전역)
#
# 사용법:
#   rw <spec_paths...> [options]
#
# 예시:
#   # 단일 spec
#   ralph-workflow docs/spec_detail_2.md
#
#   # 여러 spec 순차 실행
#   ralph-workflow docs/spec_detail_{2..5}.md
#
#   # Phase 3부터 시작
#   ralph-workflow docs/spec_detail_2.md --start-phase 3
#
#   # 이터레이션 스케일업 (기본 최대 5 → 10으로 비례 증가)
#   rw docs/spec_detail_2.md -n 10
#
#   # 모듈 경로 지정 (기본: 자동 감지)
#   rw docs/spec.md -m src/myapp -t src/myapp/tests
#
# 옵션:
#   --start-phase N      N번 Phase부터 시작 (기본: 1)
#   --phase N            특정 Phase만 실행
#   --dry-run            실제 실행 없이 프롬프트만 출력
#   -n, --max-iterations N  Phase별 비례 스케일링 (기본 최대=5 기준)
#   -m, --module PATH    구현 대상 모듈 경로
#   -t, --test PATH      테스트 디렉토리 경로
#   --templates DIR      커스텀 템플릿 디렉토리
#   --init               프로젝트에 rw 에이전트 symlink 설치

set -euo pipefail

# ─── 경로 설정 ───
GLOBAL_TEMPLATE_DIR="${0:A:h}"  # 심볼릭 링크 resolve 후 실제 디렉토리
PROJECT_ROOT="$(pwd)"
RALPH_STATE_FILE="$PROJECT_ROOT/.claude/ralph-loop.local.md"

# 프로젝트 로컬 템플릿 (있으면 우선)
LOCAL_TEMPLATE_DIR="$PROJECT_ROOT/scripts/ralph-workflow"

# ─── 색상 ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── 유틸리티 ───
format_duration() {
  local seconds=$1
  local m=$((seconds / 60))
  local s=$((seconds % 60))
  if [[ $m -gt 0 ]]; then
    printf "%d분 %02d초" "$m" "$s"
  else
    printf "%d초" "$s"
  fi
}

notify_mac() {
  local title=$1
  local message=$2
  osascript -e "display notification \"$message\" with title \"$title\" sound name \"Glass\"" 2>/dev/null || true
}

# ─── Phase 설정 ───
typeset -A PHASE_NAMES
PHASE_NAMES=(
  1 "구현"
  2 "리뷰+수정"
  3 "구조 개선"
  4 "최종 검증"
  5 "엣지케이스 사냥"
  6 "통합 테스트"
  7 "적대적 리뷰"
  8 "배포 판정"
)

typeset -A PHASE_FILES
PHASE_FILES=(
  1 "phase1-implement.md"
  2 "phase2-review-fix.md"
  3 "phase3-structure.md"
  4 "phase4-verify.md"
  5 "phase5-edge-cases.md"
  6 "phase6-integration.md"
  7 "phase7-adversarial.md"
  8 "phase8-deploy-judge.md"
)

typeset -A PHASE_PROMISES
PHASE_PROMISES=(
  1 "IMPL DONE"
  2 "REVIEW DONE"
  3 "REFACTOR DONE"
  4 "VERIFY DONE"
  5 "EDGE DONE"
  6 "INTEGRATION DONE"
  7 "ADVERSARIAL DONE"
  8 "SHIP IT"
)

typeset -A PHASE_BASE_ITERATIONS
PHASE_BASE_ITERATIONS=(
  1 5
  2 5
  3 3
  4 3
  5 3
  6 3
  7 3
  8 2
)

BASE_MAX=5

# ─── 비례 스케일링 (올림) ───
scale_iterations() {
  local base=$1
  local target_max=$2
  echo $(( (base * target_max + BASE_MAX - 1) / BASE_MAX ))
}

# ─── 템플릿 파일 탐색 (로컬 우선 → 글로벌 폴백) ───
find_template() {
  local filename=$1
  local custom_dir=$2

  # 1. 커스텀 디렉토리 (--templates 옵션)
  if [[ -n "$custom_dir" ]] && [[ -f "$custom_dir/$filename" ]]; then
    echo "$custom_dir/$filename"
    return
  fi

  # 2. 프로젝트 로컬
  if [[ -f "$LOCAL_TEMPLATE_DIR/$filename" ]]; then
    echo "$LOCAL_TEMPLATE_DIR/$filename"
    return
  fi

  # 3. 글로벌 기본
  if [[ -f "$GLOBAL_TEMPLATE_DIR/$filename" ]]; then
    echo "$GLOBAL_TEMPLATE_DIR/$filename"
    return
  fi

  echo ""
}

# ─── 인자 파싱 ───
SPEC_PATHS=()
START_PHASE=1
SINGLE_PHASE=0
DRY_RUN=false
CUSTOM_MAX_ITERATIONS=0
MODULE_PATH=""
TEST_PATH=""
CUSTOM_TEMPLATE_DIR=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --start-phase)
      START_PHASE="$2"
      shift 2
      ;;
    --phase)
      SINGLE_PHASE="$2"
      START_PHASE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --max-iterations|-n)
      CUSTOM_MAX_ITERATIONS="$2"
      shift 2
      ;;
    --module|-m)
      MODULE_PATH="$2"
      shift 2
      ;;
    --test|-t)
      TEST_PATH="$2"
      shift 2
      ;;
    --templates)
      CUSTOM_TEMPLATE_DIR="$2"
      shift 2
      ;;
    --init)
      echo "${CYAN}프로젝트에 rw 에이전트를 설치합니다...${NC}"
      mkdir -p "$PROJECT_ROOT/.claude/agents"
      local count=0
      for agent in "$GLOBAL_TEMPLATE_DIR/agents/"*.md; do
        local name=$(basename "$agent")
        if [[ -L "$PROJECT_ROOT/.claude/agents/$name" ]] || [[ -f "$PROJECT_ROOT/.claude/agents/$name" ]]; then
          echo "  ${YELLOW}skip${NC} $name (이미 존재)"
        else
          ln -sf "$agent" "$PROJECT_ROOT/.claude/agents/$name"
          echo "  ${GREEN}link${NC} $name"
          count=$((count + 1))
        fi
      done
      echo "${GREEN}완료! ${count}개 에이전트 설치됨.${NC}"
      exit 0
      ;;
    --help|-h)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*)
      echo "${RED}알 수 없는 옵션: $1${NC}" >&2
      exit 1
      ;;
    *)
      SPEC_PATHS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#SPEC_PATHS[@]} -eq 0 ]]; then
  echo "${RED}에러: spec 파일 경로를 1개 이상 지정하세요.${NC}" >&2
  echo "사용법: rw <spec_paths...> [options]" >&2
  echo "도움말: rw --help" >&2
  exit 1
fi

# spec 파일 존재 확인
for spec in "${SPEC_PATHS[@]}"; do
  if [[ ! -f "$spec" ]]; then
    echo "${RED}에러: $spec 파일이 존재하지 않습니다.${NC}" >&2
    exit 1
  fi
done

# ─── MODULE_PATH / TEST_PATH 자동 감지 ───
if [[ -z "$MODULE_PATH" ]]; then
  # spec 파일 내용에서 힌트 추출 시도
  first_spec="${SPEC_PATHS[1]}"
  # 기본값: 현재 디렉토리 기준
  MODULE_PATH="."
  echo "${YELLOW}--module 미지정. 기본값 '.' 사용. --module로 지정 권장.${NC}"
fi

if [[ -z "$TEST_PATH" ]]; then
  # MODULE_PATH/tests 가 있으면 사용
  if [[ -d "$MODULE_PATH/tests" ]]; then
    TEST_PATH="$MODULE_PATH/tests"
  else
    TEST_PATH="$MODULE_PATH"
  fi
fi

# ─── Phase별 실제 이터레이션 계산 ───
typeset -A PHASE_MAX_ITERATIONS
for phase in {1..8}; do
  base="${PHASE_BASE_ITERATIONS[$phase]}"
  if [[ $CUSTOM_MAX_ITERATIONS -gt 0 ]]; then
    PHASE_MAX_ITERATIONS[$phase]=$(scale_iterations "$base" "$CUSTOM_MAX_ITERATIONS")
  else
    PHASE_MAX_ITERATIONS[$phase]=$base
  fi
done

# ─── 프롬프트 생성 ───
generate_prompt() {
  local phase_num=$1
  local spec_path=$2
  local template_file
  template_file=$(find_template "${PHASE_FILES[$phase_num]}" "$CUSTOM_TEMPLATE_DIR")

  if [[ -z "$template_file" ]]; then
    echo "${RED}에러: 템플릿 파일을 찾을 수 없습니다: ${PHASE_FILES[$phase_num]}${NC}" >&2
    echo "  탐색 경로:" >&2
    [[ -n "$CUSTOM_TEMPLATE_DIR" ]] && echo "    1. $CUSTOM_TEMPLATE_DIR" >&2
    echo "    2. $LOCAL_TEMPLATE_DIR" >&2
    echo "    3. $GLOBAL_TEMPLATE_DIR" >&2
    return 1
  fi

  local prompt
  prompt=$(<"$template_file")
  prompt="${prompt//\{\{SPEC_PATH\}\}/$spec_path}"
  prompt="${prompt//\{\{MODULE_PATH\}\}/$MODULE_PATH}"
  prompt="${prompt//\{\{TEST_PATH\}\}/$TEST_PATH}"

  echo "$prompt"
}

# ─── Phase 실행 ───
run_phase() {
  local phase_num=$1
  local spec_path=$2
  local end_phase=$3
  local phase_name="${PHASE_NAMES[$phase_num]}"
  local promise="${PHASE_PROMISES[$phase_num]}"
  local max_iter="${PHASE_MAX_ITERATIONS[$phase_num]}"

  echo ""
  echo "${CYAN}════════════════════════════════════════════════════════${NC}"
  echo "${CYAN}  [Phase $phase_num/$end_phase] $phase_name${NC}"
  echo "${CYAN}  Spec: $spec_path${NC}"
  echo "${CYAN}  Promise: $promise | Max iterations: $max_iter${NC}"
  echo "${CYAN}════════════════════════════════════════════════════════${NC}"
  echo ""

  local prompt
  prompt=$(generate_prompt "$phase_num" "$spec_path")

  if $DRY_RUN; then
    local template_file
    template_file=$(find_template "${PHASE_FILES[$phase_num]}" "$CUSTOM_TEMPLATE_DIR")
    echo "${YELLOW}[DRY RUN] 이터레이션: $max_iter${NC}"
    echo "${YELLOW}[DRY RUN] Promise: $promise${NC}"
    echo "${YELLOW}[DRY RUN] 템플릿: $template_file${NC}"
    echo "${YELLOW}[DRY RUN] 프롬프트 (첫 5줄):${NC}"
    echo "$prompt" | head -5
    echo "  ..."
    echo ""
    return 0
  fi

  # Ralph Loop 상태 파일 생성
  mkdir -p "$PROJECT_ROOT/.claude"
  cat > "$RALPH_STATE_FILE" <<EOF
---
active: true
iteration: 1
max_iterations: $max_iter
completion_promise: "$promise"
started_at: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase: $phase_num
phase_name: "$phase_name"
spec_path: "$spec_path"
---

$prompt
EOF

  echo "${GREEN}Ralph Loop 상태 파일 생성 완료.${NC}"
  echo "${GREEN}Claude 세션을 시작합니다...${NC}"
  echo ""

  local phase_start=$SECONDS
  cd "$PROJECT_ROOT"
  claude -p "$prompt" --allowedTools "Bash(docker exec:*)" "Bash(uv run:*)" "Read" "Write" "Edit" "Grep" "Glob" "Task"
  local phase_elapsed=$((SECONDS - phase_start))
  local duration=$(format_duration "$phase_elapsed")

  if [[ -f "$RALPH_STATE_FILE" ]]; then
    local final_iter
    final_iter=$(sed -n '/^---$/,/^---$/{ /^---$/d; p; }' "$RALPH_STATE_FILE" | grep '^iteration:' | sed 's/iteration: *//')
    echo "${YELLOW}[Phase $phase_num/$end_phase] $phase_name: max-iterations ($max_iter) 도달 — ${duration}${NC}"
    notify_mac "rw [Phase $phase_num/$end_phase]" "$phase_name: MAX-ITER ($duration)"
    rm -f "$RALPH_STATE_FILE"
    return 1
  else
    echo "${GREEN}[Phase $phase_num/$end_phase] $phase_name: 완료! — ${duration}${NC}"
    notify_mac "rw [Phase $phase_num/$end_phase]" "$phase_name: PASS ($duration)"
    return 0
  fi
}

# ─── 이터레이션 요약 ───
print_iteration_summary() {
  echo "${BLUE}Phase별 이터레이션:${NC}"
  local total=0
  for phase in {1..8}; do
    local iter="${PHASE_MAX_ITERATIONS[$phase]}"
    total=$((total + iter))
    printf "  Phase %d (%s): %d회\n" "$phase" "${PHASE_NAMES[$phase]}" "$iter"
  done
  echo "  ${BLUE}총 최대: ${total}회${NC}"
}

# ─── 메인 ───
END_PHASE=8
if [[ $SINGLE_PHASE -gt 0 ]]; then
  END_PHASE=$SINGLE_PHASE
fi

for spec_path in "${SPEC_PATHS[@]}"; do
  echo "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
  echo "${CYAN}║         Ralph Workflow - Automated Pipeline         ║${NC}"
  echo "${CYAN}╠══════════════════════════════════════════════════════╣${NC}"
  echo "${CYAN}║  Spec: $spec_path${NC}"
  echo "${CYAN}║  Module: $MODULE_PATH${NC}"
  echo "${CYAN}║  Test: $TEST_PATH${NC}"
  if [[ $CUSTOM_MAX_ITERATIONS -gt 0 ]]; then
    echo "${CYAN}║  Scale: 기본 max=$BASE_MAX → $CUSTOM_MAX_ITERATIONS (비례 스케일링)${NC}"
  fi
  echo "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
  echo ""
  print_iteration_summary

  RESULTS=()
  PHASE_DURATIONS=()
  local workflow_start=$SECONDS
  for phase in $(seq "$START_PHASE" "$END_PHASE"); do
    local ps=$SECONDS
    if run_phase "$phase" "$spec_path" "$END_PHASE"; then
      local dur=$(format_duration $((SECONDS - ps)))
      RESULTS+=("[Phase $phase/$END_PHASE] ${PHASE_NAMES[$phase]}: ${GREEN}PASS${NC} ($dur)")
    else
      local dur=$(format_duration $((SECONDS - ps)))
      RESULTS+=("[Phase $phase/$END_PHASE] ${PHASE_NAMES[$phase]}: ${YELLOW}MAX-ITER${NC} ($dur)")
      echo ""
      echo "${YELLOW}Phase $phase이 max-iterations에 도달했습니다.${NC}"
      echo "${YELLOW}계속 진행하시겠습니까? (y/n)${NC}"
      read -r "continue_choice?"
      if [[ "$continue_choice" != "y" ]]; then
        echo "${RED}워크플로우 중단.${NC}"
        break
      fi
    fi
  done

  local total_duration=$(format_duration $((SECONDS - workflow_start)))
  echo ""
  echo "${CYAN}════════════════════════════════════════════════════════${NC}"
  echo "${CYAN}  워크플로우 결과 요약 — $spec_path${NC}"
  echo "${CYAN}  총 소요 시간: $total_duration${NC}"
  echo "${CYAN}════════════════════════════════════════════════════════${NC}"
  for result in "${RESULTS[@]}"; do
    echo "  $result"
  done
  echo ""
  notify_mac "rw 완료" "$spec_path — $total_duration"
done
