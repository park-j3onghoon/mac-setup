#!/bin/zsh
# OpenCode Workflow - Dual lane phase runner (impl + review)
#
# Usage:
#   ow -s <session_name> <spec_paths...> [options]
#
# Example:
#   ow -s displaycam-pr4 docs/spec.md docs/spec_detail_4.md -m adscenter/displaycam_partner
#   ow -s displaycam-pr4 docs/spec.md -m src/app --iterations 40
#   ow -s displaycam-pr4 docs/spec.md -m src/app --iterations 120   # capped to 50
#
# Note:
# - Iterations default to 30 when omitted.
# - Iterations are capped at 50.
# - The script prints when default/cap behavior is applied.

set -euo pipefail
setopt typeset_silent

# ---- Colors ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ---- Defaults ----
DEFAULT_IMPL_MODEL="${OPW_IMPL_MODEL:-anthropic/claude-opus-4-1}"
DEFAULT_REVIEW_MODEL="${OPW_REVIEW_MODEL:-openai/gpt-5-codex}"
DEFAULT_IMPL_AGENT="${OPW_IMPL_AGENT:-}"
DEFAULT_REVIEW_AGENT="${OPW_REVIEW_AGENT:-}"
DEFAULT_IMPL_EFFORT="${OPW_IMPL_EFFORT:-high}"
DEFAULT_REVIEW_EFFORT="${OPW_REVIEW_EFFORT:-xhigh}"
DEFAULT_ITERATIONS=30
MAX_ITERATIONS_CAP=50

# ---- Paths ----
GLOBAL_TEMPLATE_DIR="${0:A:h}"
PROJECT_ROOT="$(pwd)"
SESSIONS_BASE_DIR="$GLOBAL_TEMPLATE_DIR/sessions"
LOCAL_TEMPLATE_DIR="$PROJECT_ROOT/scripts/opencode-workflow"
FALLBACK_CODEX_TEMPLATE_DIR="${GLOBAL_TEMPLATE_DIR:h}/codex-workflow"
FALLBACK_RALPH_TEMPLATE_DIR="${GLOBAL_TEMPLATE_DIR:h}/ralph-workflow"

# ---- Runtime ----
EVENT_LOG_FILE=""
ACTIVE_OPENCODE_PID=""

cleanup() {
  if [[ -n "$ACTIVE_OPENCODE_PID" ]] && kill -0 "$ACTIVE_OPENCODE_PID" 2>/dev/null; then
    kill "$ACTIVE_OPENCODE_PID" 2>/dev/null || true
    wait "$ACTIVE_OPENCODE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

usage() {
  cat <<'EOF'
Usage:
  ow -s <session_name> <spec_paths...> [options]

Required:
  -s, --session NAME         Session name
  <spec_paths...>            One or more spec files

Options:
  -m, --module PATH          Target module path (default: .)
  -t, --test PATH            Test path (default: <module>/tests if exists, else <module>)
  -i, --iterations N         Max iterations per phase (default: 30, cap: 50)
  --from N                   Start phase number (default: 0)
  --impl-model MODEL         Impl lane model (provider/model)
  --review-model MODEL       Review lane model (provider/model)
  --impl-agent NAME          Impl lane agent
  --review-agent NAME        Review lane agent
  --impl-effort LEVEL        Impl reasoning hint shown in prompt (default: high)
  --review-effort LEVEL      Review reasoning hint shown in prompt (default: xhigh)
  --templates DIR            Custom template directory
  --dry-run                  Print planned execution only
  -h, --help                 Show this help

Environment overrides:
  OPW_IMPL_MODEL, OPW_REVIEW_MODEL
  OPW_IMPL_AGENT, OPW_REVIEW_AGENT
  OPW_IMPL_EFFORT, OPW_REVIEW_EFFORT
EOF
}

log_event() {
  [[ -z "$EVENT_LOG_FILE" ]] && return
  local level=$1 event=$2 detail=${3:-}
  printf '%s [%s] %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$event" "${detail//$'\n'/ }" >> "$EVENT_LOG_FILE"
}

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

format_tokens() {
  local n=${1:-0}
  printf '%s' "$n" | grep -qE '^[0-9]+$' || { printf '%s\n' "-"; return; }
  [[ $n -le 0 ]] && printf '%s\n' "-" && return
  if [[ $n -ge 1000000 ]]; then
    awk -v n="$n" 'BEGIN{printf "%.1fM\n", n/1000000}'
  elif [[ $n -ge 1000 ]]; then
    awk -v n="$n" 'BEGIN{printf "%.1fk\n", n/1000}'
  else
    printf '%s\n' "$n"
  fi
}

validate_path() {
  local value=$1 label=$2
  if [[ -n "${value//[a-zA-Z0-9_.\/\-]/}" ]]; then
    echo "${RED}에러: ${label}에 허용되지 않는 문자가 포함되어 있습니다: $value${NC}" >&2
    exit 1
  fi
  if [[ "$value" == *..* ]]; then
    echo "${RED}에러: ${label}에 '..'를 포함할 수 없습니다.${NC}" >&2
    exit 1
  fi
}

extract_tokens_from_log() {
  local log_file=$1
  local total=0
  local prev=-1
  local matches
  matches=$(sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$log_file" 2>/dev/null \
    | grep -oE '↓ [0-9.]+[kKmM]? tokens' 2>/dev/null || true)
  if [[ -z "$matches" ]]; then
    matches=$(sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$log_file" 2>/dev/null \
      | grep -oE '[0-9.]+[kKmM]? tokens' 2>/dev/null || true)
  fi
  [[ -z "$matches" ]] && printf '%s\n' 0 && return

  local num_with_suffix num suffix value
  while IFS= read -r line; do
    num_with_suffix=$(printf '%s\n' "$line" | grep -oE '[0-9.]+[kKmM]?' | head -1)
    num=$(printf '%s\n' "$num_with_suffix" | grep -oE '[0-9.]+')
    suffix=$(printf '%s\n' "$num_with_suffix" | grep -oE '[kKmM]$' || true)
    case "$suffix" in
      k|K) value=$(awk -v n="$num" 'BEGIN{printf "%d", n * 1000}') ;;
      m|M) value=$(awk -v n="$num" 'BEGIN{printf "%d", n * 1000000}') ;;
      *)   value=$(awk -v n="$num" 'BEGIN{printf "%d", n}') ;;
    esac

    if (( prev < 0 )); then
      total=$((total + value))
    elif (( value >= prev )); then
      total=$((total + value - prev))
    else
      total=$((total + value))
    fi
    prev=$value
  done <<< "$matches"
  printf '%s\n' "$total"
}

check_promise_in_log() {
  local log_file=$1 promise=$2
  [[ ! -f "$log_file" ]] && return 1
  sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$log_file" 2>/dev/null \
    | grep -Fq "$promise"
}

find_template() {
  local filename=$1
  local custom_dir=$2

  if [[ -n "$custom_dir" ]] && [[ -f "$custom_dir/$filename" ]]; then
    printf '%s\n' "$custom_dir/$filename"
    return
  fi
  if [[ -f "$LOCAL_TEMPLATE_DIR/$filename" ]]; then
    printf '%s\n' "$LOCAL_TEMPLATE_DIR/$filename"
    return
  fi
  if [[ -f "$GLOBAL_TEMPLATE_DIR/$filename" ]]; then
    printf '%s\n' "$GLOBAL_TEMPLATE_DIR/$filename"
    return
  fi
  if [[ -f "$FALLBACK_CODEX_TEMPLATE_DIR/$filename" ]]; then
    printf '%s\n' "$FALLBACK_CODEX_TEMPLATE_DIR/$filename"
    return
  fi
  if [[ -f "$FALLBACK_RALPH_TEMPLATE_DIR/$filename" ]]; then
    printf '%s\n' "$FALLBACK_RALPH_TEMPLATE_DIR/$filename"
    return
  fi
  printf '%s\n' ""
}

# ---- Phase settings ----
typeset -A PHASE_NAMES
PHASE_NAMES=(
  0  "계획 수립"
  1  "계획 검토"
  2  "검토 검증"
  3  "과설계 검토"
  4  "구현"
  5  "스펙 검증"
  6  "버그/보안"
  7  "수정 검증"
  8  "구조 개선"
  9  "통합/재사용"
  10 "사이드이펙트"
  11 "전체 재검토"
  12 "코드 정리"
  13 "코드 품질"
  14 "성능 검토"
  15 "DDD 심층"
  16 "사용자 흐름"
  17 "심층 검토"
  18 "배포 판정"
  19 "커밋"
)

typeset -A PHASE_FILES
PHASE_FILES=(
  0  "phase0-plan.md"
  1  "phase1-plan-review.md"
  2  "phase2-plan-verify.md"
  3  "phase3-yagni.md"
  4  "phase4-implement.md"
  5  "phase5-spec-verify.md"
  6  "phase6-bug-security.md"
  7  "phase7-fix-verify.md"
  8  "phase8-structure.md"
  9  "phase9-integration.md"
  10 "phase10-side-effects.md"
  11 "phase11-full-review.md"
  12 "phase12-cleanup.md"
  13 "phase13-quality.md"
  14 "phase14-performance.md"
  15 "phase15-ddd-review.md"
  16 "phase16-user-flow.md"
  17 "phase17-deep-review.md"
  18 "phase18-deploy-judge.md"
  19 "phase19-commit.md"
)

typeset -A PHASE_PROMISES
PHASE_PROMISES=(
  0  "PLAN DONE"
  1  "PLAN REVIEW DONE"
  2  "PLAN VERIFIED"
  3  "YAGNI DONE"
  4  "IMPL DONE"
  5  "SPEC VERIFIED"
  6  "SECURITY DONE"
  7  "FIXES VERIFIED"
  8  "REFACTOR DONE"
  9  "INTEGRATION DONE"
  10 "SIDEEFFECT DONE"
  11 "FULL REVIEW DONE"
  12 "CLEANUP DONE"
  13 "QUALITY DONE"
  14 "PERF DONE"
  15 "DDD DONE"
  16 "UX DONE"
  17 "DEEP REVIEW DONE"
  18 "SHIP IT"
  19 "COMMIT DONE"
)

# ---- Args ----
SESSION_NAME=""
SPEC_PATHS=()
MODULE_PATH="."
TEST_PATH=""
START_PHASE=0
CUSTOM_TEMPLATE_DIR=""
DRY_RUN=false

ITERATION_INPUT=""
ITERATIONS=$DEFAULT_ITERATIONS
USED_DEFAULT_ITERATIONS=false
CAP_APPLIED=false
USED_CAP_VALUE=false

IMPL_MODEL="$DEFAULT_IMPL_MODEL"
REVIEW_MODEL="$DEFAULT_REVIEW_MODEL"
IMPL_AGENT="$DEFAULT_IMPL_AGENT"
REVIEW_AGENT="$DEFAULT_REVIEW_AGENT"
IMPL_EFFORT="$DEFAULT_IMPL_EFFORT"
REVIEW_EFFORT="$DEFAULT_REVIEW_EFFORT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--session)
      SESSION_NAME="$2"
      shift 2
      ;;
    -m|--module)
      MODULE_PATH="$2"
      shift 2
      ;;
    -t|--test)
      TEST_PATH="$2"
      shift 2
      ;;
    -i|--iterations)
      ITERATION_INPUT="$2"
      shift 2
      ;;
    --from)
      START_PHASE="$2"
      shift 2
      ;;
    --impl-model)
      IMPL_MODEL="$2"
      shift 2
      ;;
    --review-model)
      REVIEW_MODEL="$2"
      shift 2
      ;;
    --impl-agent)
      IMPL_AGENT="$2"
      shift 2
      ;;
    --review-agent)
      REVIEW_AGENT="$2"
      shift 2
      ;;
    --impl-effort)
      IMPL_EFFORT="$2"
      shift 2
      ;;
    --review-effort)
      REVIEW_EFFORT="$2"
      shift 2
      ;;
    --templates)
      CUSTOM_TEMPLATE_DIR="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "${RED}에러: 알 수 없는 옵션: $1${NC}" >&2
      usage
      exit 1
      ;;
    *)
      SPEC_PATHS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$SESSION_NAME" ]]; then
  echo "${RED}에러: --session이 필요합니다.${NC}" >&2
  usage
  exit 1
fi

if [[ ${#SPEC_PATHS[@]} -eq 0 ]]; then
  echo "${RED}에러: spec 파일이 필요합니다.${NC}" >&2
  usage
  exit 1
fi

if ! printf '%s\n' "$START_PHASE" | grep -qE '^[0-9]+$'; then
  echo "${RED}에러: --from 값은 0~19 정수여야 합니다.${NC}" >&2
  exit 1
fi
if (( START_PHASE < 0 || START_PHASE > 19 )); then
  echo "${RED}에러: --from 범위는 0~19 입니다.${NC}" >&2
  exit 1
fi

if [[ -z "$ITERATION_INPUT" ]]; then
  ITERATIONS=$DEFAULT_ITERATIONS
  USED_DEFAULT_ITERATIONS=true
else
  if ! printf '%s\n' "$ITERATION_INPUT" | grep -qE '^[0-9]+$'; then
    echo "${RED}에러: --iterations 값은 양의 정수여야 합니다.${NC}" >&2
    exit 1
  fi
  if (( ITERATION_INPUT < 1 )); then
    echo "${RED}에러: --iterations 값은 1 이상이어야 합니다.${NC}" >&2
    exit 1
  fi
  if (( ITERATION_INPUT > MAX_ITERATIONS_CAP )); then
    ITERATIONS=$MAX_ITERATIONS_CAP
    CAP_APPLIED=true
    USED_CAP_VALUE=true
  else
    ITERATIONS=$ITERATION_INPUT
    if (( ITERATIONS == MAX_ITERATIONS_CAP )); then
      USED_CAP_VALUE=true
    fi
  fi
fi

for spec in "${SPEC_PATHS[@]}"; do
  validate_path "$spec" "spec 경로"
done
validate_path "$MODULE_PATH" "--module"
if [[ -n "$TEST_PATH" ]]; then
  validate_path "$TEST_PATH" "--test"
fi
if [[ -n "$CUSTOM_TEMPLATE_DIR" ]]; then
  validate_path "$CUSTOM_TEMPLATE_DIR" "--templates"
fi

if [[ -z "$TEST_PATH" ]]; then
  if [[ -d "$MODULE_PATH/tests" ]]; then
    TEST_PATH="$MODULE_PATH/tests"
  else
    TEST_PATH="$MODULE_PATH"
  fi
fi

if ! $DRY_RUN; then
  if ! command -v opencode >/dev/null 2>&1; then
    echo "${RED}에러: opencode CLI를 찾을 수 없습니다.${NC}" >&2
    echo "${YELLOW}힌트: opencode 설치 후 다시 실행하세요.${NC}" >&2
    exit 1
  fi
fi

# ---- Session context paths ----
SESSION_DIR="$SESSIONS_BASE_DIR/$SESSION_NAME"
mkdir -p "$SESSION_DIR"
EVENT_LOG_FILE="$SESSION_DIR/ow-events.log"

PLAN_PATH="$PROJECT_ROOT/.claude/ow-plan.md"
CHECKLIST_PATH="$PROJECT_ROOT/.claude/ow-checklist.md"
DIGEST_PATH="$PROJECT_ROOT/.claude/ow-spec-digest.md"
NOTES_PATH="$PROJECT_ROOT/.claude/ow-notes.md"
mkdir -p "$PROJECT_ROOT/.claude"

if [[ ! -f "$NOTES_PATH" ]]; then
  cat > "$NOTES_PATH" <<'EOF'
# OpenCode Workflow Notes

Phase 간 발견 사항/수정 사항을 기록한다.
EOF
fi

SPEC_LINES=$(cat "${SPEC_PATHS[@]}" 2>/dev/null | wc -l | tr -d '[:space:]')

SPEC_LIST=""
for spec in "${SPEC_PATHS[@]}"; do
  SPEC_LIST+="- $spec"$'\n'
done
SPEC_LIST="${SPEC_LIST%$'\n'}"

if $USED_DEFAULT_ITERATIONS; then
  echo "${YELLOW}iteration 미지정: 기본값 ${DEFAULT_ITERATIONS} 사용${NC}"
fi
if $CAP_APPLIED; then
  echo "${YELLOW}iteration 상한 적용: 요청 ${ITERATION_INPUT} → ${MAX_ITERATIONS_CAP}${NC}"
elif $USED_CAP_VALUE; then
  echo "${CYAN}iteration 상한값 사용: ${MAX_ITERATIONS_CAP}${NC}"
fi

echo "${CYAN}OpenCode Workflow 시작: session=${SESSION_NAME}${NC}"
echo "${CYAN}Spec: ${#SPEC_PATHS[@]}개 (${SPEC_LINES}줄), phase=${START_PHASE}~19${NC}"
echo "${CYAN}Iterations/phase: ${ITERATIONS} (default=${DEFAULT_ITERATIONS}, cap=${MAX_ITERATIONS_CAP})${NC}"
echo "${CYAN}Impl lane: model=${IMPL_MODEL}${NC}"
echo "${CYAN}Review lane: model=${REVIEW_MODEL}${NC}"
[[ -n "$IMPL_AGENT" ]] && echo "${CYAN}Impl agent: ${IMPL_AGENT}${NC}"
[[ -n "$REVIEW_AGENT" ]] && echo "${CYAN}Review agent: ${REVIEW_AGENT}${NC}"

printf 'SPEC_FINGERPRINT=%s\nCURRENT_PHASE=%s\nSTATUS=%s\nITERATIONS=%s\n' \
  "$(printf '%s\n' "${SPEC_PATHS[@]}" | sort | tr '\n' '|' | sed 's/|$//')" \
  "$START_PHASE" "in_progress" "$ITERATIONS" > "$SESSION_DIR/state.env"

log_event "INFO" "workflow_start" "session=$SESSION_NAME phase=${START_PHASE}~19 spec_lines=$SPEC_LINES iterations=$ITERATIONS"

generate_prompt() {
  local phase_num=$1 lane=$2 promise=$3 lane_effort=$4
  local template_file
  template_file=$(find_template "${PHASE_FILES[$phase_num]}" "$CUSTOM_TEMPLATE_DIR")
  if [[ -z "$template_file" ]]; then
    echo "${RED}에러: phase 템플릿을 찾을 수 없습니다: ${PHASE_FILES[$phase_num]}${NC}" >&2
    return 1
  fi

  local prompt
  prompt=$(<"$template_file")
  prompt="${prompt//\{\{SPEC_PATH\}\}/$SPEC_LIST}"
  prompt="${prompt//\{\{MODULE_PATH\}\}/$MODULE_PATH}"
  prompt="${prompt//\{\{TEST_PATH\}\}/$TEST_PATH}"
  prompt="${prompt//\{\{PLAN_PATH\}\}/$PLAN_PATH}"
  prompt="${prompt//\{\{CHECKLIST_PATH\}\}/$CHECKLIST_PATH}"
  prompt="${prompt//\{\{DIGEST_PATH\}\}/$DIGEST_PATH}"
  prompt="${prompt//\{\{NOTES_PATH\}\}/$NOTES_PATH}"

  cat <<EOF
You are running inside OpenCode Workflow dual-lane mode.

Lane: ${lane}
Phase: ${phase_num} (${PHASE_NAMES[$phase_num]})
Required completion marker: ${promise}

Rules:
1. Apply changes directly in repository files when implementation/fix is needed.
2. If template asks for unavailable tools, use equivalent commands/actions.
3. Keep outputs concise and include the completion marker only when this phase is complete.
4. Reasoning effort hint: ${lane_effort}

${prompt}
EOF
}

run_lane_once() {
  local phase_num=$1 iter_num=$2 lane=$3 promise=$4
  local lane_model lane_agent lane_effort
  if [[ "$lane" == "impl" ]]; then
    lane_model="$IMPL_MODEL"
    lane_agent="$IMPL_AGENT"
    lane_effort="$IMPL_EFFORT"
  else
    lane_model="$REVIEW_MODEL"
    lane_agent="$REVIEW_AGENT"
    lane_effort="$REVIEW_EFFORT"
  fi

  local prompt_file="$SESSION_DIR/ow-phase-${phase_num}-iter-${iter_num}-${lane}-prompt.md"
  local log_file="$SESSION_DIR/ow-phase-${phase_num}-iter-${iter_num}-${lane}.log"
  local prompt
  prompt=$(generate_prompt "$phase_num" "$lane" "$promise" "$lane_effort")
  printf '%s\n' "$prompt" > "$prompt_file"

  if $DRY_RUN; then
    echo "${YELLOW}[DRY RUN] phase=${phase_num} iter=${iter_num} lane=${lane} model=${lane_model}${NC}"
    echo "${YELLOW}[DRY RUN] prompt: $prompt_file${NC}"
    return 0
  fi

  local -a cmd
  cmd=(opencode run --model "$lane_model" --title "ow:${SESSION_NAME}:p${phase_num}:i${iter_num}:${lane}")
  [[ -n "$lane_agent" ]] && cmd+=(--agent "$lane_agent")
  for spec in "${SPEC_PATHS[@]}"; do
    cmd+=(-f "$spec")
  done
  cmd+=(-f "$prompt_file")

  local message
  if [[ "$lane" == "impl" ]]; then
    message="Implement phase ${phase_num} for this repo. Follow attached prompt first. Use reasoning effort: ${lane_effort}. Emit marker ${promise} only if complete."
  else
    message="Review and fix phase ${phase_num} results from implementation lane. Follow attached prompt first. Use reasoning effort: ${lane_effort}. Emit marker ${promise} only if complete."
  fi

  log_event "INFO" "lane_start" "phase=$phase_num iter=$iter_num lane=$lane model=$lane_model"
  "${cmd[@]}" "$message" > "$log_file" 2>&1 &
  ACTIVE_OPENCODE_PID=$!
  local exit_code=0
  if wait "$ACTIVE_OPENCODE_PID"; then
    exit_code=0
  else
    exit_code=$?
  fi
  ACTIVE_OPENCODE_PID=""

  local tokens
  tokens=$(extract_tokens_from_log "$log_file")
  log_event "INFO" "lane_done" "phase=$phase_num iter=$iter_num lane=$lane exit=$exit_code tokens=$tokens"

  if (( exit_code != 0 )); then
    echo "${YELLOW}⚠ phase ${phase_num} iter ${iter_num} lane ${lane} 실패 (exit=${exit_code})${NC}"
    return 1
  fi
  return 0
}

# ---- Stats ----
typeset -A PHASE_DURATIONS
typeset -A PHASE_TOKENS
typeset -A PHASE_ITER_USED
typeset -A PHASE_EXIT_REASON
COMPLETED_PHASES=()
EXTENDED_PHASES=()

WORKFLOW_START=$SECONDS
END_PHASE=19

for phase in $(seq "$START_PHASE" "$END_PHASE"); do
  phase_name="${PHASE_NAMES[$phase]}"
  promise="${PHASE_PROMISES[$phase]}"
  phase_start=$SECONDS
  phase_tokens=0
  phase_reason="max-iterations"
  phase_done=false
  no_change_streak=0

  echo ""
  echo "${CYAN}▶ Phase $phase/$END_PHASE: $phase_name (max ${ITERATIONS}회)${NC}"
  log_event "INFO" "phase_start" "phase=$phase name=$phase_name max_iter=$ITERATIONS"
  printf 'SPEC_FINGERPRINT=%s\nCURRENT_PHASE=%s\nSTATUS=%s\nITERATIONS=%s\n' \
    "$(printf '%s\n' "${SPEC_PATHS[@]}" | sort | tr '\n' '|' | sed 's/|$//')" \
    "$phase" "in_progress" "$ITERATIONS" > "$SESSION_DIR/state.env"

  for iter in $(seq 1 "$ITERATIONS"); do
    before_changes=$(git status --porcelain 2>/dev/null | wc -l | tr -d '[:space:]')

    run_lane_once "$phase" "$iter" "impl" "$promise" || true
    run_lane_once "$phase" "$iter" "review" "$promise" || true

    if ! $DRY_RUN; then
      impl_log="$SESSION_DIR/ow-phase-${phase}-iter-${iter}-impl.log"
      review_log="$SESSION_DIR/ow-phase-${phase}-iter-${iter}-review.log"
      iter_tokens=0
      [[ -f "$impl_log" ]] && iter_tokens=$((iter_tokens + $(extract_tokens_from_log "$impl_log")))
      [[ -f "$review_log" ]] && iter_tokens=$((iter_tokens + $(extract_tokens_from_log "$review_log")))
      phase_tokens=$((phase_tokens + iter_tokens))

      if check_promise_in_log "$impl_log" "$promise" || check_promise_in_log "$review_log" "$promise"; then
        phase_done=true
        phase_reason="promise"
        PHASE_ITER_USED[$phase]=$iter
        break
      fi
    else
      phase_done=true
      phase_reason="dry-run"
      PHASE_ITER_USED[$phase]=1
      break
    fi

    after_changes=$(git status --porcelain 2>/dev/null | wc -l | tr -d '[:space:]')
    if [[ "$after_changes" == "$before_changes" ]]; then
      no_change_streak=$((no_change_streak + 1))
    else
      no_change_streak=0
    fi

    if (( no_change_streak >= 2 )); then
      phase_reason="no-change-streak"
      PHASE_ITER_USED[$phase]=$iter
      break
    fi
  done

  if [[ -z "${PHASE_ITER_USED[$phase]:-}" ]]; then
    PHASE_ITER_USED[$phase]=$ITERATIONS
  fi

  phase_elapsed=$((SECONDS - phase_start))
  PHASE_DURATIONS[$phase]=$phase_elapsed
  PHASE_TOKENS[$phase]=$phase_tokens
  PHASE_EXIT_REASON[$phase]="$phase_reason"

  dur_fmt=$(format_duration "$phase_elapsed")
  tok_fmt=$(format_tokens "$phase_tokens")

  if $phase_done; then
    COMPLETED_PHASES+=("$phase")
    echo "${GREEN}✔ Phase $phase $phase_name 완료 (${dur_fmt}, iter ${PHASE_ITER_USED[$phase]}/${ITERATIONS}, ↓ ${tok_fmt}, ${phase_reason})${NC}"
    log_event "INFO" "phase_done" "phase=$phase iter=${PHASE_ITER_USED[$phase]} tokens=$phase_tokens reason=$phase_reason"
  else
    EXTENDED_PHASES+=("$phase")
    echo "${YELLOW}⚠ Phase $phase $phase_name marker 미감지 (${dur_fmt}, iter ${PHASE_ITER_USED[$phase]}/${ITERATIONS}, ↓ ${tok_fmt}, ${phase_reason})${NC}"
    log_event "WARN" "phase_force_proceed" "phase=$phase iter=${PHASE_ITER_USED[$phase]} tokens=$phase_tokens reason=$phase_reason"
  fi
done

TOTAL_ELAPSED=$((SECONDS - WORKFLOW_START))
TOTAL_TOKENS=0
for phase in {0..19}; do
  TOTAL_TOKENS=$((TOTAL_TOKENS + ${PHASE_TOKENS[$phase]:-0}))
done

TOTAL_DUR=$(format_duration "$TOTAL_ELAPSED")
TOTAL_TOKENS_FMT=$(format_tokens "$TOTAL_TOKENS")

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  OpenCode Workflow 실행 요약  [$SESSION_NAME]"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Spec: ${SPEC_LINES}줄, Iterations/phase: ${ITERATIONS} (default=${DEFAULT_ITERATIONS}, cap=${MAX_ITERATIONS_CAP})"
echo "  Impl: ${IMPL_MODEL} ${IMPL_AGENT:+(agent=$IMPL_AGENT)}"
echo "  Review: ${REVIEW_MODEL} ${REVIEW_AGENT:+(agent=$REVIEW_AGENT)}"
echo ""

for phase in $(seq "$START_PHASE" "$END_PHASE"); do
  [[ -n "${PHASE_DURATIONS[$phase]:-}" ]] || continue
  name="${PHASE_NAMES[$phase]}"
  dur=$(format_duration "${PHASE_DURATIONS[$phase]}")
  tok=$(format_tokens "${PHASE_TOKENS[$phase]}")
  it="${PHASE_ITER_USED[$phase]:-0}"
  rsn="${PHASE_EXIT_REASON[$phase]:-unknown}"
  printf "  Phase %2d %-14s —  %10s  —  iter %2s/%2s  —  ↓ %6s  —  %s\n" \
    "$phase" "$name" "$dur" "$it" "$ITERATIONS" "$tok" "$rsn"
done

echo "  ─────────────────────────────────────────────────────"
printf "  TOTAL                   —  %10s  —  ↓ %6s\n" "$TOTAL_DUR" "$TOTAL_TOKENS_FMT"

if [[ ${#EXTENDED_PHASES[@]} -gt 0 ]]; then
  echo ""
  echo "  ${YELLOW}⚠ marker 미감지/강제 진행 phase: ${EXTENDED_PHASES[*]}${NC}"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

printf 'SPEC_FINGERPRINT=%s\nCURRENT_PHASE=%s\nSTATUS=%s\nITERATIONS=%s\n' \
  "$(printf '%s\n' "${SPEC_PATHS[@]}" | sort | tr '\n' '|' | sed 's/|$//')" \
  "$END_PHASE" "completed" "$ITERATIONS" > "$SESSION_DIR/state.env"
log_event "INFO" "workflow_end" "session=$SESSION_NAME duration=$TOTAL_DUR tokens=$TOTAL_TOKENS completed=${#COMPLETED_PHASES[@]}"
