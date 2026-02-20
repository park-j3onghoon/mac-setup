#!/bin/zsh
# Ralph Workflow - Phase 0~19 자동 체이닝 스크립트 (전역)
#
# 사용법:
#   rw -s <session_name> <spec_paths...> [options]
#
# 예시:
#   rw -s pr2-impl docs/spec_detail_2.md -m adscenter/displaycam_partner
#   rw -s big-feature docs/spec_{1..3}.md -m src/app -n 2
#
# 옵션:
#   -s, --session NAME   세션 이름 (필수). 로그/프롬프트 파일 구분에 사용
#   --dry-run            실제 실행 없이 프롬프트만 출력
#   -n, --multiplier N   이터레이션 배수 (기본 1, float 허용. 예: -n 2, -n 0.5)
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
  # 상태 파일 정리 (다음 실행 시 오판 방지)
  rm -f "$RALPH_STATE_FILE" 2>/dev/null
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

extract_tokens_from_log() {
  local log_file=$1
  local total=0
  # ANSI escape + \r 제거 후 ↓ Xk tokens 패턴 매칭
  local matches
  matches=$(sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$log_file" 2>/dev/null \
    | grep -oE '↓ [0-9.]+[kKmM]? tokens' 2>/dev/null || true)
  [[ -z "$matches" ]] && printf '%s\n' 0 && return
  local num_with_suffix num suffix
  while IFS= read -r line; do
    # "↓ " 와 " tokens" 사이의 숫자+접미사만 추출 (tokens의 k 오매칭 방지)
    num_with_suffix=$(printf '%s\n' "$line" | grep -oE '[0-9.]+[kKmM]?' | head -1)
    num=$(printf '%s\n' "$num_with_suffix" | grep -oE '[0-9.]+')
    suffix=$(printf '%s\n' "$num_with_suffix" | grep -oE '[kKmM]$')
    case "$suffix" in
      k|K) total=$(awk -v t="$total" -v n="$num" 'BEGIN{printf "%d", t + n * 1000}') ;;
      m|M) total=$(awk -v t="$total" -v n="$num" 'BEGIN{printf "%d", t + n * 1000000}') ;;
      *)   total=$(awk -v t="$total" -v n="$num" 'BEGIN{printf "%d", t + n}') ;;
    esac
  done <<< "$matches"
  printf '%s\n' "$total"
}

# ─── 알림 시스템 ───
NOTIFY_BACKEND="mac"  # 향후: "kakao", "sms", "slack"

notify_info() {   # 자동 소멸 (heartbeat용)
  _notify_dispatch "info" "$1" "$2"
}
notify_alert() {  # 닫을 때까지 유지 (phase 시작/끝)
  _notify_dispatch "alert" "$1" "$2"
}
_notify_dispatch() {
  local level=$1
  local title="${2//\"/\\\"}"
  local message="${3//\"/\\\"}"
  case "$NOTIFY_BACKEND" in
    mac)
      if [[ "$level" == "alert" ]]; then
        osascript -e "display alert \"$title\" message \"$message\" as informational" 2>/dev/null &
      else
        osascript -e "display notification \"$message\" with title \"$title\" sound name \"Glass\"" 2>/dev/null || true
      fi ;;
    *) printf '[%s] %s: %s\n' "$level" "$title" "$message" ;;
  esac
}

# ─── 입력 검증 ───
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

# ─── 세션 상태 관리 ───

# spec 경로를 절대 경로로 변환 + 정렬하여 fingerprint 생성
compute_spec_fingerprint() {
  for spec in "$@"; do
    printf '%s\n' "${spec:A}"  # zsh: 절대 경로 + symlink resolve
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
      printf '%s\n' "$(basename "$dir")|$ph"
      return 0
    fi
  done
  return 1
}

# ─── Spec 크기 분석 ───
compute_spec_lines() {
  cat "${SPEC_PATHS[@]}" 2>/dev/null | wc -l | tr -d '[:space:]'
}

# spec 줄 수에 따른 이터레이션 추가분 (300줄마다 +1)
compute_spec_addend() {
  local lines=$1
  printf '%s\n' $(( lines / 300 ))
}

# ─── 메인 브랜치 자동 감지 ───
detect_main_branch() {
  if git show-ref --verify --quiet refs/heads/main 2>/dev/null; then
    printf '%s\n' "main"
  elif git show-ref --verify --quiet refs/heads/master 2>/dev/null; then
    printf '%s\n' "master"
  else
    printf '%s\n' "HEAD"
  fi
}

# ─── Phase 설정 (0~19) ───
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

typeset -A PHASE_BASE_ITERATIONS
PHASE_BASE_ITERATIONS=(
  0  3
  1  1
  2  1
  3  1
  4  5
  5  2
  6  2
  7  1
  8  2
  9  1
  10 1
  11 2
  12 1
  13 1
  14 1
  15 1
  16 1
  17 2
  18 1
  19 1
)

# ─── 이터레이션 계산: ceil((base + spec_addend) × multiplier) ───
compute_iterations() {
  local base=$1 multiplier=$2 addend=$3
  awk -v b="$base" -v m="$multiplier" -v a="$addend" 'BEGIN{
    v = (b + a) * m; printf "%d", (v == int(v)) ? v : int(v) + 1
  }'
}

# Phase별 최대 재시도 횟수 = iterations × 3
compute_max_retries() {
  local iterations=$1
  printf '%s\n' $(( iterations * 3 ))
}

# ─── 템플릿 파일 탐색 (로컬 우선 → 글로벌 폴백) ───
find_template() {
  local filename=$1
  local custom_dir=$2

  # 1. 커스텀 디렉토리 (--templates 옵션)
  if [[ -n "$custom_dir" ]] && [[ -f "$custom_dir/$filename" ]]; then
    printf '%s\n' "$custom_dir/$filename"
    return
  fi

  # 2. 프로젝트 로컬
  if [[ -f "$LOCAL_TEMPLATE_DIR/$filename" ]]; then
    printf '%s\n' "$LOCAL_TEMPLATE_DIR/$filename"
    return
  fi

  # 3. 글로벌 기본
  if [[ -f "$GLOBAL_TEMPLATE_DIR/$filename" ]]; then
    printf '%s\n' "$GLOBAL_TEMPLATE_DIR/$filename"
    return
  fi

  printf '%s\n' ""
}

# ─── Promise 검증 ───
check_promise_in_log() {
  local log_file=$1 promise=$2
  # ANSI escape 제거 후 promise 문자열 검색
  sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$log_file" 2>/dev/null \
    | grep -qF "$promise" 2>/dev/null
}

# ─── 인자 파싱 ───
SPEC_PATHS=()
SESSION_NAME=""
START_PHASE=0
DRY_RUN=false
N_MULTIPLIER="1"
MODULE_PATH=""
TEST_PATH=""
CUSTOM_TEMPLATE_DIR=""
# MAX_PHASE_RETRIES는 Phase별 iterations × 3으로 동적 계산 (compute_max_retries 함수 참조)

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
    --multiplier|-n)
      N_MULTIPLIER="$2"
      if ! printf '%s' "$N_MULTIPLIER" | grep -qE '^[0-9]+\.?[0-9]*$'; then
        echo "${RED}에러: -n 값은 양수 숫자여야 합니다: $N_MULTIPLIER${NC}" >&2
        exit 1
      fi
      # 0 또는 0.0 방지
      if awk -v n="$N_MULTIPLIER" 'BEGIN{exit (n > 0) ? 0 : 1}'; then :; else
        echo "${RED}에러: -n 값은 0보다 커야 합니다: $N_MULTIPLIER${NC}" >&2
        exit 1
      fi
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
    echo -n "미완료 세션 발견 (${OLD_SESSION}, Phase ${OLD_PHASE}). 이어서? (yes/no): "
    read -r resume_choice
    if [[ "$resume_choice" == "yes" ]]; then
      SESSION_NAME="$OLD_SESSION"
      SESSION_DIR="$SESSIONS_BASE_DIR/$SESSION_NAME"
      START_PHASE="$OLD_PHASE"
    elif [[ "$resume_choice" == "no" ]]; then
      [[ -n "$OLD_SESSION" ]] && rm -rf "$SESSIONS_BASE_DIR/$OLD_SESSION"
    else
      echo "${RED}취소됨. 'yes' 또는 'no'만 입력 가능합니다.${NC}" >&2
      exit 1
    fi
  fi
fi

# 세션 디렉토리 생성 (resume 후 SESSION_DIR이 확정된 시점)
mkdir -p "$SESSION_DIR"

# START_PHASE 범위 검증 (0~19)
if ! printf '%s' "$START_PHASE" | grep -qE '^[0-9]+$' || [[ "$START_PHASE" -gt 19 ]]; then
  echo "${RED}에러: 유효하지 않은 phase 번호입니다: $START_PHASE (0~19 범위)${NC}" >&2
  exit 1
fi

# DEV_CONTAINER 환경변수 확인 (없으면 자동 source)
if ! $DRY_RUN && [[ -z "${DEV_CONTAINER:-}" ]]; then
  if [[ -f "$PROJECT_ROOT/scripts/set_dev_env.sh" ]]; then
    source "$PROJECT_ROOT/scripts/set_dev_env.sh" >/dev/null 2>&1
  else
    echo "${RED}에러: DEV_CONTAINER 환경변수가 설정되지 않았고, scripts/set_dev_env.sh도 없습니다.${NC}" >&2
    exit 1
  fi
fi

# ─── MODULE_PATH / TEST_PATH 자동 감지 ───
if [[ -z "$MODULE_PATH" ]]; then
  MODULE_PATH="."
  notify_info "rw 경고" "--module 미지정. 기본값 '.' 사용."
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

# ─── Spec 크기 분석 + Phase별 이터레이션 계산 ───
PLAN_PATH="$PROJECT_ROOT/.claude/rw-plan.md"
CHECKLIST_PATH="$PROJECT_ROOT/.claude/rw-checklist.md"
DIGEST_PATH="$PROJECT_ROOT/.claude/rw-spec-digest.md"
NOTES_PATH="$PROJECT_ROOT/.claude/rw-notes.md"

SPEC_LINES=$(compute_spec_lines)
SPEC_ADDEND=$(compute_spec_addend "$SPEC_LINES")
MAIN_BRANCH=$(detect_main_branch)

typeset -A PHASE_MAX_ITERATIONS
for phase in {0..19}; do
  base="${PHASE_BASE_ITERATIONS[$phase]}"
  PHASE_MAX_ITERATIONS[$phase]=$(compute_iterations "$base" "$N_MULTIPLIER" "$SPEC_ADDEND")
done

# ─── Spec 목록 문자열 생성 ───
SPEC_LIST=""
for spec in "${SPEC_PATHS[@]}"; do
  SPEC_LIST+="- $spec"$'\n'
done
SPEC_LIST="${SPEC_LIST%$'\n'}"  # 마지막 줄바꿈 제거

# ─── Phase별 통계 추적 ───
typeset -A PHASE_DURATIONS   # phase_num → seconds (누적)
typeset -A PHASE_TOKENS      # phase_num → token count (누적)
typeset -A PHASE_RETRIES     # phase_num → retry count
COMPLETED_PHASES=()
EXTENDED_PHASES=()           # promise 미감지로 강제 진행된 phase 목록

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
  prompt="${prompt//\{\{CHECKLIST_PATH\}\}/$CHECKLIST_PATH}"
  prompt="${prompt//\{\{DIGEST_PATH\}\}/$DIGEST_PATH}"
  prompt="${prompt//\{\{NOTES_PATH\}\}/$NOTES_PATH}"

  printf '%s\n' "$prompt"
}

# ─── Phase 실행 ───
run_phase() {
  local phase_num=$1
  local end_phase=$2
  local run_suffix="${3:-}"  # 재시도 시: "-retry-1", "-retry-2" 등
  local phase_name="${PHASE_NAMES[$phase_num]}"
  local promise="${PHASE_PROMISES[$phase_num]}"
  local max_iter="${PHASE_MAX_ITERATIONS[$phase_num]}"

  local retry_label=""
  [[ -n "$run_suffix" ]] && retry_label=" (재시도)"

  notify_alert "rw [$SESSION_NAME]" "Phase $phase_num/$end_phase: $phase_name 시작${retry_label} (max ${max_iter}회)"

  local prompt
  prompt=$(generate_prompt "$phase_num")

  if $DRY_RUN; then
    local template_file
    template_file=$(find_template "${PHASE_FILES[$phase_num]}" "$CUSTOM_TEMPLATE_DIR")
    echo "${YELLOW}[DRY RUN] 이터레이션: $max_iter (base=${PHASE_BASE_ITERATIONS[$phase_num]} + ${SPEC_ADDEND}, ×${N_MULTIPLIER})${NC}"
    echo "${YELLOW}[DRY RUN] Promise: $promise${NC}"
    echo "${YELLOW}[DRY RUN] 템플릿: $template_file${NC}"
    echo "${YELLOW}[DRY RUN] 프롬프트 (첫 5줄):${NC}"
    printf '%s\n' "$prompt" | head -5
    echo "  ..."
    echo ""
    return 0
  fi

  # 프롬프트/로그를 mac-setup 세션 디렉토리에 저장
  cd "$PROJECT_ROOT"
  mkdir -p "$PROJECT_ROOT/.claude"
  local prompt_file="$SESSION_DIR/rw-phase-${phase_num}${run_suffix}-prompt.md"
  local log_file="$SESSION_DIR/rw-phase-${phase_num}${run_suffix}.log"
  printf '%s\n' "$prompt" > "$prompt_file"

  # 이전 상태 파일 정리
  rm -f "$RALPH_STATE_FILE"

  local phase_start=$SECONDS

  # Claude 세션을 백그라운드로 시작 (script으로 pty 제공 → stop hook 정상 동작)
  # >/dev/null 2>&1: script의 터미널 미러링 출력 억제 (로그 파일에만 기록)
  script -q "$log_file" claude --dangerously-skip-permissions \
    "/ralph-loop:ralph-loop --max-iterations ${max_iter} --completion-promise '${promise}' Read ${prompt_file} and follow all instructions in it." \
    </dev/null >/dev/null 2>&1 &
  CLAUDE_PID=$!

  # 상태 파일 생성 대기 (최대 60초)
  local wait_count=0
  local state_file_seen=false
  local init_spin_chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  local init_spin_idx=0
  while [[ ! -f "$RALPH_STATE_FILE" ]]; do
    if ! kill -0 "$CLAUDE_PID" 2>/dev/null; then
      printf "\r\033[K"
      notify_alert "rw [$SESSION_NAME] 에러" "Claude 프로세스가 예기치 않게 종료됨"
      break
    fi
    local isc="${init_spin_chars:$((init_spin_idx % ${#init_spin_chars})):1}"
    init_spin_idx=$((init_spin_idx + 1))
    printf "\r${CYAN}%s Phase %d/%d %s — Claude 시작 중...${NC}  " \
      "$isc" "$phase_num" "$end_phase" "$phase_name"
    sleep 2
    wait_count=$((wait_count + 1))
    if [[ $wait_count -ge 30 ]]; then
      printf "\r\033[K"
      notify_alert "rw [$SESSION_NAME] 에러" "Ralph Loop 상태 파일 생성 타임아웃 (60초)"
      kill -- -"$CLAUDE_PID" 2>/dev/null || kill "$CLAUDE_PID" 2>/dev/null
      wait "$CLAUDE_PID" 2>/dev/null
      rm -f "$prompt_file"
      return 1
    fi
  done
  printf "\r\033[K"

  # 상태 파일이 한 번이라도 생성되었는지 기록
  [[ -f "$RALPH_STATE_FILE" ]] && state_file_seen=true

  # 폴링 루프: Ralph Loop 상태 파일 감시
  local poll_interval=5
  local last_iter=0
  local current_iter=""
  local spin_chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  local spin_idx=0
  local last_heartbeat=$SECONDS

  while true; do
    # Claude 프로세스 생존 확인
    if ! kill -0 "$CLAUDE_PID" 2>/dev/null; then
      printf "\r\033[K"
      break
    fi

    # 상태 파일 확인
    if [[ -f "$RALPH_STATE_FILE" ]]; then
      state_file_seen=true
      # 현재 이터레이션 읽기
      current_iter=$(sed -n '/^---$/,/^---$/{ /^---$/d; p; }' "$RALPH_STATE_FILE" 2>/dev/null | grep '^iteration:' | sed 's/iteration: *//' 2>/dev/null)
      if [[ -n "$current_iter" ]] && [[ "$current_iter" != "$last_iter" ]]; then
        last_iter="$current_iter"
      fi

      # 스피너 출력
      local elapsed=$((SECONDS - phase_start))
      local dur=$(format_duration "$elapsed")
      local sc="${spin_chars:$((spin_idx % ${#spin_chars})):1}"
      spin_idx=$((spin_idx + 1))
      printf "\r${CYAN}%s Phase %d/%d %s — iter %s/%s (%s)${retry_label}${NC}  " \
        "$sc" "$phase_num" "$end_phase" "$phase_name" "${last_iter:-0}" "$max_iter" "$dur"

      # 10분 heartbeat 알림
      if (( SECONDS - last_heartbeat >= 600 )); then
        notify_info "rw [$SESSION_NAME]" "Phase $phase_num 진행 중 ($dur)${retry_label}"
        last_heartbeat=$SECONDS
      fi
    else
      # 상태 파일 삭제됨 = Ralph Loop 완료 (promise 감지 또는 max-iter 도달)
      printf "\r\033[K"
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

  # 토큰 사용량 추출
  local tokens=0
  if [[ -f "$log_file" ]]; then
    tokens=$(extract_tokens_from_log "$log_file")
  fi
  local tokens_fmt=$(format_tokens "$tokens")

  # 통계 누적 (재시도 시 기존 값에 더함)
  PHASE_DURATIONS[$phase_num]=$((${PHASE_DURATIONS[$phase_num]:-0} + phase_elapsed))
  PHASE_TOKENS[$phase_num]=$((${PHASE_TOKENS[$phase_num]:-0} + tokens))

  if [[ -f "$RALPH_STATE_FILE" ]]; then
    # 상태 파일이 남아 있음 = 실행 중 중단됨
    rm -f "$RALPH_STATE_FILE"
    echo "${RED}✘ Phase $phase_num $phase_name — $duration — ↓ $tokens_fmt${retry_label}${NC}"
    notify_alert "rw [$SESSION_NAME]" "Phase $phase_num/$end_phase $phase_name: 중단 ($duration, ↓ $tokens_fmt)"
    return 1
  elif ! $state_file_seen; then
    # 상태 파일이 한 번도 생성되지 않음 = 프로세스 조기 사망
    echo "${RED}✘ Phase $phase_num $phase_name — $duration — ↓ $tokens_fmt (프로세스 조기 종료)${NC}"
    notify_alert "rw [$SESSION_NAME]" "Phase $phase_num/$end_phase $phase_name: 실패 — 프로세스 시작 안 됨"
    return 1
  else
    # 상태 파일 생성 후 삭제됨 = 실행 완료 (promise 여부는 메인 루프에서 확인)
    echo "${GREEN}✔ Phase $phase_num $phase_name — $duration — ↓ $tokens_fmt${retry_label}${NC}"
    return 0
  fi
}

# ─── 토큰 합산 ───
compute_total_tokens() {
  local total=0
  for phase in "${COMPLETED_PHASES[@]}"; do
    total=$((total + ${PHASE_TOKENS[$phase]:-0}))
  done
  printf '%s\n' "$total"
}

# ─── 코드 통계 ───
compute_code_stats() {
  local base_ref stat_line
  base_ref=$(git merge-base HEAD "$MAIN_BRANCH" 2>/dev/null || printf '%s\n' "HEAD~1")
  stat_line=$(git diff --stat "$base_ref" 2>/dev/null | tail -1)
  FILES_CHANGED=$(printf '%s\n' "$stat_line" | grep -oE '[0-9]+ file' | grep -oE '[0-9]+')
  LINES_ADDED=$(printf '%s\n' "$stat_line" | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+')
  LINES_DELETED=$(printf '%s\n' "$stat_line" | grep -oE '[0-9]+ deletion' | grep -oE '[0-9]+')
  FILES_CHANGED=${FILES_CHANGED:-0}
  LINES_ADDED=${LINES_ADDED:-0}
  LINES_DELETED=${LINES_DELETED:-0}
}

# ─── 실행 요약 ───
print_summary() {
  local total_seconds=$1
  local total_dur=$(format_duration "$total_seconds")
  local total_tokens
  total_tokens=$(compute_total_tokens)
  local total_tokens_fmt=$(format_tokens "$total_tokens")

  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  Ralph Workflow 실행 요약  [$SESSION_NAME]"
  echo "═══════════════════════════════════════════════════════════"
  echo ""
  echo "  Spec: ${SPEC_LINES}줄, +${SPEC_ADDEND}/phase (300줄당 +1), multiplier: ×${N_MULTIPLIER}"
  echo ""

  for phase in "${COMPLETED_PHASES[@]}"; do
    local name="${PHASE_NAMES[$phase]}"
    local dur=$(format_duration "${PHASE_DURATIONS[$phase]:-0}")
    local tok=$(format_tokens "${PHASE_TOKENS[$phase]:-0}")
    local retry_info=""
    local retries=${PHASE_RETRIES[$phase]:-0}
    if (( retries > 0 )); then
      retry_info=" (재시도 ${retries}회)"
    fi
    printf "  Phase %2d %-14s —  %10s  —  ↓ %6s%s\n" "$phase" "$name" "$dur" "$tok" "$retry_info"
  done

  echo "  ─────────────────────────────────────────────────────"
  printf "  TOTAL    %-14s —  %10s  —  ↓ %6s\n" "" "$total_dur" "$total_tokens_fmt"

  # 코드 통계 (커밋이 있는 경우)
  compute_code_stats
  if [[ "$FILES_CHANGED" -gt 0 ]] 2>/dev/null; then
    printf "  코드: %s files changed, +%s -%s\n" "$FILES_CHANGED" "$LINES_ADDED" "$LINES_DELETED"
  fi

  # promise 미감지 경고
  if [[ ${#EXTENDED_PHASES[@]} -gt 0 ]]; then
    echo ""
    echo "  ${YELLOW}⚠ Promise 미감지 phase: ${EXTENDED_PHASES[*]}${NC}"
    echo "    (max-iter 도달 후 iterations×3회 재시도에도 promise 미출력)"
  fi

  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo ""
}

# ─── 메인 ───
END_PHASE=19

# 메모 파일 초기화 (워크플로우 시작 시, 기존 내용 유지하거나 새로 생성)
if [[ "$START_PHASE" -eq 0 ]] && [[ ! -f "$NOTES_PATH" ]]; then
  mkdir -p "$(dirname "$NOTES_PATH")"
  cat > "$NOTES_PATH" << 'NOTES_EOF'
# Phase 간 공유 메모

이전 Phase에서 발견/수정한 사항을 기록한다. 후속 Phase에서 참조한다.

**기록 형식**: `[Phase N] [심각도] [파일:라인] 설명` (예: `[Phase 6] [HIGH] auth/services.py:45 SQL injection 수정`)

---

NOTES_EOF
fi

notify_alert "rw [$SESSION_NAME] 시작" "Phase ${START_PHASE}~${END_PHASE}, spec ${#SPEC_PATHS[@]}개 (${SPEC_LINES}줄, +${SPEC_ADDEND}/phase)"

WORKFLOW_START=$SECONDS
ALL_DONE=true
for phase in $(seq "$START_PHASE" "$END_PHASE"); do
  # 현재 phase 상태 저장
  if ! $DRY_RUN; then
    save_session_state "in_progress" "$phase"
  fi

  retry=0
  phase_success=false
  max_retries=$(compute_max_retries "${PHASE_MAX_ITERATIONS[$phase]}")

  while true; do
    run_suffix=""
    if (( retry > 0 )); then
      run_suffix="-retry-${retry}"
    fi

    if run_phase "$phase" "$END_PHASE" "$run_suffix"; then
      # Phase 실행 완료 — promise 검증
      log_file="$SESSION_DIR/rw-phase-${phase}${run_suffix}.log"
      promise="${PHASE_PROMISES[$phase]}"

      if $DRY_RUN || check_promise_in_log "$log_file" "$promise"; then
        # promise 확인됨 → 성공
        phase_success=true
        PHASE_RETRIES[$phase]=$retry
        break
      else
        # promise 미감지 → max-iter 도달
        retry=$((retry + 1))
        if (( retry > max_retries )); then
          EXTENDED_PHASES+=("$phase")
          PHASE_RETRIES[$phase]=$((retry - 1))
          notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase: ${max_retries}회 재시도 후 promise 미감지, 강제 진행"
          phase_success=true  # 강제 진행
          break
        fi
        notify_alert "rw [$SESSION_NAME]" "Phase $phase: promise 미감지, 재시도 $retry/${max_retries}"
      fi
    else
      # Phase 실패 (크래시, 타임아웃 등)
      echo -n "Phase $phase 중단. 계속? (y/n): "
      read -r continue_choice
      if [[ "$continue_choice" != "y" ]]; then
        ALL_DONE=false
        break 2  # 외부 for 루프도 탈출
      fi
      break  # 내부 while만 탈출, 다음 phase로
    fi
  done

  if $phase_success; then
    COMPLETED_PHASES+=("$phase")
    notify_alert "rw [$SESSION_NAME]" "Phase $phase/$END_PHASE ${PHASE_NAMES[$phase]}: 완료"
  fi
done

# 전체 완료 시 상태 갱신 + 임시 파일 정리
if ! $DRY_RUN && $ALL_DONE; then
  save_session_state "completed" "$END_PHASE"
  # 임시 파일을 세션 디렉토리에 보관 (사후 분석용)
  for f in "$PLAN_PATH" "$CHECKLIST_PATH" "$DIGEST_PATH" "$NOTES_PATH"; do
    [[ -f "$f" ]] && mv "$f" "$SESSION_DIR/"
  done
fi

TOTAL_ELAPSED=$((SECONDS - WORKFLOW_START))
TOTAL_DURATION=$(format_duration "$TOTAL_ELAPSED")

# 요약 테이블 출력 (실행된 phase가 있을 때만)
if [[ ${#COMPLETED_PHASES[@]} -gt 0 ]]; then
  print_summary "$TOTAL_ELAPSED"
fi

TOTAL_TOKENS_FMT=$(format_tokens "$(compute_total_tokens)")

notify_alert "rw [$SESSION_NAME] 완료" "spec ${#SPEC_PATHS[@]}개 — $TOTAL_DURATION — ↓ $TOTAL_TOKENS_FMT"
