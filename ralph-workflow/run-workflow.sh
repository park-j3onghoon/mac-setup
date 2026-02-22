#!/bin/zsh
# Ralph Workflow - Phase 0~19 자동 체이닝 스크립트 (전역)
#
# 사용법:
#   rw -s <session_name> <spec_paths...> [options]
#
# 예시:
#   rw -s pr2-impl docs/spec_detail_2.md -m adscenter/displaycam_partner
#   rw -s big-feature docs/spec_{1..3}.md -m src/app -n 2
#   rw -s best docs/spec.md -m src/app --model opus --effort high
#
# 옵션:
#   -s, --session NAME   세션 이름 (필수). 로그/프롬프트 파일 구분에 사용
#   --dry-run            실제 실행 없이 프롬프트만 출력
#   -n, --multiplier N   이터레이션 배수 (기본 1, float 허용. 예: -n 2, -n 0.5)
#   -m, --module PATH    구현 대상 모듈 경로
#   -t, --test PATH      테스트 디렉토리 경로
#   --model MODEL        Claude 실행 모델 (기본: opus)
#   --effort LEVEL       Claude 추론 강도 (기본: high)
#   --templates DIR      커스텀 템플릿 디렉토리
#   --from N             시작 Phase 번호 (기본 0). 특정 phase부터 재실행할 때 사용
#   --spec-split FILE    큰 스펙을 PR 단위로 분할 (--max-lines N, --review-hours H)
#   --review             세션 리뷰 파일 생성 + 리뷰 세션 시작 (spec 없이 사용 가능)
#   --assistant NAME     --review에서 실행할 도우미 (codex|claude|none, 기본 codex)
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

# ─── 플러그인 캐시 동기화 ───
# marketplace 소스가 캐시보다 새로우면 갱신 (stop hook 버그 fix 반영)
sync_plugin_cache() {
  local plugin_name=$1
  local marketplace_src="$HOME/.claude/plugins/marketplaces/$plugin_name"
  local cache_base="$HOME/.claude/plugins/cache/$plugin_name"

  [[ ! -d "$marketplace_src" ]] && return 0
  [[ ! -d "$cache_base" ]] && return 0

  local synced=0
  for cache_dir in "$cache_base"/*(N/); do
    # hooks 디렉토리만 동기화 (스킬/설정은 건드리지 않음)
    if [[ -d "$marketplace_src/hooks" ]] && [[ -d "${cache_dir}hooks" ]]; then
      if ! diff -rq "$marketplace_src/hooks" "${cache_dir}hooks" >/dev/null 2>&1; then
        cp -R "$marketplace_src/hooks/"* "${cache_dir}hooks/"
        synced=$((synced + 1))
      fi
    fi
  done
  if (( synced > 0 )); then
    log_event "INFO" "plugin_sync" "plugin=$plugin_name synced=$synced"
  fi
}

# ─── 외부 Stop hook 비활성화 ───
ECC_HOOKS_BACKUPS=()

disable_external_stop_hooks() {
  if ! command -v jq >/dev/null 2>&1; then
    log_event "WARN" "skip_disable_hooks" "reason=jq_not_found"
    return 0
  fi
  for hooks_json in "$HOME/.claude/plugins/cache/everything-claude-code"/*/*/hooks/hooks.json(N); do
    local backup="${hooks_json}.rw-backup"
    cp "$hooks_json" "$backup"
    ECC_HOOKS_BACKUPS+=("$backup")
    if jq 'del(.hooks.Stop)' "$hooks_json" > "${hooks_json}.tmp" 2>/dev/null; then
      mv "${hooks_json}.tmp" "$hooks_json"
    else
      rm -f "${hooks_json}.tmp"
      log_event "WARN" "hook_disable_fail" "file=$hooks_json"
    fi
  done
}

restore_external_stop_hooks() {
  for backup in "${ECC_HOOKS_BACKUPS[@]}"; do
    local original="${backup%.rw-backup}"
    [[ -f "$backup" ]] && mv "$backup" "$original"
  done
  ECC_HOOKS_BACKUPS=()
}

# ─── 프로세스 정리 ───
CLAUDE_PID=""
cleanup() {
  restore_external_stop_hooks
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

# ─── 정체 감지 ───
STALL_THRESHOLD=900    # 이터레이션 변화 없이 이 시간(초) 경과 시 알림 (15분)
STALL_KILL_THRESHOLD=3600  # 로그 의미있는 성장 없이 이 시간(초) 경과 시 프로세스 강제 종료 (60분)
LOG_GROWTH_CHECK_INTERVAL=900  # 로그 성장 체크 간격 (15분)
LOG_MEANINGFUL_GROWTH=102400   # 의미있는 성장 임계값 (100KB) — UI 노이즈 ~50KB/15분 vs 실제 작업 ~150KB+/15분

# ─── 색상 ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── 기본 모델/추론 설정 (최상) ───
DEFAULT_MODEL_NAME="opus"
DEFAULT_REASONING_EFFORT="high"
DEFAULT_CODEX_MODEL_NAME="gpt-5.3-codex"
DEFAULT_CODEX_REASONING_EFFORT="xhigh"

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
notify_alert() {  # 중요 알림 (phase 시작/끝) — 자동 소멸, 다른 소리
  _notify_dispatch "alert" "$1" "$2"
}
_notify_dispatch() {
  local level=$1
  local title="${2//\"/\\\"}"
  local message="${3//\"/\\\"}"
  case "$NOTIFY_BACKEND" in
    mac)
      if [[ "$level" == "alert" ]]; then
        osascript -e "display notification \"$message\" with title \"$title\" sound name \"Hero\"" 2>/dev/null || true
      else
        osascript -e "display notification \"$message\" with title \"$title\" sound name \"Glass\"" 2>/dev/null || true
      fi ;;
    *) printf '[%s] %s: %s\n' "$level" "$title" "$message" ;;
  esac
}

# ─── 이벤트 로그 ───
# 정체/에러 등 주요 이벤트를 타임스탬프와 함께 기록 (분석용)
EVENT_LOG_FILE=""  # SESSION_DIR 확정 후 설정

log_event() {
  [[ -z "$EVENT_LOG_FILE" ]] && return
  local level=$1 event=$2 detail=${3:-}
  printf '%s [%s] %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$event" "${detail//$'\n'/ }" >> "$EVENT_LOG_FILE"
}

# 로그 파일 tail에서 에러 패턴 탐지
# 반환: 감지된 패턴 문자열 (없으면 빈 문자열)
detect_log_errors() {
  local log_file=$1
  [[ ! -f "$log_file" ]] && return
  # 마지막 20KB 스캔 (4KB→20KB 확대: 큰 로그에서 에러 메시지 놓침 방지)
  local tail_content
  tail_content=$(tail -c 20480 "$log_file" 2>/dev/null | sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' 2>/dev/null || true)
  [[ -z "$tail_content" ]] && return

  local pattern
  # rate limit / API 에러 / 토큰 한도 패턴 (Claude CLI, API 공통)
  # 429/503은 단어 경계로 제한하여 토큰수·줄번호 false positive 방지
  pattern=$(printf '%s\n' "$tail_content" | grep -ioE 'rate.?limit|overloaded|(^|[^0-9])429([^0-9]|$)|(^|[^0-9])503([^0-9]|$)|too many requests|usage.?limit|quota.?exceed|context.?length.?exceed|token.?limit.?(reach|exceed|hit)|ECONNREFUSED|ECONNRESET|ETIMEDOUT|APIError|server.?error' | head -1 || true)
  [[ -n "$pattern" ]] && printf '%s\n' "${pattern:l}"  # 소문자 정규화 (중복 알림 방지)
}

# 로그 파일 크기 (bytes)
get_log_size() {
  local log_file=$1
  [[ ! -f "$log_file" ]] && printf '%s\n' 0 && return
  wc -c < "$log_file" 2>/dev/null || printf '%s\n' 0
}

# ─── 0-토큰 대기 (카운트다운 표시) ───
sleep_with_countdown() {
  local total=$1 label=${2:-"0-token 대기"}
  local remaining=$total
  while (( remaining > 0 )); do
    local step=$(( remaining < 30 ? remaining : 30 ))
    printf "\r${YELLOW}  %s: %d초 남음...${NC}  " "$label" "$remaining"
    sleep "$step"
    remaining=$((remaining - step))
  done
  printf "\r\033[K"
}

# ─── 0-토큰 처리 (token limit 대기 + 재시도) ───
# 반환: 0=계속 재시도, 1=워크플로우 중단 (호출부에서 break 2 필요)
handle_zero_tokens() {
  local phase=$1 context=${2:-"0 토큰"}
  CONSECUTIVE_ZERO_TOKENS=$((CONSECUTIVE_ZERO_TOKENS + 1))
  if (( CONSECUTIVE_ZERO_TOKENS >= MAX_ZERO_TOKEN_RETRIES )); then
    local zt_hours=$(( CONSECUTIVE_ZERO_TOKENS * ZERO_TOKEN_WAIT / 3600 ))
    notify_alert "rw [$SESSION_NAME] ⚠" "0 토큰 ${zt_hours}시간 지속. 워크플로우 중단"
    log_event "ERROR" "zero_tokens_timeout" "phase=$phase consecutive=${CONSECUTIVE_ZERO_TOKENS} hours=${zt_hours}"
    return 1
  fi
  local zt_elapsed=$(( CONSECUTIVE_ZERO_TOKENS * ZERO_TOKEN_WAIT / 60 ))
  local zt_max=$(( MAX_ZERO_TOKEN_RETRIES * ZERO_TOKEN_WAIT / 60 ))
  notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase: ${context} (연속 ${CONSECUTIVE_ZERO_TOKENS}회, ${zt_elapsed}/${zt_max}분). 10분 후 재시도"
  log_event "WARN" "zero_tokens" "phase=$phase context=${context} consecutive=${CONSECUTIVE_ZERO_TOKENS}"
  sleep_with_countdown "$ZERO_TOKEN_WAIT" "Phase $phase token limit 대기"
  return 0
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

# 시작 phase가 0이 아닐 때, .claude의 컨텍스트 파일(rw-*.md)이 비어있으면
# 세션 디렉토리에서 자동 복원한다.
find_context_source_file() {
  local file_name=$1

  # 1) 현재 세션 우선
  if [[ -f "$SESSION_DIR/$file_name" ]]; then
    printf '%s\n' "$SESSION_DIR/$file_name"
    return 0
  fi

  # 2) 같은 spec fingerprint를 가진 다른 세션 폴백
  local dirs=($SESSIONS_BASE_DIR/*(N/))
  [[ ${#dirs[@]} -eq 0 ]] && return 1
  for dir in "${dirs[@]}"; do
    [[ "$dir" == "$SESSION_DIR" ]] && continue
    [[ -f "$dir/$file_name" ]] || continue
    [[ -f "$dir/state.env" ]] || continue
    local fp=""
    fp=$(grep '^SPEC_FINGERPRINT=' "$dir/state.env" | cut -d= -f2- || true)
    if [[ "$fp" == "$SPEC_FINGERPRINT" ]]; then
      printf '%s\n' "$dir/$file_name"
      return 0
    fi
  done
  return 1
}

restore_context_files_if_missing() {
  [[ "$START_PHASE" -eq 0 ]] && return 0

  local -a context_files=(
    "rw-plan.md"
    "rw-checklist.md"
    "rw-spec-digest.md"
    "rw-notes.md"
  )
  local restored_count=0
  local missing_count=0

  mkdir -p "$PROJECT_ROOT/.claude"

  for file_name in "${context_files[@]}"; do
    local dest_path="$PROJECT_ROOT/.claude/$file_name"
    [[ -f "$dest_path" ]] && continue

    local src_path=""
    if src_path=$(find_context_source_file "$file_name"); then
      cp "$src_path" "$dest_path"
      restored_count=$((restored_count + 1))
      log_event "INFO" "context_restore" "file=$file_name source=$src_path"
    else
      missing_count=$((missing_count + 1))
      log_event "WARN" "context_missing" "file=$file_name phase=$START_PHASE"
    fi
  done

  if (( restored_count > 0 )); then
    notify_info "rw [$SESSION_NAME]" ".claude 컨텍스트 파일 ${restored_count}개 자동 복원"
  fi
  if (( missing_count > 0 )); then
    echo "${YELLOW}경고: .claude 컨텍스트 파일 ${missing_count}개를 자동 복원하지 못했습니다.${NC}" >&2
    echo "${YELLOW}      --from ${START_PHASE} 실행 품질을 위해 세션 파일 확인을 권장합니다.${NC}" >&2
  fi
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
  0  4
  1  2
  2  2
  3  2
  4  6
  5  4
  6  3
  7  2
  8  3
  9  2
  10 2
  11 4
  12 2
  13 2
  14 2
  15 2
  16 2
  17 4
  18 2
  19 1
)

# ─── 이터레이션 계산: ceil((base + spec_addend) × multiplier) ───
compute_iterations() {
  local base=$1 multiplier=$2 addend=$3
  awk -v b="$base" -v m="$multiplier" -v a="$addend" 'BEGIN{
    v = (b + a) * m; printf "%d", (v == int(v)) ? v : int(v) + 1
  }'
}

# Phase별 최대 재시도 횟수 = iterations × 3 (최대 9회)
compute_max_retries() {
  local iterations=$1
  local retries=$(( iterations * 3 ))
  (( retries > 9 )) && retries=9
  printf '%s\n' "$retries"
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
  local sed_clean='s/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1b][^\x07]*\x07//g; s/\x1b(B//g; s/\r//g'

  # 1차: 정확한 매칭 (명령어 에코/stop hook 안내 제외 — false positive 방지)
  if sed "$sed_clean" "$log_file" 2>/dev/null \
     | grep -v 'completion-promise' | grep -v '<promise>' | grep -qF "$promise" 2>/dev/null; then
    return 0
  fi
  # 2차: 공백 제거 매칭 (ANSI 제거 시 공백 소실 대응, e.g. "PLANDONE")
  local promise_nospace="${promise// /}"
  sed "${sed_clean}; s/ //g" "$log_file" 2>/dev/null \
    | grep -v 'completion.*promise' | grep -v '<promise>' | grep -qF "$promise_nospace" 2>/dev/null
}

# review 모드에서 즉시 사용하기 위한 경량 버전.
# (아래쪽에서 동일 이름 함수가 다시 정의되며, 일반 워크플로우 종료 시에는 최신 정의를 사용)
generate_review_file() {
  local review_file="$SESSION_DIR/rw-review.md"
  local state_file="$SESSION_DIR/state.env"
  local session_status="unknown" current_phase="0" spec_fingerprint=""
  [[ -f "$state_file" ]] && spec_fingerprint=$(grep '^SPEC_FINGERPRINT=' "$state_file" | cut -d= -f2-)
  [[ -f "$state_file" ]] && session_status=$(grep '^STATUS=' "$state_file" | cut -d= -f2-)
  [[ -f "$state_file" ]] && current_phase=$(grep '^CURRENT_PHASE=' "$state_file" | cut -d= -f2-)
  printf '%s' "$current_phase" | grep -qE '^[0-9]+$' || current_phase="0"

  local main_branch
  main_branch=$(detect_main_branch)
  local base_ref
  base_ref=$(git merge-base HEAD "$main_branch" 2>/dev/null || printf '%s\n' "HEAD~1")

  local status_file numstat_file
  status_file=$(mktemp)
  numstat_file=$(mktemp)
  git diff --name-status --no-renames "$base_ref" > "$status_file" 2>/dev/null || true
  git diff --numstat --no-renames "$base_ref" > "$numstat_file" 2>/dev/null || true

  typeset -A add_map del_map
  local add del file_path file_stat
  while IFS=$'\t' read -r add del file_path; do
    [[ -z "$file_path" ]] && continue
    [[ "$add" == "-" ]] && add=0
    [[ "$del" == "-" ]] && del=0
    add_map[$file_path]="${add:-0}"
    del_map[$file_path]="${del:-0}"
  done < "$numstat_file"

  local progress_pct=$(((current_phase + 1) * 100 / 20))
  [[ "$session_status" == "completed" ]] && progress_pct=100
  (( progress_pct > 100 )) && progress_pct=100
  (( progress_pct < 0 )) && progress_pct=0

  {
    echo "# RW Review Guide - ${SESSION_NAME}"
    echo ""
    echo "## 이번 작업 목표"
    echo "- spec 요구사항 구현/검증 결과를 리뷰한다."
    if [[ -n "$spec_fingerprint" ]]; then
      echo "- 대상 spec:"
      local spec_path
      for spec_path in ${(s:|:)spec_fingerprint}; do
        echo "  - \`${spec_path}\`"
      done
    fi
    echo ""
    echo "## 전체 작업 중 현재 위치"
    echo "- 상태: \`${session_status}\`"
    echo "- 현재/마지막 phase: \`${current_phase}\` (${PHASE_NAMES[$current_phase]:-알 수 없음})"
    echo "- 진행률: ${progress_pct}%"
    echo ""
    echo "## 리뷰 체크리스트"
    echo "- [ ] 1. 목표/범위 확인"
    echo "- [ ] 2. 신규 파일 확인"
    echo "- [ ] 3. 핵심 구현 변경 확인"
    echo "- [ ] 4. 테스트 변경 확인"
    echo "- [ ] 5. 문서/설정 확인"
    echo "- [ ] 6. 최종 판정"
    echo ""
    echo "## 파일별 변경 요약"
    echo "- 기준: \`${base_ref}\`..HEAD"
    while IFS=$'\t' read -r file_stat file_path; do
      [[ -z "$file_path" ]] && continue
      local kind="modified"
      [[ "$file_stat" == "A" ]] && kind="created"
      [[ "$file_stat" == "D" ]] && kind="deleted"
      echo "- \`${file_path}\` | ${kind} | +${add_map[$file_path]:-0}/-${del_map[$file_path]:-0}"
    done < "$status_file"
    echo ""
    echo "## 추천 리뷰 순서"
    echo "1. 계약/스키마/API 영향 파일"
    echo "2. 핵심 구현 파일"
    echo "3. 테스트 파일"
    echo "4. 문서/설정 파일"
    echo ""
    echo "## 함께 리뷰 진행"
    echo "- 1번 체크리스트부터 시작하고, 사용자 확인 후 다음으로 이동한다."
    echo "- 각 단계마다 피드백을 액션 아이템으로 기록한다."
  } > "$review_file"

  rm -f "$status_file" "$numstat_file"
  printf '%s\n' "$review_file"
}

launch_review_assistant() {
  local assistant=${1:-codex}
  local review_file=$2
  local prompt="Read ${review_file} first. Start from checklist item 1 only. Ask the user for review feedback and WAIT."
  case "$assistant" in
    codex)
      command -v codex >/dev/null 2>&1 || { echo "${YELLOW}경고: codex 미설치${NC}" >&2; return 0; }
      codex -C "$PROJECT_ROOT" --model "$DEFAULT_CODEX_MODEL_NAME" \
        -c "model_reasoning_effort=\"$DEFAULT_CODEX_REASONING_EFFORT\"" "$prompt"
      ;;
    claude)
      command -v claude >/dev/null 2>&1 || { echo "${YELLOW}경고: claude 미설치${NC}" >&2; return 0; }
      claude --model "$MODEL_NAME" --effort "$REASONING_EFFORT" "$prompt"
      ;;
    none) return 0 ;;
    *)
      echo "${RED}에러: 지원하지 않는 assistant입니다: $assistant (codex|claude|none)${NC}" >&2
      return 1
      ;;
  esac
}

# ─── 인자 파싱 ───
SPEC_PATHS=()
SESSION_NAME=""
START_PHASE=0
FROM_SPECIFIED=false
DRY_RUN=false
N_MULTIPLIER="1"
MODULE_PATH=""
TEST_PATH=""
CUSTOM_TEMPLATE_DIR=""
MODEL_NAME="$DEFAULT_MODEL_NAME"
REASONING_EFFORT="$DEFAULT_REASONING_EFFORT"
REVIEW_MODE=false
REVIEW_ASSISTANT="codex"
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
    --model)
      MODEL_NAME="$2"
      shift 2
      ;;
    --effort)
      REASONING_EFFORT="$2"
      shift 2
      ;;
    --from)
      START_PHASE="$2"
      FROM_SPECIFIED=true
      if ! printf '%s' "$START_PHASE" | grep -qE '^[0-9]+$' || [[ "$START_PHASE" -gt 19 ]]; then
        echo "${RED}에러: --from 값은 0~19 범위의 정수여야 합니다: $START_PHASE${NC}" >&2
        exit 1
      fi
      shift 2
      ;;
    --templates)
      CUSTOM_TEMPLATE_DIR="$2"
      shift 2
      ;;
    --review)
      REVIEW_MODE=true
      shift
      ;;
    --assistant)
      REVIEW_ASSISTANT="$2"
      shift 2
      ;;
    --spec-split)
      local spec_file="${2:-}"
      [[ -z "$spec_file" || "$spec_file" == -* ]] && echo "${RED}에러: spec 파일 경로 필요${NC}" >&2 && exit 1
      shift 2
      local max_lines=500
      local review_hours="1.5"
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --max-lines)
            max_lines="${2:-}"
            if ! printf '%s' "$max_lines" | grep -qE '^[1-9][0-9]*$'; then
              echo "${RED}에러: --max-lines 값은 1 이상의 정수여야 합니다: $max_lines${NC}" >&2
              exit 1
            fi
            shift 2
            ;;
          --review-hours)
            review_hours="${2:-}"
            if ! printf '%s' "$review_hours" | grep -qE '^[0-9]+\.?[0-9]*$'; then
              echo "${RED}에러: --review-hours 값은 양수 숫자여야 합니다: $review_hours${NC}" >&2
              exit 1
            fi
            if awk -v h="$review_hours" 'BEGIN{exit (h > 0) ? 0 : 1}'; then :; else
              echo "${RED}에러: --review-hours 값은 0보다 커야 합니다: $review_hours${NC}" >&2
              exit 1
            fi
            shift 2
            ;;
          *) break ;;
        esac
      done
      [[ ! -f "$spec_file" ]] && echo "${RED}에러: $spec_file 없음${NC}" >&2 && exit 1

      local target_review_minutes
      target_review_minutes=$(awk -v h="$review_hours" 'BEGIN{v=h*60; printf "%d", (v == int(v)) ? v : int(v) + 1}')
      local review_min=$((target_review_minutes - 30))
      local review_max=$((target_review_minutes + 30))
      (( review_min < 45 )) && review_min=45
      (( review_max > 240 )) && review_max=240

      local total=$(wc -l < "$spec_file" | tr -d ' ')
      if (( total <= max_lines )); then
        echo "${GREEN}분할 불필요: ${total}줄 (제한: ${max_lines}줄, 리뷰 목표: ${review_min}~${review_max}분)${NC}"
        exit 0
      fi

      # ── Step 1: ## 헤더 기준 섹션 추출 ──
      local -a h2_positions
      h2_positions=(${(f)"$(grep -n '^## [^#]' "$spec_file" | cut -d: -f1)"})

      if [[ ${#h2_positions[@]} -eq 0 ]]; then
        echo "${RED}에러: ## 헤더가 없어 섹션을 식별할 수 없습니다.${NC}" >&2
        exit 1
      fi

      # 프리앰블 (첫 ## 이전)
      local preamble_end=$((h2_positions[1] - 1))
      (( h2_positions[1] <= 1 )) && preamble_end=0
      local preamble_lines=$preamble_end
      local body_max=$((max_lines - preamble_lines))
      if (( body_max <= 0 )); then
        echo "${RED}에러: --max-lines(${max_lines})가 프리앰블(${preamble_lines})보다 작거나 같습니다.${NC}" >&2
        exit 1
      fi

      # 섹션별 정보
      local -a sec_starts sec_ends sec_names sec_lines
      local i
      for (( i=1; i<=${#h2_positions[@]}; i++ )); do
        sec_starts+=("${h2_positions[$i]}")
        if (( i < ${#h2_positions[@]} )); then
          sec_ends+=("$((h2_positions[$((i+1))] - 1))")
        else
          sec_ends+=("$total")
        fi
        local sec_name=''
        sec_name="$(sed -n "${h2_positions[$i]}p" "$spec_file" | sed 's/^## //')"
        sec_names+=("$sec_name")
        sec_lines+=("$((sec_ends[$i] - sec_starts[$i] + 1))")
      done

      local sec_count=${#sec_names[@]}

      # ── Step 2: LLM에게 PR 단위 그룹핑 + 맥락 요약 요청 ──
      local section_list=""
      for (( i=1; i<=sec_count; i++ )); do
        section_list+="  ${i}. ${sec_names[$i]} (${sec_lines[$i]}줄)"$'\n'
      done

      local ai_prompt="다음 스펙 문서를 사람이 리뷰하기 좋은 PR 단위로 분할하라.

규칙:
- 프리앰블(${preamble_lines}줄)은 모든 그룹에 자동 포함됨 (줄 수 계산에서 제외)
- 각 그룹의 섹션 줄 수 합: ${body_max}줄 이하
- 각 그룹은 PR 1개로 가정하며, 사람이 ${review_min}~${review_max}분(목표 ${target_review_minutes}분) 내 리뷰 가능한 크기로 맞춘다
- 서로 참조하거나 같은 도메인의 섹션은 같은 그룹에 배치한다
- PR 순서는 점진적으로 구성한다: 기반/계약 -> 핵심 기능 -> 엣지케이스/예외 -> 마무리
- 한 PR에 너무 많은 목표를 섞지 말고, 리뷰 가능한 단일 목적을 유지한다
- 모든 섹션 번호가 정확히 1번씩 등장해야 함 (누락/중복 불가)
- 단일 섹션이 ${body_max}줄 초과 시 단독 그룹

섹션 목록:
${section_list}
응답 형식 — 각 PR을 한 줄에 출력. 설명/마크다운/코드블록 금지.
형식:
섹션번호들|PR:<짧은 제목>|REVIEW:<분>|CTX:<다른 PR에 있는 참고 맥락 2~3문장>

예시:
1,3|PR:인증 기반/API 계약 정리|REVIEW:80|CTX:실제 비즈니스 검증은 PR2에서 구현. DB 마이그레이션은 PR4에서 진행.
2,4,5|PR:핵심 조회/집계 구현|REVIEW:105|CTX:인증/권한 체크 로직은 PR1 계약을 그대로 사용. 엣지케이스는 PR3에서 보강.

스펙 전문:
$(cat "$spec_file")"

      echo "${CYAN}AI로 섹션 관련성 분석 중...${NC}" >&2
      local ai_prompt_file ai_result
      ai_prompt_file="$(mktemp)"
      printf '%s' "$ai_prompt" > "$ai_prompt_file"
      ai_result="$(claude -p --model "$MODEL_NAME" --effort "$REASONING_EFFORT" < "$ai_prompt_file" 2>/dev/null)"
      local ai_exit=$?
      rm -f "$ai_prompt_file"

      if [[ $ai_exit -ne 0 ]] || [[ -z "$ai_result" ]]; then
        echo "${RED}에러: AI 호출 실패${NC}" >&2
        exit 1
      fi

      # ── Step 3: AI 응답 파싱 ──
      local -a group_nums_list group_context_list group_pr_titles group_review_mins

      while IFS= read -r line; do
        line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [[ -z "$line" ]] && continue
        if [[ "$line" =~ ^([0-9]+(,[0-9]+)*)\|PR:([^|]+)\|REVIEW:([0-9]+)\|CTX:(.+)$ ]]; then
          group_nums_list+=("${match[1]}")
          group_pr_titles+=("$(printf '%s' "${match[3]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')")
          group_review_mins+=("${match[4]}")
          group_context_list+=("$(printf '%s' "${match[5]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')")
        elif [[ "$line" =~ ^([0-9]+(,[0-9]+)*)\|(.+)$ ]]; then
          group_nums_list+=("${match[1]}")
          group_pr_titles+=("PR ${#group_nums_list[@]}")
          group_review_mins+=("$target_review_minutes")
          group_context_list+=("$(printf '%s' "${match[3]}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')")
        elif [[ "$line" =~ ^([0-9]+(,[0-9]+)*)$ ]]; then
          group_nums_list+=("${match[1]}")
          group_pr_titles+=("PR ${#group_nums_list[@]}")
          group_review_mins+=("$target_review_minutes")
          group_context_list+=("")
        fi
      done <<< "$ai_result"

      if [[ ${#group_nums_list[@]} -eq 0 ]]; then
        echo "${RED}에러: AI 응답을 파싱할 수 없습니다.${NC}" >&2
        echo "${YELLOW}AI 원본 응답:${NC}" >&2
        printf '%s\n' "$ai_result" | head -20 >&2
        exit 1
      fi

      # 검증: 모든 섹션 번호가 정확히 1번씩
      local all_nums=""
      for g in "${group_nums_list[@]}"; do
        all_nums+="$(printf '%s\n' "$g" | tr ',' '\n')"$'\n'
      done
      local sorted_nums=$(printf '%s' "$all_nums" | grep -E '^[0-9]+$' | sort -n)
      local expected_nums=$(seq 1 $sec_count)
      if [[ "$sorted_nums" != "$expected_nums" ]]; then
        echo "${RED}에러: AI 그룹핑 검증 실패 (섹션 누락/중복)${NC}" >&2
        echo "  기대: $(seq 1 $sec_count | tr '\n' ',')" >&2
        echo "  실제: $(printf '%s' "$sorted_nums" | tr '\n' ',')" >&2
        exit 1
      fi
      for (( i=1; i<=${#group_nums_list[@]}; i++ )); do
        if ! printf '%s' "${group_review_mins[$i]}" | grep -qE '^[0-9]+$'; then
          group_review_mins[$i]="$target_review_minutes"
        fi
        (( group_review_mins[$i] < 30 )) && group_review_mins[$i]=30
        [[ -z "${group_pr_titles[$i]}" ]] && group_pr_titles[$i]="PR $i"
      done

      # ── Step 4: split 파일 생성 (PR 메타 + 맥락 + 원본 섹션) ──
      local base="${spec_file%.md}"
      local split_num=${#group_nums_list[@]}
      local -a split_line_counts split_sec_labels
      local plan_file="${base}.split-plan.md"

      for (( i=1; i<=split_num; i++ )); do
        local out_file="${base}.split-${i}.md"
        : > "$out_file"

        # 1) 프리앰블 원본
        if (( preamble_end > 0 )); then
          sed -n "1,${preamble_end}p" "$spec_file" >> "$out_file"
          printf '\n' >> "$out_file"
        fi

        # 2) PR 메타 + 맥락 요약
        printf '> **PR 단위**: PR %s - %s\n' "$i" "${group_pr_titles[$i]}" >> "$out_file"
        printf '> **예상 리뷰 시간**: 약 %s분 (목표 %s분)\n' "${group_review_mins[$i]}" "$target_review_minutes" >> "$out_file"
        if [[ -n "${group_context_list[$i]}" ]]; then
          printf '> **다른 PR 참조 맥락**: %s\n' "${group_context_list[$i]}" >> "$out_file"
        fi
        printf '\n---\n\n' >> "$out_file"

        # 3) 해당 섹션들 원본 (sed 추출)
        local -a nums
        nums=(${(s:,:)group_nums_list[$i]})
        local sec_label_parts=()
        for n in "${nums[@]}"; do
          sed -n "${sec_starts[$n]},${sec_ends[$n]}p" "$spec_file" >> "$out_file"
          printf '\n' >> "$out_file"
          sec_label_parts+=("${sec_names[$n]}")
        done
        split_sec_labels+=("${(j:, :)sec_label_parts}")

        local file_lines=$(wc -l < "$out_file" | tr -d ' ')
        split_line_counts+=("$file_lines")
      done

      # ── Step 5: PR 순서 플랜 파일 생성 ──
      {
        echo "# Spec Split PR Plan"
        echo ""
        echo "- 원본 스펙: $spec_file"
        echo "- 리뷰 목표: PR당 ${review_min}~${review_max}분 (target ${target_review_minutes}분)"
        echo "- 줄수 제한: 프리앰블 제외 ${body_max}줄 이하"
        echo ""
        for (( i=1; i<=split_num; i++ )); do
          echo "## PR ${i}: ${group_pr_titles[$i]}"
          echo "- 파일: ${base}.split-${i}.md"
          echo "- 섹션 번호: ${group_nums_list[$i]}"
          echo "- 포함 섹션: ${split_sec_labels[$i]}"
          echo "- 예상 리뷰 시간: 약 ${group_review_mins[$i]}분"
          if [[ -n "${group_context_list[$i]}" ]]; then
            echo "- 다른 PR 참조 맥락: ${group_context_list[$i]}"
          fi
          echo ""
        done
      } > "$plan_file"

      # ── 결과 출력 ──
      echo ""
      echo "스펙 분할(PR 단위): $spec_file (${total}줄 → ${split_num}개 파일)"
      echo ""
      for (( i=1; i<=split_num; i++ )); do
        printf "  split-%s.md — %s줄 — PR %s: %s (리뷰 ~%s분)\n" \
          "$i" "${split_line_counts[$i]}" "$i" "${group_pr_titles[$i]}" "${group_review_mins[$i]}"
      done
      echo "  plan: $(basename "$plan_file")"
      echo ""
      echo "실행 예시:"
      local session_base=$(basename "${base}")
      for (( i=1; i<=split_num; i++ )); do
        echo "  rw -s ${session_base}-${i} ${base}.split-${i}.md -m src/module"
      done
      echo ""
      exit 0
      ;;
    --clean)
      local sessions=($SESSIONS_BASE_DIR/*(N/))
      if [[ ${#sessions[@]} -eq 0 ]]; then
        echo "${YELLOW}삭제할 세션이 없습니다.${NC}"
        exit 0
      fi
      echo "${CYAN}세션 목록:${NC}"
      for dir in "${sessions[@]}"; do
        local name=$(basename "$dir")
        local size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        local files=$(ls "$dir" 2>/dev/null | wc -l | tr -d ' ')
        echo "  ${name} (${size}, ${files}개 파일)"
      done
      echo ""
      echo -n "${YELLOW}모든 세션을 삭제합니다. 계속? (y/n): ${NC}"
      read -r confirm
      if [[ "$confirm" == "y" ]]; then
        rm -rf "$SESSIONS_BASE_DIR"/*(N/)
        echo "${GREEN}${#sessions[@]}개 세션 삭제 완료.${NC}"
      else
        echo "취소됨."
      fi
      exit 0
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

if $REVIEW_MODE; then
  if [[ -z "$SESSION_NAME" ]]; then
    echo "${RED}에러: --review 사용 시 --session (-s) 옵션은 필수입니다.${NC}" >&2
    echo "예시: rw --review -s pr2-impl --assistant codex" >&2
    exit 1
  fi
  if [[ -n "${SESSION_NAME//[a-zA-Z0-9_-]/}" ]]; then
    echo "${RED}에러: 세션 이름은 영문, 숫자, 하이픈(-), 밑줄(_)만 허용됩니다: $SESSION_NAME${NC}" >&2
    exit 1
  fi
  SESSION_DIR="$SESSIONS_BASE_DIR/$SESSION_NAME"
  if [[ ! -d "$SESSION_DIR" ]]; then
    echo "${RED}에러: 세션 디렉토리를 찾을 수 없습니다: $SESSION_DIR${NC}" >&2
    exit 1
  fi
  EVENT_LOG_FILE="$SESSION_DIR/rw-events.log"
  review_file=$(generate_review_file)
  echo "${GREEN}리뷰 파일 생성 완료: $review_file${NC}"
  echo "${CYAN}리뷰 시작: 체크리스트 1번부터 사용자 확인을 받고 진행합니다.${NC}"
  launch_review_assistant "$REVIEW_ASSISTANT" "$review_file"
  exit $?
fi

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

# 기존 미완료 세션 검사 (dry-run 및 --from 명시 시 제외)
if ! $DRY_RUN && ! $FROM_SPECIFIED; then
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
EVENT_LOG_FILE="$SESSION_DIR/rw-events.log"

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

# --from으로 중간 phase부터 시작할 때 필요한 컨텍스트 파일 자동 복원
restore_context_files_if_missing

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
LAST_PHASE_TOKENS=0          # run_phase에서 설정, 메인 루프에서 0-토큰 감지용
CONSECUTIVE_ZERO_TOKENS=0    # 연속 0-토큰 횟수 (별도 카운터, max_retries와 독립)
MAX_ZERO_TOKEN_RETRIES=60    # 0-토큰 최대 재시도 (10분 × 60 = 10시간)
ZERO_TOKEN_WAIT=600          # 0-토큰 재시도 대기 시간 (10분 = 600초)

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
  script -q "$log_file" claude --dangerously-skip-permissions --model "$MODEL_NAME" --effort "$REASONING_EFFORT" \
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
  local last_progress=$SECONDS
  local last_stall_alert=$SECONDS
  local last_checkpoint_size=$(get_log_size "$log_file")
  local last_growth_check=$SECONDS
  local last_log_active=$SECONDS
  local last_error_scan=$SECONDS
  local last_detected_error=""

  log_event "INFO" "phase_start" "phase=$phase_num name=$phase_name max_iter=$max_iter"

  while true; do
    # Claude 프로세스 생존 확인
    if ! kill -0 "$CLAUDE_PID" 2>/dev/null; then
      printf "\r\033[K"
      wait "$CLAUDE_PID" 2>/dev/null
      sleep 1  # 로그 파일 flush 대기
      log_event "INFO" "process_exit" "phase=$phase_num iter=${last_iter:-0}"
      break
    fi

    # 상태 파일 확인
    if [[ -f "$RALPH_STATE_FILE" ]]; then
      state_file_seen=true
      # 현재 이터레이션 읽기
      current_iter=$(sed -n '/^---$/,/^---$/{ /^---$/d; p; }' "$RALPH_STATE_FILE" 2>/dev/null | grep '^iteration:' | sed 's/iteration: *//' 2>/dev/null)
      if [[ -n "$current_iter" ]] && [[ "$current_iter" != "$last_iter" ]]; then
        last_iter="$current_iter"
        last_progress=$SECONDS
        last_stall_alert=$SECONDS
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

      # 로그 파일 활성 감지: SIZE 증가량 추적
      # UI 노이즈(스피너/상태바)는 ~50KB/15분, 실제 작업은 ~150KB+/15분
      local log_active=false
      if (( SECONDS - last_growth_check >= LOG_GROWTH_CHECK_INTERVAL )); then
        local cur_log_size=$(get_log_size "$log_file")
        local growth=$((cur_log_size - last_checkpoint_size))
        if (( growth > LOG_MEANINGFUL_GROWTH )); then
          last_log_active=$SECONDS
          log_active=true
        fi
        last_checkpoint_size=$cur_log_size
        last_growth_check=$SECONDS
      fi
      local log_stale_secs=$(( SECONDS - last_log_active ))

      # 강제 종료: 로그 정체 STALL_KILL_THRESHOLD(60분) 이상 → 프로세스 죽음
      if (( log_stale_secs >= STALL_KILL_THRESHOLD )); then
        local stale_min=$(( log_stale_secs / 60 ))
        notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase_num: 로그 ${stale_min}분간 무응답 → 강제 종료"
        log_event "ERROR" "stall_kill" "phase=$phase_num iter=${last_iter:-0} log_stale=${stale_min}m"
        printf "\r\033[K"
        kill "$CLAUDE_PID" 2>/dev/null
        local kill_wait=0
        while kill -0 "$CLAUDE_PID" 2>/dev/null && (( kill_wait < 5 )); do
          sleep 1
          kill_wait=$((kill_wait + 1))
        done
        kill -- -"$CLAUDE_PID" 2>/dev/null || true
        wait "$CLAUDE_PID" 2>/dev/null
        break
      fi

      # 정체 알림: STALL_THRESHOLD(15분) 주기
      if (( SECONDS - last_stall_alert >= STALL_THRESHOLD )); then
        local stall_secs=$(( SECONDS - last_progress ))
        local stall_min=$(( stall_secs / 60 ))
        if $log_active || (( log_stale_secs < LOG_GROWTH_CHECK_INTERVAL )); then
          notify_info "rw [$SESSION_NAME]" "Phase $phase_num: iter ${last_iter:-0}/${max_iter} — ${stall_min}분 경과 (로그 활성, 작업 중)"
          log_event "INFO" "long_iter" "phase=$phase_num iter=${last_iter:-0} elapsed=${stall_min}m"
        else
          local stale_min=$(( log_stale_secs / 60 ))
          notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase_num: 로그 ${stale_min}분간 무응답 (iter ${last_iter:-0}/${max_iter})"
          log_event "WARN" "stall_log" "phase=$phase_num iter=${last_iter:-0} log_stale=${stale_min}m"
        fi
        last_stall_alert=$SECONDS
      fi

      # 에러 패턴 스캔 (30초마다)
      if (( SECONDS - last_error_scan >= 30 )); then
        local detected=$(detect_log_errors "$log_file")
        if [[ -n "$detected" ]] && [[ "$detected" != "$last_detected_error" ]]; then
          notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase_num: 에러 감지 — $detected"
          log_event "ERROR" "log_error" "phase=$phase_num iter=${last_iter:-0} pattern=$detected"
          last_detected_error="$detected"
        fi
        last_error_scan=$SECONDS
      fi

      # Claude 프롬프트 대기 감지: stop hook error 후 ❯ 에서 멈춤
      if (( SECONDS - phase_start >= 120 )); then
        local tail_clean
        tail_clean=$(tail -c 4096 "$log_file" 2>/dev/null \
          | sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1b][^\x07]*\x07//g; s/\r//g' 2>/dev/null || true)
        if printf '%s' "$tail_clean" | grep -q 'Stop hook error' 2>/dev/null && \
           printf '%s' "$tail_clean" | grep -qE '❯|bypass permissions' 2>/dev/null; then
          log_event "ERROR" "prompt_stuck" "phase=$phase_num iter=${last_iter:-0}"
          notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase_num: 프롬프트 대기 감지 → 종료"
          printf "\r\033[K"
          kill "$CLAUDE_PID" 2>/dev/null
          sleep 2
          kill -- -"$CLAUDE_PID" 2>/dev/null || true
          wait "$CLAUDE_PID" 2>/dev/null
          break
        fi
      fi
    else
      # 상태 파일 삭제됨 = Ralph Loop 완료 (promise 감지 또는 max-iter 도달)
      printf "\r\033[K"
      # 1단계: Claude가 자연 종료될 때까지 대기 (최대 30초)
      # state file 삭제 시점과 Claude 최종 출력 사이에 갭이 있으므로 즉시 kill하지 않는다
      local kill_wait=0
      while kill -0 "$CLAUDE_PID" 2>/dev/null && (( kill_wait < 30 )); do
        sleep 1
        kill_wait=$((kill_wait + 1))
      done
      # 2단계: 30초 후에도 살아있으면 강제 종료
      if kill -0 "$CLAUDE_PID" 2>/dev/null; then
        kill "$CLAUDE_PID" 2>/dev/null
        sleep 2
        kill -- -"$CLAUDE_PID" 2>/dev/null || true
      fi
      wait "$CLAUDE_PID" 2>/dev/null
      # 3단계: 로그 파일 flush 대기
      sleep 1
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
  LAST_PHASE_TOKENS=$tokens

  # 통계 누적 (재시도 시 기존 값에 더함)
  PHASE_DURATIONS[$phase_num]=$((${PHASE_DURATIONS[$phase_num]:-0} + phase_elapsed))
  PHASE_TOKENS[$phase_num]=$((${PHASE_TOKENS[$phase_num]:-0} + tokens))
  # 이터레이션 라벨
  local iter_label=""
  if [[ -n "${last_iter:-}" ]] && [[ "${last_iter:-0}" != "0" ]]; then
    iter_label=" (iter ${last_iter}/${max_iter})"
  fi

  if [[ -f "$RALPH_STATE_FILE" ]]; then
    # 상태 파일이 남아 있음 = 실행 중 중단됨
    rm -f "$RALPH_STATE_FILE"
    echo "${RED}✘ Phase $phase_num $phase_name — $duration — ↓ $tokens_fmt${iter_label}${retry_label}${NC}"
    notify_alert "rw [$SESSION_NAME]" "Phase $phase_num/$end_phase $phase_name: 중단 ($duration, ↓ $tokens_fmt)"
    return 1
  elif ! $state_file_seen; then
    # 상태 파일이 한 번도 생성되지 않음 = 프로세스 조기 사망
    echo "${RED}✘ Phase $phase_num $phase_name — $duration — ↓ $tokens_fmt (프로세스 조기 종료)${NC}"
    notify_alert "rw [$SESSION_NAME]" "Phase $phase_num/$end_phase $phase_name: 실패 — 프로세스 시작 안 됨"
    return 1
  else
    # 상태 파일 생성 후 삭제됨 = 실행 완료 (promise 여부는 메인 루프에서 확인)
    echo "${GREEN}✔ Phase $phase_num $phase_name — $duration — ↓ $tokens_fmt${iter_label}${retry_label}${NC}"
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

categorize_review_path() {
  local file_path=$1
  if [[ "$file_path" == *"/migrations/"* ]] || [[ "$file_path" == *.sql ]] || [[ "$file_path" == *schema* ]] || [[ "$file_path" == *openapi* ]] || [[ "$file_path" == *.proto ]]; then
    printf '%s\n' "1|계약/스키마/API"
  elif [[ "$file_path" == */tests/* ]] || [[ "$file_path" == tests/* ]] || [[ "$file_path" == *_test.py ]] || [[ "$file_path" == test_* ]]; then
    printf '%s\n' "3|테스트"
  elif [[ "$file_path" == docs/* ]] || [[ "$file_path" == *.md ]]; then
    printf '%s\n' "4|문서/운영"
  elif [[ "$file_path" == *.yml ]] || [[ "$file_path" == *.yaml ]] || [[ "$file_path" == *.toml ]] || [[ "$file_path" == *.json ]] || [[ "$file_path" == *.ini ]]; then
    printf '%s\n' "5|설정/기타"
  else
    printf '%s\n' "2|핵심 구현"
  fi
}

review_focus_for_path() {
  local file_path=$1
  if [[ "$file_path" == *"/migrations/"* ]] || [[ "$file_path" == *.sql ]] || [[ "$file_path" == *schema* ]]; then
    printf '%s\n' "스키마/호환성 영향 확인"
  elif [[ "$file_path" == */tests/* ]] || [[ "$file_path" == tests/* ]] || [[ "$file_path" == *_test.py ]] || [[ "$file_path" == test_* ]]; then
    printf '%s\n' "요구사항 커버리지와 assertion 품질 확인"
  elif [[ "$file_path" == docs/* ]] || [[ "$file_path" == *.md ]]; then
    printf '%s\n' "문서와 실제 동작 일치 여부 확인"
  else
    printf '%s\n' "요구사항 반영/부작용/예외 처리 확인"
  fi
}

generate_review_file() {
  local review_file="$SESSION_DIR/rw-review.md"
  local state_file="$SESSION_DIR/state.env"
  local session_status="unknown"
  local current_phase=0
  local spec_fingerprint=""

  if [[ -f "$state_file" ]]; then
    spec_fingerprint=$(grep '^SPEC_FINGERPRINT=' "$state_file" | cut -d= -f2-)
    session_status=$(grep '^STATUS=' "$state_file" | cut -d= -f2-)
    current_phase=$(grep '^CURRENT_PHASE=' "$state_file" | cut -d= -f2-)
  fi
  if ! printf '%s' "$current_phase" | grep -qE '^[0-9]+$'; then
    current_phase=0
  fi

  local progress_pct=0
  if [[ "$session_status" == "completed" ]]; then
    progress_pct=100
  else
    progress_pct=$(((current_phase + 1) * 100 / 20))
    (( progress_pct > 99 )) && progress_pct=99
  fi
  local current_phase_name="${PHASE_NAMES[$current_phase]:-알 수 없음}"

  local -a spec_entries=()
  if [[ ${#SPEC_PATHS[@]} -gt 0 ]]; then
    spec_entries=("${SPEC_PATHS[@]}")
  elif [[ -n "$spec_fingerprint" ]]; then
    spec_entries=(${(s:|:)spec_fingerprint})
  fi

  local main_branch
  main_branch=$(detect_main_branch)
  local base_ref
  base_ref=$(git merge-base HEAD "$main_branch" 2>/dev/null || printf '%s\n' "HEAD~1")

  local diff_status_file diff_numstat_file
  diff_status_file=$(mktemp)
  diff_numstat_file=$(mktemp)
  git diff --name-status --no-renames "$base_ref" > "$diff_status_file" 2>/dev/null || true
  git diff --numstat --no-renames "$base_ref" > "$diff_numstat_file" 2>/dev/null || true

  typeset -A file_status file_added file_deleted file_bucket file_bucket_label
  local file_stat file_path
  while IFS=$'\t' read -r file_stat file_path; do
    [[ -z "$file_path" ]] && continue
    case "$file_stat" in
      A) file_status[$file_path]="created" ;;
      M) file_status[$file_path]="modified" ;;
      D) file_status[$file_path]="deleted" ;;
      *) file_status[$file_path]="$file_stat" ;;
    esac
    local bucket_info bucket_no bucket_label
    bucket_info=$(categorize_review_path "$file_path")
    bucket_no="${bucket_info%%|*}"
    bucket_label="${bucket_info#*|}"
    file_bucket[$file_path]="$bucket_no"
    file_bucket_label[$file_path]="$bucket_label"
  done < "$diff_status_file"

  local add del num_file_path
  while IFS=$'\t' read -r add del num_file_path; do
    [[ -z "$num_file_path" ]] && continue
    [[ "$add" == "-" ]] && add=0
    [[ "$del" == "-" ]] && del=0
    file_added[$num_file_path]="${add:-0}"
    file_deleted[$num_file_path]="${del:-0}"
  done < "$diff_numstat_file"

  local -a changed_paths=(${(k)file_status})
  changed_paths=(${(on)changed_paths})
  local changed_count=${#changed_paths[@]}

  local created_count=0 modified_count=0 deleted_count=0
  local -a bucket1_files=() bucket2_files=() bucket3_files=() bucket4_files=() bucket5_files=()
  local file_path
  for file_path in "${changed_paths[@]}"; do
    case "${file_status[$file_path]}" in
      created) created_count=$((created_count + 1)) ;;
      modified) modified_count=$((modified_count + 1)) ;;
      deleted) deleted_count=$((deleted_count + 1)) ;;
    esac
    case "${file_bucket[$file_path]:-2}" in
      1) bucket1_files+=("$file_path") ;;
      2) bucket2_files+=("$file_path") ;;
      3) bucket3_files+=("$file_path") ;;
      4) bucket4_files+=("$file_path") ;;
      5) bucket5_files+=("$file_path") ;;
    esac
  done

  {
    echo "# RW Review Guide - ${SESSION_NAME}"
    echo ""
    echo "## 이번 작업 목표"
    if [[ ${#spec_entries[@]} -gt 0 ]]; then
      echo "- Spec 요구사항 구현/검증 완료 (Phase 0~19)"
      echo "- 대상 spec:"
      local spec
      for spec in "${spec_entries[@]}"; do
        echo "  - \`${spec}\`"
      done
    else
      echo "- 세션 상태 기준으로 워크플로우 결과 검토"
    fi
    echo "- 리뷰 목적: 변경 사항을 누락 없이 빠르게 검증하고 배포/머지 리스크를 줄인다."
    echo ""
    echo "## 전체 작업 중 현재 위치"
    echo "- 상태: \`${session_status}\`"
    echo "- 현재/마지막 Phase: \`${current_phase}\` (${current_phase_name})"
    echo "- Phase 진행률(0~19 기준): ${progress_pct}%"
    echo "- 세션: \`${SESSION_NAME}\`"
    echo "- 리뷰 문서 생성 시각: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "## 리뷰 체크리스트"
    echo "- [ ] 1. 목표/범위 확인 (Spec/요구사항과 현재 변경의 일치 여부)"
    echo "- [ ] 2. 신규 생성 파일 검토 (누락/과도한 설계 여부)"
    echo "- [ ] 3. 핵심 구현 변경 검토 (비즈니스 규칙/예외 처리/부작용)"
    echo "- [ ] 4. 테스트 변경 검토 (커버리지/assert 품질/회귀 방지)"
    echo "- [ ] 5. 문서/설정 변경 검토 (운영 영향/설정 누락)"
    echo "- [ ] 6. 최종 판정 (머지 가능/추가 수정 필요)"
    echo ""
    echo "## 변경 파일 요약"
    echo "- 비교 기준: \`${base_ref}\`..HEAD"
    echo "- 총 변경 파일: ${changed_count}개 (created ${created_count}, modified ${modified_count}, deleted ${deleted_count})"
    echo ""
    echo "### 신규 생성 파일"
    if (( created_count == 0 )); then
      echo "- 없음"
    else
      for file_path in "${changed_paths[@]}"; do
        [[ "${file_status[$file_path]}" == "created" ]] && echo "- \`${file_path}\`"
      done
    fi
    echo ""
    echo "### 파일별 변경 상세"
    if (( changed_count == 0 )); then
      echo "- 변경 파일 없음"
    else
      for file_path in "${changed_paths[@]}"; do
        local add_v="${file_added[$file_path]:-0}"
        local del_v="${file_deleted[$file_path]:-0}"
        local focus
        focus=$(review_focus_for_path "$file_path")
        echo "- \`${file_path}\` | ${file_status[$file_path]} | +${add_v}/-${del_v} | ${focus}"
      done
    fi
    echo ""
    echo "## 추천 리뷰 순서 (1~2시간 리뷰 기준)"
    echo "1. 계약/스키마/API 영향 파일"
    if (( ${#bucket1_files[@]} == 0 )); then echo "   - 없음"; else for file_path in "${bucket1_files[@]}"; do echo "   - \`${file_path}\`"; done; fi
    echo "2. 핵심 구현 파일"
    if (( ${#bucket2_files[@]} == 0 )); then echo "   - 없음"; else for file_path in "${bucket2_files[@]}"; do echo "   - \`${file_path}\`"; done; fi
    echo "3. 테스트 파일"
    if (( ${#bucket3_files[@]} == 0 )); then echo "   - 없음"; else for file_path in "${bucket3_files[@]}"; do echo "   - \`${file_path}\`"; done; fi
    echo "4. 문서/운영 파일"
    if (( ${#bucket4_files[@]} == 0 )); then echo "   - 없음"; else for file_path in "${bucket4_files[@]}"; do echo "   - \`${file_path}\`"; done; fi
    echo "5. 설정/기타 파일"
    if (( ${#bucket5_files[@]} == 0 )); then echo "   - 없음"; else for file_path in "${bucket5_files[@]}"; do echo "   - \`${file_path}\`"; done; fi
    echo ""
    echo "## 함께 리뷰 진행 방법"
    echo "- 리뷰 도우미를 실행하면 반드시 1번 항목부터 시작한다."
    echo "- 각 항목에서 사용자 확인을 받은 뒤 다음 번호로 이동한다."
    echo "- 사용자 피드백은 바로 액션 아이템으로 기록한다."
  } > "$review_file"

  rm -f "$diff_status_file" "$diff_numstat_file"
  printf '%s\n' "$review_file"
}

launch_review_assistant() {
  local assistant=${1:-codex}
  local review_file=$2
  local prompt="Read ${review_file} first. Start collaborative review from checklist item 1 only. Ask for the user's review and WAIT. Never move to item 2+ until the user explicitly confirms."

  case "$assistant" in
    codex)
      if ! command -v codex >/dev/null 2>&1; then
        echo "${YELLOW}경고: codex 명령을 찾을 수 없어 자동 실행을 건너뜁니다.${NC}" >&2
        return 0
      fi
      codex -C "$PROJECT_ROOT" --model "$DEFAULT_CODEX_MODEL_NAME" \
        -c "model_reasoning_effort=\"$DEFAULT_CODEX_REASONING_EFFORT\"" "$prompt"
      ;;
    claude)
      if ! command -v claude >/dev/null 2>&1; then
        echo "${YELLOW}경고: claude 명령을 찾을 수 없어 자동 실행을 건너뜁니다.${NC}" >&2
        return 0
      fi
      claude --model "$MODEL_NAME" --effort "$REASONING_EFFORT" "$prompt"
      ;;
    none)
      return 0
      ;;
    *)
      echo "${RED}에러: 지원하지 않는 assistant입니다: $assistant (codex|claude|none)${NC}" >&2
      return 1
      ;;
  esac
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
  echo "  Model: ${MODEL_NAME}, Effort: ${REASONING_EFFORT}"
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

notify_alert "rw [$SESSION_NAME] 시작" "Phase ${START_PHASE}~${END_PHASE}, spec ${#SPEC_PATHS[@]}개 (${SPEC_LINES}줄, ×${N_MULTIPLIER}), model=${MODEL_NAME}, effort=${REASONING_EFFORT}"
log_event "INFO" "workflow_start" "session=$SESSION_NAME phases=${START_PHASE}~${END_PHASE} specs=${#SPEC_PATHS[@]} model=$MODEL_NAME effort=$REASONING_EFFORT"

# 플러그인 캐시 동기화 + 외부 Stop hook 비활성화
if ! $DRY_RUN; then
  sync_plugin_cache "claude-plugins-official/plugins/ralph-loop"
  disable_external_stop_hooks
fi

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
    if (( CONSECUTIVE_ZERO_TOKENS > 0 )); then
      run_suffix="${run_suffix}-zt-${CONSECUTIVE_ZERO_TOKENS}"
    fi

    if run_phase "$phase" "$END_PHASE" "$run_suffix"; then
      # Phase 실행 완료 — promise 검증
      log_file="$SESSION_DIR/rw-phase-${phase}${run_suffix}.log"
      promise="${PHASE_PROMISES[$phase]}"

      if $DRY_RUN || check_promise_in_log "$log_file" "$promise"; then
        # promise 확인됨 → 성공
        phase_success=true
        PHASE_RETRIES[$phase]=$retry
        CONSECUTIVE_ZERO_TOKENS=0
        break
      else
        # promise 미감지
        if (( LAST_PHASE_TOKENS == 0 )); then
          # ── 0-토큰: token limit → 별도 카운터, retry 미차감, 10분 대기 ──
          if ! handle_zero_tokens "$phase" "0 토큰, promise 미감지"; then
            ALL_DONE=false
            break 2
          fi
        else
          # ── 정상 토큰이 나왔으나 promise 미감지 → 일반 재시도 ──
          CONSECUTIVE_ZERO_TOKENS=0
          retry=$((retry + 1))
          if (( retry > max_retries )); then
            EXTENDED_PHASES+=("$phase")
            PHASE_RETRIES[$phase]=$((retry - 1))
            notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase: ${max_retries}회 재시도 후 promise 미감지, 강제 진행"
            log_event "WARN" "force_proceed" "phase=$phase retries=$((retry - 1))"
            phase_success=true  # 강제 진행
            break
          fi
          notify_alert "rw [$SESSION_NAME]" "Phase $phase: promise 미감지, 재시도 $retry/${max_retries}"
          log_event "INFO" "retry" "phase=$phase retry=$retry max=$max_retries"
        fi
      fi
    else
      # Phase 실패 (크래시, 타임아웃 등)

      # ── 실패했지만 promise가 로그에 있으면 성공 처리 ──
      log_file="$SESSION_DIR/rw-phase-${phase}${run_suffix}.log"
      promise="${PHASE_PROMISES[$phase]}"
      if [[ -f "$log_file" ]] && check_promise_in_log "$log_file" "$promise"; then
        log_event "INFO" "promise_recovered" "phase=$phase"
        notify_alert "rw [$SESSION_NAME]" "Phase $phase: 실패했지만 promise 감지 → 성공"
        phase_success=true
        PHASE_RETRIES[$phase]=$retry
        CONSECUTIVE_ZERO_TOKENS=0
        break
      fi

      if (( LAST_PHASE_TOKENS == 0 )); then
        # ── 0-토큰 실패: token limit → 10분 대기 후 재시도 ──
        if ! handle_zero_tokens "$phase" "실패, 0 토큰"; then
          ALL_DONE=false
          break 2
        fi
      else
        # ── 일반 실패 ──
        CONSECUTIVE_ZERO_TOKENS=0
        log_event "ERROR" "phase_fail" "phase=$phase retry=$retry"
        if [[ -t 0 ]]; then
          notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase 실패 — 2분 내 응답 없으면 자동 진행"
          echo -n "Phase $phase 중단. 계속? (y/n, 2분 후 자동 y): "
          if read -t 120 -r continue_choice; then
            if [[ "$continue_choice" == "n" ]]; then
              log_event "INFO" "user_abort" "phase=$phase"
              ALL_DONE=false
              break 2
            fi
            log_event "INFO" "user_continue" "phase=$phase"
          else
            echo ""
            notify_alert "rw [$SESSION_NAME]" "Phase $phase 실패 — 2분 타임아웃, 자동 진행"
            log_event "WARN" "auto_continue" "phase=$phase reason=timeout_120s"
          fi
        else
          notify_alert "rw [$SESSION_NAME] ⚠" "Phase $phase 실패 — nohup 모드, 자동 진행"
          log_event "WARN" "auto_continue" "phase=$phase reason=no_tty"
        fi
        break  # 내부 while만 탈출, 다음 phase로
      fi
    fi
  done

  if $phase_success; then
    COMPLETED_PHASES+=("$phase")
    notify_alert "rw [$SESSION_NAME]" "Phase $phase/$END_PHASE ${PHASE_NAMES[$phase]}: 완료"
    log_event "INFO" "phase_done" "phase=$phase name=${PHASE_NAMES[$phase]} retries=${PHASE_RETRIES[$phase]:-0}"
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

if ! $DRY_RUN; then
  REVIEW_FILE_PATH=$(generate_review_file)
  echo "${CYAN}리뷰 파일: $REVIEW_FILE_PATH${NC}"
  echo "${CYAN}리뷰 시작 명령: rw --review -s ${SESSION_NAME} --assistant codex${NC}"
  log_event "INFO" "review_file" "path=$REVIEW_FILE_PATH"
fi

TOTAL_TOKENS_FMT=$(format_tokens "$(compute_total_tokens)")

notify_alert "rw [$SESSION_NAME] 완료" "spec ${#SPEC_PATHS[@]}개 — $TOTAL_DURATION — ↓ $TOTAL_TOKENS_FMT"
log_event "INFO" "workflow_end" "session=$SESSION_NAME duration=$TOTAL_DURATION tokens=$TOTAL_TOKENS_FMT completed=${#COMPLETED_PHASES[@]} all_done=$ALL_DONE"
