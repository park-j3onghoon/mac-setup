#!/bin/zsh
# Ralph Workflow - Phase 0~9 자동 체이닝 스크립트 (전역)
#
# 사용법:
#   rw -s <session_name> <spec_paths...> [options]
#
# 예시:
#   rw -s pr2-impl docs/spec_detail_2.md -m adscenter/displaycam_partner
#   rw -s big-feature docs/spec_{1..3}.md -m src/app -n 10
#
# 옵션:
#   -s, --session NAME   세션 이름 (필수). 로그/프롬프트 파일 구분에 사용
#   --dry-run            실제 실행 없이 프롬프트만 출력
#   -n, --max-iterations N  Phase별 비례 스케일링 (기본 최대=5 기준)
#   -m, --module PATH    구현 대상 모듈 경로
#   -t, --test PATH      테스트 디렉토리 경로
#   --templates DIR      커스텀 템플릿 디렉토리
#   --init               프로젝트에 rw 에이전트 symlink 설치
#
# 실행 전 체크리스트 (복붙 한번에 실행, 재실행 안전):
#   source scripts/set_dev_env.sh && \
#   docker compose --env-file /dev/null -f compose/py3.yml up -d dynamodb redis testdb && \
#   (docker ps -q -f name="$DEV_CONTAINER" | grep -q . || \
#     docker compose --env-file /dev/null -f compose/py3.yml \
#       run -d --rm --no-deps --name "$DEV_CONTAINER" dev bash -c "sleep infinity")
#
# 초기 설정 (프로젝트당 1회):
#   rw --init                                 # 에이전트 symlink 설치

set -euo pipefail

# ─── 프로세스 정리 ───
CLAUDE_PID=""
cleanup() {
  if [[ -n "$CLAUDE_PID" ]] && kill -0 "$CLAUDE_PID" 2>/dev/null; then
    kill -- -"$CLAUDE_PID" 2>/dev/null || kill "$CLAUDE_PID" 2>/dev/null
    wait "$CLAUDE_PID" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

# ─── 경로 설정 ───
GLOBAL_TEMPLATE_DIR="${0:A:h}"  # 심볼릭 링크 resolve 후 실제 디렉토리
PROJECT_ROOT="$(pwd)"
RALPH_STATE_FILE="$PROJECT_ROOT/.claude/ralph-loop.local.md"

# 세션 파일 기본 디렉토리 (mac-setup 내, 세션 이름은 파싱 후 설정)
SESSIONS_BASE_DIR="$GLOBAL_TEMPLATE_DIR/sessions"

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
  local title="${1//\"/\\\"}"
  local message="${2//\"/\\\"}"
  osascript -e "display notification \"$message\" with title \"$title\" sound name \"Glass\"" 2>/dev/null || true
}

# ─── 입력 검증 ───
validate_path() {
  local value=$1 label=$2
  if [[ -n "${value//[a-zA-Z0-9_.\/\-]/}" ]]; then
    echo "${RED}에러: $label에 허용되지 않는 문자가 포함되어 있습니다: $value${NC}" >&2
    exit 1
  fi
  if [[ "$value" == *..* ]]; then
    echo "${RED}에러: $label에 '..'를 포함할 수 없습니다.${NC}" >&2
    exit 1
  fi
}

# ─── 세션 상태 관리 ───

# spec 경로를 절대 경로로 변환 + 정렬하여 fingerprint 생성
compute_spec_fingerprint() {
  for spec in "$@"; do
    echo "${spec:A}"  # zsh: 절대 경로 + symlink resolve
  done | sort | tr '\n' '|' | sed 's/|$//'
}

save_session_state() {
  local session_status=$1 current_phase=$2
  printf 'SPEC_FINGERPRINT=%s\nCURRENT_PHASE=%s\nSTATUS=%s\n' \
    "$SPEC_FINGERPRINT" "$current_phase" "$session_status" > "$SESSION_DIR/state.env"
}

find_incomplete_session() {
  local dirs=($SESSIONS_BASE_DIR/*(N/))
  [[ ${#dirs[@]} -eq 0 ]] && return 1
  for dir in "${dirs[@]}"; do
    [[ -f "$dir/state.env" ]] || continue
    local fp st ph
    fp=$(grep '^SPEC_FINGERPRINT=' "$dir/state.env" | cut -d= -f2-)
    st=$(grep '^STATUS=' "$dir/state.env" | cut -d= -f2-)
    ph=$(grep '^CURRENT_PHASE=' "$dir/state.env" | cut -d= -f2-)
    if [[ "$fp" == "$SPEC_FINGERPRINT" ]] && [[ "$st" == "in_progress" ]]; then
      echo "$(basename "$dir")|$ph"
      return 0
    fi
  done
  return 1
}

# ─── Phase 설정 ───
typeset -A PHASE_NAMES
PHASE_NAMES=(
  0 "계획"
  1 "구현"
  2 "리뷰+수정"
  3 "구조 개선"
  4 "최종 검증"
  5 "엣지케이스 사냥"
  6 "통합 테스트"
  7 "적대적 리뷰"
  8 "배포 판정"
  9 "커밋"
)

typeset -A PHASE_FILES
PHASE_FILES=(
  0 "phase0-plan.md"
  1 "phase1-implement.md"
  2 "phase2-review-fix.md"
  3 "phase3-structure.md"
  4 "phase4-verify.md"
  5 "phase5-edge-cases.md"
  6 "phase6-integration.md"
  7 "phase7-adversarial.md"
  8 "phase8-deploy-judge.md"
  9 "phase9-commit.md"
)

typeset -A PHASE_PROMISES
PHASE_PROMISES=(
  0 "PLAN DONE"
  1 "IMPL DONE"
  2 "REVIEW DONE"
  3 "REFACTOR DONE"
  4 "VERIFY DONE"
  5 "EDGE DONE"
  6 "INTEGRATION DONE"
  7 "ADVERSARIAL DONE"
  8 "SHIP IT"
  9 "COMMIT DONE"
)

typeset -A PHASE_BASE_ITERATIONS
PHASE_BASE_ITERATIONS=(
  0 3
  1 5
  2 5
  3 3
  4 3
  5 3
  6 3
  7 3
  8 2
  9 1
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
SESSION_NAME=""
START_PHASE=0
DRY_RUN=false
CUSTOM_MAX_ITERATIONS=0
MODULE_PATH=""
TEST_PATH=""
CUSTOM_TEMPLATE_DIR=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --session|-s)
      SESSION_NAME="$2"
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
      count=0
      for agent in "$GLOBAL_TEMPLATE_DIR/agents/"*.md(N); do
        name=$(basename "$agent")
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

# 세션 이름 필수 확인 + path traversal 방지
if [[ -z "$SESSION_NAME" ]]; then
  echo "${RED}에러: --session (-s) 옵션은 필수입니다.${NC}" >&2
  echo "예시: rw -s pr2-impl docs/spec.md -m src/app" >&2
  exit 1
fi

if [[ -n "${SESSION_NAME//[a-zA-Z0-9_-]/}" ]]; then
  echo "${RED}에러: 세션 이름은 영문, 숫자, 하이픈(-), 밑줄(_)만 허용됩니다: $SESSION_NAME${NC}" >&2
  exit 1
fi

# 세션 디렉토리 설정 (세션별 격리, mkdir은 resume 확인 후 수행)
SESSION_DIR="$SESSIONS_BASE_DIR/$SESSION_NAME"

# spec 파일 존재 확인
for spec in "${SPEC_PATHS[@]}"; do
  if [[ ! -f "$spec" ]]; then
    echo "${RED}에러: $spec 파일이 존재하지 않습니다.${NC}" >&2
    exit 1
  fi
done

# spec fingerprint 계산 (절대 경로 정렬)
SPEC_FINGERPRINT=$(compute_spec_fingerprint "${SPEC_PATHS[@]}")

# 기존 미완료 세션 검사 (dry-run 제외)
if ! $DRY_RUN; then
  if incomplete_info=$(find_incomplete_session); then
    IFS='|' read -r OLD_SESSION OLD_PHASE <<< "$incomplete_info"
    echo ""
    echo "${YELLOW}동일 spec의 미완료 세션 발견:${NC}"
    echo "  세션: ${OLD_SESSION}"
    echo "  중단 Phase: ${OLD_PHASE}"
    echo ""
    echo -n "${YELLOW}이어서 하시겠습니까? (yes/no): ${NC}"
    read -r resume_choice
    if [[ "$resume_choice" == "yes" ]]; then
      SESSION_NAME="$OLD_SESSION"
      SESSION_DIR="$SESSIONS_BASE_DIR/$SESSION_NAME"
      START_PHASE="$OLD_PHASE"
      echo "${GREEN}세션 '${SESSION_NAME}' Phase ${START_PHASE}부터 이어서 진행합니다.${NC}"
    elif [[ "$resume_choice" == "no" ]]; then
      rm -rf "$SESSIONS_BASE_DIR/$OLD_SESSION"
      echo "${GREEN}이전 세션 '$OLD_SESSION' 삭제. '$SESSION_NAME'으로 새로 시작합니다.${NC}"
    else
      echo "${RED}취소됨. 'yes' 또는 'no'만 입력 가능합니다.${NC}"
      exit 1
    fi
  fi
fi

# 세션 디렉토리 생성 (resume 후 SESSION_DIR이 확정된 시점)
mkdir -p "$SESSION_DIR"

# START_PHASE 범위 검증
if [[ "$START_PHASE" != [0-9] ]]; then
  echo "${RED}에러: 유효하지 않은 phase 번호입니다: $START_PHASE${NC}" >&2
  exit 1
fi

# DEV_CONTAINER 환경변수 확인 (실제 실행 시 필수)
if ! $DRY_RUN && [[ -z "${DEV_CONTAINER:-}" ]]; then
  echo "${RED}에러: DEV_CONTAINER 환경변수가 설정되지 않았습니다.${NC}" >&2
  echo "먼저 실행: source scripts/set_dev_env.sh" >&2
  exit 1
fi

# ─── MODULE_PATH / TEST_PATH 자동 감지 ───
if [[ -z "$MODULE_PATH" ]]; then
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

# 경로 입력 검증
for spec in "${SPEC_PATHS[@]}"; do
  validate_path "$spec" "spec 경로"
done
validate_path "$MODULE_PATH" "--module"
validate_path "$TEST_PATH" "--test"
if [[ -n "$CUSTOM_TEMPLATE_DIR" ]]; then
  validate_path "$CUSTOM_TEMPLATE_DIR" "--templates"
fi

# ─── 계획 파일 경로 + Phase별 이터레이션 계산 ───
PLAN_PATH="$PROJECT_ROOT/.claude/rw-plan.md"

typeset -A PHASE_MAX_ITERATIONS
for phase in {0..9}; do
  base="${PHASE_BASE_ITERATIONS[$phase]}"
  if [[ $CUSTOM_MAX_ITERATIONS -gt 0 ]]; then
    PHASE_MAX_ITERATIONS[$phase]=$(scale_iterations "$base" "$CUSTOM_MAX_ITERATIONS")
  else
    PHASE_MAX_ITERATIONS[$phase]=$base
  fi
done

# ─── Spec 목록 문자열 생성 ───
SPEC_LIST=""
for spec in "${SPEC_PATHS[@]}"; do
  SPEC_LIST+="- $spec"$'\n'
done
SPEC_LIST="${SPEC_LIST%$'\n'}"  # 마지막 줄바꿈 제거

# ─── 프롬프트 생성 ───
generate_prompt() {
  local phase_num=$1
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
  prompt="${prompt//\{\{SPEC_PATH\}\}/$SPEC_LIST}"
  prompt="${prompt//\{\{MODULE_PATH\}\}/$MODULE_PATH}"
  prompt="${prompt//\{\{TEST_PATH\}\}/$TEST_PATH}"
  prompt="${prompt//\{\{PLAN_PATH\}\}/$PLAN_PATH}"

  echo "$prompt"
}

# ─── Phase 실행 ───
run_phase() {
  local phase_num=$1
  local end_phase=$2
  local phase_name="${PHASE_NAMES[$phase_num]}"
  local promise="${PHASE_PROMISES[$phase_num]}"
  local max_iter="${PHASE_MAX_ITERATIONS[$phase_num]}"

  echo ""
  echo "${CYAN}════════════════════════════════════════════════════════${NC}"
  echo "${CYAN}  [$SESSION_NAME] Phase $phase_num/$end_phase: $phase_name${NC}"
  for spec in "${SPEC_PATHS[@]}"; do
    echo "${CYAN}  Spec: $spec${NC}"
  done
  echo "${CYAN}  Promise: $promise | Max iterations: $max_iter${NC}"
  echo "${CYAN}════════════════════════════════════════════════════════${NC}"
  echo ""

  local prompt
  prompt=$(generate_prompt "$phase_num")

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

  # 프롬프트/로그를 mac-setup 세션 디렉토리에 저장
  cd "$PROJECT_ROOT"
  mkdir -p "$PROJECT_ROOT/.claude"
  local prompt_file="$SESSION_DIR/rw-phase-${phase_num}-prompt.md"
  local log_file="$SESSION_DIR/rw-phase-${phase_num}.log"
  echo "$prompt" > "$prompt_file"

  # 이전 상태 파일 정리
  rm -f "$RALPH_STATE_FILE"

  local phase_start=$SECONDS

  # Claude 세션을 백그라운드로 시작 (script으로 pty 제공 → stop hook 정상 동작)
  script -q "$log_file" claude --dangerously-skip-permissions \
    "/ralph-loop:ralph-loop --max-iterations ${max_iter} --completion-promise '${promise}' Read ${prompt_file} and follow all instructions in it." \
    </dev/null &
  CLAUDE_PID=$!

  echo "${GREEN}  Claude 세션 시작 (PID: $CLAUDE_PID)${NC}"
  echo "${GREEN}  로그: $log_file${NC}"
  echo ""

  # 상태 파일 생성 대기 (최대 60초)
  local wait_count=0
  while [[ ! -f "$RALPH_STATE_FILE" ]]; do
    if ! kill -0 "$CLAUDE_PID" 2>/dev/null; then
      echo "${RED}  Claude 프로세스가 예기치 않게 종료됨.${NC}"
      break
    fi
    sleep 2
    wait_count=$((wait_count + 1))
    if [[ $wait_count -ge 30 ]]; then
      echo "${RED}  Ralph Loop 상태 파일 생성 타임아웃 (60초).${NC}"
      kill -- -"$CLAUDE_PID" 2>/dev/null || kill "$CLAUDE_PID" 2>/dev/null
      wait "$CLAUDE_PID" 2>/dev/null
      rm -f "$prompt_file"
      return 1
    fi
  done

  # 폴링 루프: Ralph Loop 상태 파일 감시
  local poll_interval=5
  local last_iter=0

  while true; do
    # Claude 프로세스 생존 확인
    if ! kill -0 "$CLAUDE_PID" 2>/dev/null; then
      echo ""
      echo "${GREEN}  Claude 세션 종료됨.${NC}"
      break
    fi

    # 상태 파일 확인
    if [[ -f "$RALPH_STATE_FILE" ]]; then
      # 현재 이터레이션 읽기
      local current_iter
      current_iter=$(sed -n '/^---$/,/^---$/{ /^---$/d; p; }' "$RALPH_STATE_FILE" 2>/dev/null | grep '^iteration:' | sed 's/iteration: *//' 2>/dev/null)
      if [[ -n "$current_iter" ]] && [[ "$current_iter" != "$last_iter" ]]; then
        local elapsed=$((SECONDS - phase_start))
        local dur=$(format_duration "$elapsed")
        printf "\r${CYAN}  [%s] Phase %d/%d %s — 이터레이션 %s/%s (%s)${NC}          " \
          "$SESSION_NAME" "$phase_num" "$end_phase" "$phase_name" "$current_iter" "$max_iter" "$dur"
        last_iter="$current_iter"
      fi
    else
      # 상태 파일 삭제됨 = Ralph Loop 완료 (promise 감지 또는 max-iter 도달)
      echo ""
      echo "${GREEN}  Ralph Loop 완료 감지. Claude 세션 종료 중...${NC}"
      kill -- -"$CLAUDE_PID" 2>/dev/null || kill "$CLAUDE_PID" 2>/dev/null
      wait "$CLAUDE_PID" 2>/dev/null
      break
    fi

    sleep "$poll_interval"
  done

  # 정리
  CLAUDE_PID=""
  rm -f "$prompt_file"

  local phase_elapsed=$((SECONDS - phase_start))
  local duration=$(format_duration "$phase_elapsed")

  if [[ -f "$RALPH_STATE_FILE" ]]; then
    rm -f "$RALPH_STATE_FILE"
    echo "${YELLOW}[$SESSION_NAME] Phase $phase_num/$end_phase $phase_name: 중단됨 — ${duration}${NC}"
    notify_mac "rw [$SESSION_NAME]" "Phase $phase_num: $phase_name 중단 ($duration)"
    return 1
  else
    echo "${GREEN}[$SESSION_NAME] Phase $phase_num/$end_phase $phase_name: 완료! — ${duration}${NC}"
    notify_mac "rw [$SESSION_NAME]" "Phase $phase_num: $phase_name PASS ($duration)"
    return 0
  fi
}

# ─── 이터레이션 요약 ───
print_iteration_summary() {
  local start=$1 end=$2
  echo "${BLUE}Phase별 이터레이션:${NC}"
  local total=0
  for phase in $(seq "$start" "$end"); do
    local iter="${PHASE_MAX_ITERATIONS[$phase]}"
    total=$((total + iter))
    printf "  Phase %d (%s): %d회\n" "$phase" "${PHASE_NAMES[$phase]}" "$iter"
  done
  echo "  ${BLUE}총 최대: ${total}회${NC}"
}

# ─── 메인 ───
END_PHASE=9

echo "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo "${CYAN}║         Ralph Workflow - Automated Pipeline         ║${NC}"
echo "${CYAN}╠══════════════════════════════════════════════════════╣${NC}"
echo "${CYAN}║  Session: $SESSION_NAME${NC}"
for spec in "${SPEC_PATHS[@]}"; do
  echo "${CYAN}║  Spec: $spec${NC}"
done
echo "${CYAN}║  Module: $MODULE_PATH${NC}"
echo "${CYAN}║  Test: $TEST_PATH${NC}"
if [[ $CUSTOM_MAX_ITERATIONS -gt 0 ]]; then
  echo "${CYAN}║  Scale: 기본 max=$BASE_MAX → $CUSTOM_MAX_ITERATIONS (비례 스케일링)${NC}"
fi
echo "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
print_iteration_summary "$START_PHASE" "$END_PHASE"

RESULTS=()
WORKFLOW_START=$SECONDS
ALL_DONE=true
for phase in $(seq "$START_PHASE" "$END_PHASE"); do
  # Phase 9 (커밋) 전에 계획 파일 정리 (커밋에 포함 방지)
  if [[ $phase -eq 9 ]]; then
    rm -f "$PLAN_PATH"
  fi
  # 현재 phase 상태 저장
  if ! $DRY_RUN; then
    save_session_state "in_progress" "$phase"
  fi
  PHASE_START_TS=$SECONDS
  if run_phase "$phase" "$END_PHASE"; then
    dur=$(format_duration $((SECONDS - PHASE_START_TS)))
    RESULTS+=("[$SESSION_NAME] Phase $phase/$END_PHASE ${PHASE_NAMES[$phase]}: ${GREEN}PASS${NC} ($dur)")
  else
    dur=$(format_duration $((SECONDS - PHASE_START_TS)))
    RESULTS+=("[$SESSION_NAME] Phase $phase/$END_PHASE ${PHASE_NAMES[$phase]}: ${YELLOW}중단${NC} ($dur)")
    echo ""
    echo "${YELLOW}Phase $phase이 중단되었습니다.${NC}"
    echo "${YELLOW}계속 진행하시겠습니까? (y/n)${NC}"
    read -r "continue_choice?"
    if [[ "$continue_choice" != "y" ]]; then
      echo "${RED}워크플로우 중단.${NC}"
      ALL_DONE=false
      break
    fi
  fi
done

# 전체 완료 시 상태 갱신
if ! $DRY_RUN && $ALL_DONE; then
  save_session_state "completed" "$END_PHASE"
fi

TOTAL_DURATION=$(format_duration $((SECONDS - WORKFLOW_START)))
echo ""
echo "${CYAN}════════════════════════════════════════════════════════${NC}"
echo "${CYAN}  [$SESSION_NAME] 워크플로우 결과 요약 (spec ${#SPEC_PATHS[@]}개)${NC}"
echo "${CYAN}  총 소요 시간: $TOTAL_DURATION${NC}"
echo "${CYAN}════════════════════════════════════════════════════════${NC}"
for result in "${RESULTS[@]}"; do
  echo "  $result"
done
echo ""
notify_mac "rw [$SESSION_NAME] 완료" "spec ${#SPEC_PATHS[@]}개 — $TOTAL_DURATION"
