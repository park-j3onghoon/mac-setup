#!/bin/zsh
# Codex Workflow - Phase 0~19 자동 체이닝 스크립트 (Codex 전용)
#
# 사용법:
#   cw -s <session_name> <spec_paths...> [options]
#
# 예시:
#   cw -s pr2-impl docs/spec_detail_2.md -m src/myapp
#   cw -s big-feature docs/spec_{1..3}.md -m src/app -n 1.5
#   cw -s best docs/spec.md -m src/app --model gpt-5.3-codex --reasoning-effort xhigh
#
# 옵션:
#   -s, --session NAME   세션 이름 (필수)
#   -m, --module PATH    구현 대상 모듈 경로
#   -t, --test PATH      테스트 디렉토리 경로
#   -n, --multiplier N   이터레이션 배수 (기본 1, float 허용)
#   --from N             시작 Phase 번호 (기본 0). 특정 phase부터 재실행할 때 사용
#   --spec-split FILE    큰 스펙을 PR 단위로 분할 (--max-lines N, --review-hours H)
#   --review             세션 리뷰 파일 생성 + 리뷰 세션 시작 (spec 없이 사용 가능)
#   --improve            improve_review.md 기반 워크플로우 개선 세션 시작
#   --improve-file FILE  개선 입력 파일 경로 (기본: 세션의 improve_review.md)
#   --assistant NAME     --review/--improve에서 실행할 도우미 (codex|claude|none, 기본 codex)
#   --model MODEL        codex 실행 모델 (기본: gpt-5.3-codex)
#   --reasoning-effort L codex 추론 강도 (기본: xhigh, 미지정 시 최상)
#   --templates DIR      커스텀 템플릿 디렉토리
#   --dry-run            실제 실행 없이 프롬프트 확인
#   --init               프로젝트 AGENTS.md에 cw 가이드 블록 설치/업데이트
#   --clean              저장된 세션 정리

set -euo pipefail
setopt typeset_silent

# ─── 실행 중 프로세스 정리 ───
ACTIVE_CODEX_PID=""
cleanup() {
  if [[ -n "$ACTIVE_CODEX_PID" ]] && kill -0 "$ACTIVE_CODEX_PID" 2>/dev/null; then
    kill "$ACTIVE_CODEX_PID" 2>/dev/null || true
    wait "$ACTIVE_CODEX_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ─── 경로 설정 ───
GLOBAL_TEMPLATE_DIR="${0:A:h}"
PROJECT_ROOT="$(pwd)"
SESSIONS_BASE_DIR="$PROJECT_ROOT/tmp/codex-workflow"
LOCAL_TEMPLATE_DIR="$PROJECT_ROOT/scripts/codex-workflow"

# ─── 색상 ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── 기본 모델/추론 설정 (최상) ───
DEFAULT_MODEL_NAME="gpt-5.3-codex"
DEFAULT_REASONING_EFFORT="xhigh"
DEFAULT_CLAUDE_MODEL_NAME="opus"
DEFAULT_CLAUDE_EFFORT="high"

# ─── 정체 감지 / 0-토큰 재시도 설정 ───
STALL_THRESHOLD=900             # 장시간 실행 경고 주기 (15분)
STALL_KILL_THRESHOLD=3600       # 로그 무성장 강제 종료 기준 (60분)
LOG_GROWTH_CHECK_INTERVAL=900   # 로그 성장 체크 간격 (15분)
LOG_MEANINGFUL_GROWTH=102400    # 의미있는 로그 성장 임계값 (100KB)
MAX_ZERO_TOKEN_RETRIES=60       # 0-토큰 최대 재시도 (10분 × 60 = 10시간)
ZERO_TOKEN_WAIT=600             # 0-토큰 대기 시간 (10분)

EVENT_LOG_FILE=""

if ! command -v codex >/dev/null 2>&1; then
  echo "${RED}에러: codex CLI를 찾을 수 없습니다. 먼저 설치/로그인 후 다시 실행하세요.${NC}" >&2
  exit 1
fi

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
  local prev=-1
  local matches
  matches=$(sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$log_file" 2>/dev/null \
    | grep -oE '↓ [0-9.]+[kKmM]? tokens' 2>/dev/null || true)
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

    # CLI가 누적 토큰을 반복 렌더링하는 경우가 있어 증가분만 합산한다.
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

log_event() {
  [[ -z "$EVENT_LOG_FILE" ]] && return
  local level=$1 event=$2 detail=${3:-}
  printf '%s [%s] %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$level" "$event" "${detail//$'\n'/ }" >> "$EVENT_LOG_FILE"
}

detect_log_errors() {
  local log_file=$1
  [[ ! -f "$log_file" ]] && return
  local tail_content
  tail_content=$(tail -c 20480 "$log_file" 2>/dev/null | sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\r//g' 2>/dev/null || true)
  [[ -z "$tail_content" ]] && return

  local pattern
  pattern=$(printf '%s\n' "$tail_content" | grep -ioE 'rate.?limit|overloaded|(^|[^0-9])429([^0-9]|$)|(^|[^0-9])503([^0-9]|$)|too many requests|usage.?limit|quota.?exceed|context.?length.?exceed|token.?limit.?(reach|exceed|hit)|ECONNREFUSED|ECONNRESET|ETIMEDOUT|APIError|server.?error|stop hook error|non-blocking status code|no stderr output' | head -1 || true)
  [[ -n "$pattern" ]] && printf '%s\n' "${pattern:l}"
}

get_log_size() {
  local log_file=$1
  [[ ! -f "$log_file" ]] && printf '%s\n' 0 && return
  wc -c < "$log_file" 2>/dev/null || printf '%s\n' 0
}

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

is_token_limit_error() {
  local detected="${1:l}"
  [[ -z "$detected" ]] && return 1
  [[ "$detected" == *"rate"* ]] && return 0
  [[ "$detected" == *"overloaded"* ]] && return 0
  [[ "$detected" == *"too many requests"* ]] && return 0
  [[ "$detected" == *"429"* ]] && return 0
  [[ "$detected" == *"503"* ]] && return 0
  [[ "$detected" == *"usage"* ]] && return 0
  [[ "$detected" == *"quota"* ]] && return 0
  [[ "$detected" == *"context"* ]] && return 0
  [[ "$detected" == *"token"* ]] && return 0
  return 1
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

# spec 경로를 절대 경로로 변환 + 정렬하여 fingerprint 생성
compute_spec_fingerprint() {
  for spec in "$@"; do
    printf '%s\n' "${spec:A}"
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

find_context_source_file() {
  local file_name=$1

  if [[ -f "$SESSION_DIR/$file_name" ]]; then
    printf '%s\n' "$SESSION_DIR/$file_name"
    return 0
  fi

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
    "cw-plan.md"
    "cw-checklist.md"
    "cw-spec-digest.md"
    "cw-notes.md"
  )
  local restored_count=0
  local missing_count=0

  mkdir -p "$SESSION_DIR"

  local file_name
  for file_name in "${context_files[@]}"; do
    local dest_path="$SESSION_DIR/$file_name"
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
    echo "${CYAN}세션 컨텍스트 파일 ${restored_count}개 자동 복원${NC}"
  fi
  if (( missing_count > 0 )); then
    echo "${YELLOW}경고: 세션 컨텍스트 파일 ${missing_count}개를 자동 복원하지 못했습니다.${NC}" >&2
    echo "${YELLOW}      --from ${START_PHASE} 실행 품질을 위해 세션 파일 확인을 권장합니다.${NC}" >&2
  fi
}

list_review_session_candidates() {
  local session_name=$1
  local -a candidates=("$SESSIONS_BASE_DIR/$session_name")
  typeset -A seen=()
  local path
  for path in "${candidates[@]}"; do
    [[ -z "$path" ]] && continue
    [[ -n "${seen[$path]:-}" ]] && continue
    seen[$path]=1
    printf '%s\n' "$path"
  done
}

resolve_review_session_dir() {
  local session_name=$1
  local candidate
  while IFS= read -r candidate; do
    [[ -d "$candidate" ]] || continue
    printf '%s\n' "$candidate"
    return 0
  done < <(list_review_session_candidates "$session_name")
  return 1
}

print_review_session_candidates() {
  local session_name=$1
  echo "${YELLOW}검색한 세션 경로:${NC}" >&2
  local candidate
  while IFS= read -r candidate; do
    echo "  - $candidate" >&2
  done < <(list_review_session_candidates "$session_name")
}

compute_spec_lines() {
  cat "${SPEC_PATHS[@]}" 2>/dev/null | wc -l | tr -d '[:space:]'
}

# spec 줄 수에 따른 이터레이션 추가분 (300줄마다 +1)
compute_spec_addend() {
  local lines=$1
  printf '%s\n' $(( lines / 300 ))
}

# 메인 브랜치 자동 감지


detect_main_branch() {
  if git show-ref --verify --quiet refs/heads/main 2>/dev/null; then
    printf '%s\n' "main"
  elif git show-ref --verify --quiet refs/heads/master 2>/dev/null; then
    printf '%s\n' "master"
  else
    printf '%s\n' "HEAD"
  fi
}

# 이터레이션 계산: ceil((base + spec_addend) × multiplier)
compute_iterations() {
  local base=$1 multiplier=$2 addend=$3
  awk -v b="$base" -v m="$multiplier" -v a="$addend" 'BEGIN{
    v = (b + a) * m; printf "%d", (v == int(v)) ? v : int(v) + 1
  }'
}

compute_max_retries() {
  local iterations=$1
  local retries=$(( iterations * 3 ))
  (( retries > 9 )) && retries=9
  printf '%s\n' "$retries"
}

check_promise_in_log() {
  local log_file=$1 promise=$2
  local sed_clean='s/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1b][^\x07]*\x07//g; s/\x1b(B//g; s/\r//g'

  # Codex 출력이 <promise>...</promise> 형태인 경우를 먼저 허용한다.
  if sed "$sed_clean" "$log_file" 2>/dev/null \
     | grep -qiE "<promise>[[:space:]]*${promise// /[[:space:]]+}[[:space:]]*</promise>" 2>/dev/null; then
    return 0
  fi

  if sed "$sed_clean" "$log_file" 2>/dev/null \
     | grep -v 'completion-promise' | grep -v '<promise>' | grep -qF "$promise" 2>/dev/null; then
    return 0
  fi

  local promise_nospace="${promise// /}"
  sed "${sed_clean}; s/ //g" "$log_file" 2>/dev/null \
    | grep -v 'completion.*promise' | grep -v '<promise>' | grep -qF "$promise_nospace" 2>/dev/null
}

# 템플릿 파일 탐색 (로컬 우선 → 글로벌 폴백)
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

  printf '%s\n' ""
}

# 에이전트 문서 탐색 (커스텀 우선 → 로컬 → 글로벌)
find_agent_doc() {
  local agent_name=$1
  local custom_dir=$2

  if [[ -n "$custom_dir" ]] && [[ -f "$custom_dir/agents/${agent_name}.md" ]]; then
    printf '%s\n' "$custom_dir/agents/${agent_name}.md"
    return
  fi

  if [[ -f "$LOCAL_TEMPLATE_DIR/agents/${agent_name}.md" ]]; then
    printf '%s\n' "$LOCAL_TEMPLATE_DIR/agents/${agent_name}.md"
    return
  fi

  if [[ -f "$GLOBAL_TEMPLATE_DIR/agents/${agent_name}.md" ]]; then
    printf '%s\n' "$GLOBAL_TEMPLATE_DIR/agents/${agent_name}.md"
    return
  fi

  printf '%s\n' ""
}

# 템플릿의 Task(subagent_type='...') 목록 추출
extract_task_agent_names() {
  local template_content=$1
  print -r -- "$template_content" \
    | grep -oE "Task\\(subagent_type='[^']+'\\)" \
    | sed -E "s/Task\\(subagent_type='([^']+)'\\)/\\1/" \
    | sort -u
}

# Task(subagent_type='...') 대응 에이전트 문서를 프롬프트에 첨부
build_task_agent_guides() {
  local template_content=$1
  local custom_dir=$2
  local names
  names=$(extract_task_agent_names "$template_content")
  [[ -z "$names" ]] && return 0

  local output=""
  local agent_name
  while IFS= read -r agent_name; do
    [[ -z "$agent_name" ]] && continue
    local doc_path
    doc_path=$(find_agent_doc "$agent_name" "$custom_dir")
    if [[ -n "$doc_path" ]]; then
      output+=$'\n'"### Agent Reference: ${agent_name}"$'\n'
      output+="source: ${doc_path}"$'\n\n'
      output+="$(<"$doc_path")"$'\n'
    else
      output+=$'\n'"### Agent Reference: ${agent_name}"$'\n'
      output+="source: (not found)"$'\n'
      output+="- 경고: 해당 에이전트 문서를 찾지 못했다. 현재 phase 템플릿 지시를 기준으로 직접 판단해 수행한다."$'\n'
    fi
  done <<< "$names"

  printf '%s\n' "$output"
}

write_cw_agents_block() {
  cat <<'EOF'
<!-- CW_WORKFLOW_GUIDE_START -->
## Codex Workflow (`cw`)

- Codex는 `.codex/agents`를 표준 자동 로딩 경로로 사용하지 않는다.
- `cw`는 phase 템플릿의 `Task(subagent_type='...')`를 해석할 때,
  - `scripts/codex-workflow/agents/<name>.md` (프로젝트 override) 또는
  - `codex-workflow/agents/<name>.md` (기본 템플릿)
  문서를 프롬프트에 자동 첨부해 참조한다.
- 장기/전역 규칙은 `AGENTS.md`와 Codex Skills를 기준으로 관리한다.
<!-- CW_WORKFLOW_GUIDE_END -->
EOF
}

install_or_update_project_agents_md() {
  local agents_md="$PROJECT_ROOT/AGENTS.md"
  local start_marker="<!-- CW_WORKFLOW_GUIDE_START -->"
  local end_marker="<!-- CW_WORKFLOW_GUIDE_END -->"
  local tmp_file
  tmp_file="$(mktemp)"

  if [[ -f "$agents_md" ]]; then
    local in_block=0
    local replaced=0
    while IFS= read -r line || [[ -n "$line" ]]; do
      if [[ "$line" == "$start_marker" ]]; then
        in_block=1
        replaced=1
        write_cw_agents_block >> "$tmp_file"
        continue
      fi
      if [[ "$line" == "$end_marker" ]]; then
        in_block=0
        continue
      fi
      if (( ! in_block )); then
        printf '%s\n' "$line" >> "$tmp_file"
      fi
    done < "$agents_md"

    if (( ! replaced )); then
      [[ -s "$tmp_file" ]] && printf '\n' >> "$tmp_file"
      write_cw_agents_block >> "$tmp_file"
    fi
  else
    cat > "$tmp_file" <<'EOF'
# AGENTS.md

EOF
    write_cw_agents_block >> "$tmp_file"
  fi

  mv "$tmp_file" "$agents_md"
  printf '%s\n' "$agents_md"
}

workspace_fingerprint() {
  {
    git diff --no-ext-diff --binary 2>/dev/null || true
    git diff --cached --no-ext-diff --binary 2>/dev/null || true
    git ls-files --others --exclude-standard -z 2>/dev/null \
      | while IFS= read -r -d '' f; do
          printf 'UNTRACKED:%s\n' "$f"
          shasum "$f" 2>/dev/null || true
        done
  } | shasum | awk '{print $1}'
}

run_spec_split() {
  local spec_file=$1
  local max_lines=${2:-500}
  local review_hours=${3:-1.5}

  [[ ! -f "$spec_file" ]] && echo "${RED}에러: $spec_file 없음${NC}" >&2 && return 1
  if ! printf '%s' "$max_lines" | grep -qE '^[1-9][0-9]*$'; then
    echo "${RED}에러: --max-lines 값은 1 이상의 정수여야 합니다: $max_lines${NC}" >&2
    return 1
  fi
  if ! printf '%s' "$review_hours" | grep -qE '^[0-9]+\.?[0-9]*$'; then
    echo "${RED}에러: --review-hours 값은 양수 숫자여야 합니다: $review_hours${NC}" >&2
    return 1
  fi
  if awk -v h="$review_hours" 'BEGIN{exit (h > 0) ? 0 : 1}'; then :; else
    echo "${RED}에러: --review-hours 값은 0보다 커야 합니다: $review_hours${NC}" >&2
    return 1
  fi

  local target_review_minutes
  target_review_minutes=$(awk -v h="$review_hours" 'BEGIN{v=h*60; printf "%d", (v == int(v)) ? v : int(v) + 1}')
  local review_min=$((target_review_minutes - 30))
  local review_max=$((target_review_minutes + 30))
  (( review_min < 45 )) && review_min=45
  (( review_max > 240 )) && review_max=240

  local total
  total=$(wc -l < "$spec_file" | tr -d ' ')
  if (( total <= max_lines )); then
    echo "${GREEN}분할 불필요: ${total}줄 (제한: ${max_lines}줄, 리뷰 목표: ${review_min}~${review_max}분)${NC}"
    return 0
  fi

  local -a h2_positions
  h2_positions=(${(f)"$(grep -n '^## [^#]' "$spec_file" | cut -d: -f1)"})

  if [[ ${#h2_positions[@]} -eq 0 ]]; then
    echo "${RED}에러: ## 헤더가 없어 섹션을 식별할 수 없습니다.${NC}" >&2
    return 1
  fi

  local preamble_end=$((h2_positions[1] - 1))
  (( h2_positions[1] <= 1 )) && preamble_end=0
  local preamble_lines=$preamble_end
  local body_max=$((max_lines - preamble_lines))
  if (( body_max <= 0 )); then
    echo "${RED}에러: --max-lines(${max_lines})가 프리앰블(${preamble_lines})보다 작거나 같습니다.${NC}" >&2
    return 1
  fi

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
  local ai_prompt_file ai_result ai_exit
  ai_prompt_file="$(mktemp)"
  printf '%s' "$ai_prompt" > "$ai_prompt_file"

  local -a split_cmd
  split_cmd=(codex exec --full-auto --color never --cd "$PROJECT_ROOT" --model "$MODEL_NAME")
  split_cmd+=(-c "model_reasoning_effort=\"$REASONING_EFFORT\"")
  split_cmd+=(-)

  ai_result="$("${split_cmd[@]}" < "$ai_prompt_file" 2>/dev/null)"
  ai_exit=$?
  rm -f "$ai_prompt_file"

  if [[ $ai_exit -ne 0 ]] || [[ -z "$ai_result" ]]; then
    echo "${RED}에러: AI 호출 실패${NC}" >&2
    return 1
  fi

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
    return 1
  fi

  local all_nums=""
  for g in "${group_nums_list[@]}"; do
    all_nums+="$(printf '%s\n' "$g" | tr ',' '\n')"$'\n'
  done
  local sorted_nums expected_nums
  sorted_nums=$(printf '%s' "$all_nums" | grep -E '^[0-9]+$' | sort -n)
  expected_nums=$(seq 1 $sec_count)
  if [[ "$sorted_nums" != "$expected_nums" ]]; then
    echo "${RED}에러: AI 그룹핑 검증 실패 (섹션 누락/중복)${NC}" >&2
    echo "  기대: $(seq 1 $sec_count | tr '\n' ',')" >&2
    echo "  실제: $(printf '%s' "$sorted_nums" | tr '\n' ',')" >&2
    return 1
  fi
  for (( i=1; i<=${#group_nums_list[@]}; i++ )); do
    if ! printf '%s' "${group_review_mins[$i]}" | grep -qE '^[0-9]+$'; then
      group_review_mins[$i]="$target_review_minutes"
    fi
    (( group_review_mins[$i] < 30 )) && group_review_mins[$i]=30
    [[ -z "${group_pr_titles[$i]}" ]] && group_pr_titles[$i]="PR $i"
  done

  local base="${spec_file%.md}"
  local split_num=${#group_nums_list[@]}
  local -a split_line_counts split_sec_labels
  local plan_file="${base}.split-plan.md"

  for (( i=1; i<=split_num; i++ )); do
    local out_file="${base}.split-${i}.md"
    : > "$out_file"

    if (( preamble_end > 0 )); then
      sed -n "1,${preamble_end}p" "$spec_file" >> "$out_file"
      printf '\n' >> "$out_file"
    fi

    printf '> **PR 단위**: PR %s - %s\n' "$i" "${group_pr_titles[$i]}" >> "$out_file"
    printf '> **예상 리뷰 시간**: 약 %s분 (목표 %s분)\n' "${group_review_mins[$i]}" "$target_review_minutes" >> "$out_file"
    if [[ -n "${group_context_list[$i]}" ]]; then
      printf '> **다른 PR 참조 맥락**: %s\n' "${group_context_list[$i]}" >> "$out_file"
    fi
    printf '\n---\n\n' >> "$out_file"

    local -a nums
    nums=(${(s:,:)group_nums_list[$i]})
    local sec_label_parts=()
    local n
    for n in "${nums[@]}"; do
      sed -n "${sec_starts[$n]},${sec_ends[$n]}p" "$spec_file" >> "$out_file"
      printf '\n' >> "$out_file"
      sec_label_parts+=("${sec_names[$n]}")
    done
    split_sec_labels+=("${(j:, :)sec_label_parts}")

    local file_lines
    file_lines=$(wc -l < "$out_file" | tr -d ' ')
    split_line_counts+=("$file_lines")
  done

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
  local session_base
  session_base=$(basename "${base}")
  for (( i=1; i<=split_num; i++ )); do
    echo "  cw -s ${session_base}-${i} ${base}.split-${i}.md -m src/module"
  done
  echo ""
  return 0
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

generate_deep_review_file() {
  local review_title_prefix=$1
  local review_filename=$2
  local review_file="$SESSION_DIR/$review_filename"
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

  local progress_pct
  if [[ "$session_status" == "completed" ]]; then
    progress_pct=100
  else
    progress_pct=$(((current_phase + 1) * 100 / 20))
    (( progress_pct > 99 )) && progress_pct=99
    (( progress_pct < 0 )) && progress_pct=0
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

  typeset -A file_status file_added file_deleted file_bundle file_focus file_hunks file_hunk_count
  local file_stat file_path
  while IFS=$'\t' read -r file_stat file_path; do
    [[ -z "$file_path" ]] && continue
    case "$file_stat" in
      A) file_status[$file_path]="created" ;;
      M) file_status[$file_path]="modified" ;;
      D) file_status[$file_path]="deleted" ;;
      *) file_status[$file_path]="$file_stat" ;;
    esac
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
  local -a contract_files=() core_files=() test_files=() ops_files=()
  for file_path in "${changed_paths[@]}"; do
    case "${file_status[$file_path]}" in
      created) created_count=$((created_count + 1)) ;;
      modified) modified_count=$((modified_count + 1)) ;;
      deleted) deleted_count=$((deleted_count + 1)) ;;
    esac

    local bundle_key="(root)"
    if [[ "$file_path" == */*/* ]]; then
      local first_dir="${file_path%%/*}"
      local rest_path="${file_path#*/}"
      local second_dir="${rest_path%%/*}"
      bundle_key="${first_dir}/${second_dir}"
    elif [[ "$file_path" == */* ]]; then
      bundle_key="${file_path%%/*}"
    fi
    file_bundle[$file_path]="$bundle_key"

    case "$file_path" in
      *"/migrations/"*|*.sql|*schema*|*openapi*|*.proto|*/dto.py|*/models/*|*/domain/*constants*.py|*/domain/*repositories.py)
        contract_files+=("$file_path")
        file_focus[$file_path]="스키마/계약 변경과 하위 호환성 검증"
        ;;
      */tests/*|tests/*|*_test.py|test_*)
        test_files+=("$file_path")
        file_focus[$file_path]="요구사항 커버리지와 회귀 방지 수준 검증"
        ;;
      docs/*|*.md|*/management/commands/*|*/scripts/*|*.sh|*.yml|*.yaml|*.toml|*.json|*.ini)
        ops_files+=("$file_path")
        file_focus[$file_path]="운영 절차/문서/설정 값 정합성과 실행 안정성 검증"
        ;;
      *)
        core_files+=("$file_path")
        file_focus[$file_path]="도메인 로직, 예외 처리, 부작용 검증"
        ;;
    esac
  done

  local diff_content hunk_lines hunk_count
  for file_path in "${changed_paths[@]}"; do
    diff_content=$(git diff --unified=0 --no-color "$base_ref" -- "$file_path" 2>/dev/null || true)
    hunk_lines=$(printf '%s\n' "$diff_content" | grep '^@@' || true)
    hunk_lines=$(printf '%s\n' "$hunk_lines" | sed '/^$/d' || true)
    if [[ -n "$hunk_lines" ]]; then
      hunk_count=$(printf '%s\n' "$hunk_lines" | wc -l | tr -d ' ')
    else
      hunk_count=0
    fi
    file_hunks[$file_path]="$hunk_lines"
    file_hunk_count[$file_path]="$hunk_count"
  done

  local -a evidence_candidates=(
    "$SESSION_DIR/rw-spec-digest.md"
    "$SESSION_DIR/rw-checklist.md"
    "$SESSION_DIR/rw-notes.md"
    "$SESSION_DIR/rw-review.md"
    "$SESSION_DIR/cw-spec-digest.md"
    "$SESSION_DIR/cw-checklist.md"
    "$SESSION_DIR/cw-notes.md"
    "$SESSION_DIR/cw-review.md"
    "$SESSION_DIR/rw-plan.md"
    "$SESSION_DIR/cw-plan.md"
  )
  local -a evidence_files=()
  local evidence_path
  for evidence_path in "${evidence_candidates[@]}"; do
    [[ -f "$evidence_path" ]] && evidence_files+=("$evidence_path")
  done

  emit_group_file_checklist() {
    local group_title=$1
    local group_purpose=$2
    shift 2
    local -a group_files=("$@")

    echo "## ${group_title}"
    echo "### 목적"
    echo "- ${group_purpose}"
    echo "### 파일 수"
    echo "- ${#group_files[@]}개"
    if (( ${#group_files[@]} == 0 )); then
      echo "- 변경 파일 없음"
      echo ""
      return 0
    fi

    typeset -A bundle_counts
    local group_file bundle_name
    for group_file in "${group_files[@]}"; do
      bundle_name="${file_bundle[$group_file]:-(root)}"
      bundle_counts[$bundle_name]=$(( ${bundle_counts[$bundle_name]:-0} + 1 ))
    done

    local -a bundle_names=(${(k)bundle_counts})
    bundle_names=(${(on)bundle_names})

    echo "### 묶음(폴더) 요약"
    for bundle_name in "${bundle_names[@]}"; do
      echo "- \`${bundle_name}\`: ${bundle_counts[$bundle_name]}개"
    done
    echo ""

    local bundle_file file_status_text add_count del_count hunk_line hunk_item_count change_index change_context
    for bundle_name in "${bundle_names[@]}"; do
      echo "### Bundle: \`${bundle_name}\`"
      local -a bundle_files=()
      for group_file in "${group_files[@]}"; do
        [[ "${file_bundle[$group_file]:-(root)}" == "$bundle_name" ]] && bundle_files+=("$group_file")
      done
      bundle_files=(${(on)bundle_files})

      for bundle_file in "${bundle_files[@]}"; do
        file_status_text="${file_status[$bundle_file]:-unknown}"
        add_count="${file_added[$bundle_file]:-0}"
        del_count="${file_deleted[$bundle_file]:-0}"
        hunk_item_count="${file_hunk_count[$bundle_file]:-0}"

        echo "#### File: \`${bundle_file}\`"
        echo "- 상태: ${file_status_text} | 라인: +${add_count}/-${del_count}"
        echo "- 리뷰 포커스: ${file_focus[$bundle_file]:-요구사항 반영/부작용 검증}"
        echo "- 파일 체크리스트"
        echo "- [ ] WHAT: 무엇이 바뀌었는지(입력/출력/상태/오류)를 기록했다."
        echo "- [ ] HOW: 어떻게 바뀌었는지(흐름/의존성/레이어)를 기록했다."
        echo "- [ ] WHY: 왜 바뀌었는지(스펙 절/REQ)를 연결했다."
        echo "- [ ] VERIFY: 검증 근거(테스트/로그/수동 절차)를 기록했다."
        echo "- [ ] SIDE EFFECT: 인접 모듈/기존 호출자 영향 여부를 확인했다."
        echo "- 변경 체크포인트: ${hunk_item_count}개"

        if (( hunk_item_count == 0 )); then
          echo "- [ ] HUNK 정보 없음: 파일 전체 diff 기준으로 WHAT/HOW/WHY를 작성했다."
        else
          change_index=1
          while IFS= read -r hunk_line; do
            [[ -z "$hunk_line" ]] && continue
            change_context=$(printf '%s\n' "$hunk_line" | sed -E 's/^@@[^@]*@@[[:space:]]*//')
            if [[ -z "$change_context" ]] || [[ "$change_context" == "$hunk_line" ]]; then
              change_context="(컨텍스트 없음)"
            fi
            echo ""
            echo "##### Change ${change_index}"
            echo "- 범위: \`${hunk_line}\`"
            echo "- 컨텍스트: ${change_context}"
            echo "- [ ] WHAT:"
            echo "- [ ] HOW:"
            echo "- [ ] WHY:"
            echo "- [ ] VERIFY:"
            change_index=$((change_index + 1))
          done <<< "${file_hunks[$bundle_file]}"
        fi

        echo "- 파일 판정"
        echo "- [ ] PASS"
        echo "- [ ] PASS WITH COMMENT"
        echo "- [ ] FAIL"
        echo ""
      done
    done
  }

  {
    echo "# ${review_title_prefix} Review Guide - ${SESSION_NAME} (File-Centric Checklist)"
    echo ""
    echo "## 문서 목적"
    echo "- 변경 파일을 파일 단위로 리뷰하면서, 각 변경 묶음(hunk)마다 WHAT/HOW/WHY를 체크하기 위한 문서."
    echo "- 폴더 묶음(Bundle)으로 순서를 잡고, 파일 판정과 최종 판정을 분리해 누락을 줄인다."
    echo ""
    echo "## 전체 작업 중 현재 위치"
    echo "- 상태: \`${session_status}\`"
    echo "- 현재/마지막 Phase: \`${current_phase}\` (${current_phase_name})"
    echo "- 진행률(0~19 기준): ${progress_pct}%"
    echo "- 비교 기준: \`${base_ref}\`..HEAD"
    echo "- 변경 파일: ${changed_count}개 (created ${created_count}, modified ${modified_count}, deleted ${deleted_count})"
    echo "- 그룹 요약: 계약 ${#contract_files[@]}개 / 핵심 ${#core_files[@]}개 / 테스트 ${#test_files[@]}개 / 운영 ${#ops_files[@]}개"
    echo "- 문서 생성 시각: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "## 자동 수집 근거"
    echo "### 스펙 경로"
    if (( ${#spec_entries[@]} == 0 )); then
      echo "- state.env에 spec 정보가 없어 수동 확인 필요"
    else
      local spec_path
      for spec_path in "${spec_entries[@]}"; do
        echo "- \`${spec_path}\`"
      done
    fi
    echo ""
    echo "### 세션 근거 파일"
    if (( ${#evidence_files[@]} == 0 )); then
      echo "- 자동 탐지된 세션 근거 파일 없음"
    else
      for evidence_path in "${evidence_files[@]}"; do
        echo "- \`${evidence_path}\`"
      done
    fi
    echo ""
    echo "## 리뷰 진행 규칙"
    echo "1. Group 0/1을 먼저 끝낸 뒤 Group 2~5를 파일 단위로 리뷰한다."
    echo "2. 각 파일에서 WHAT/HOW/WHY/VERIFY/SIDE EFFECT를 모두 체크한다."
    echo "3. 파일 내 Change 체크포인트를 채우기 전에는 파일 판정을 PASS로 두지 않는다."
    echo "4. FAIL 파일이 1개라도 있으면 Group 6 최종 판정을 \`REQUEST CHANGES\`로 둔다."
    echo ""
    echo "## Group 0. 범위/베이스라인 확인"
    echo "### 체크리스트"
    echo "- [ ] 리뷰 기준 커밋(\`${base_ref}\`..HEAD)을 확정했다."
    echo "- [ ] 리뷰 대상 파일 목록 ${changed_count}개를 확정했다."
    echo "- [ ] 파일 누락 방지를 위해 Bundle 순서를 확정했다."
    echo "### 판정"
    echo "- [ ] PASS"
    echo "- [ ] PASS WITH COMMENT"
    echo "- [ ] FAIL"
    echo ""
    echo "## Group 1. 세션/스펙 정합성"
    echo "### 목적"
    echo "- 세션 산출물의 요구사항 목록과 실제 스펙 문서가 일치하는지 확인한다."
    echo "### 변화 요약"
    echo "- 세션 근거 파일: ${#evidence_files[@]}개"
    if (( ${#evidence_files[@]} == 0 )); then
      echo "- 근거 파일 없음(수동 확인 필요)"
    else
      for evidence_path in "${evidence_files[@]}"; do
        echo "- \`${evidence_path}\`"
      done
    fi
    echo "### 체크리스트"
    echo "- [ ] 세션 체크리스트/노트의 REQ 목록을 확보했다."
    echo "- [ ] 파일 리뷰 시 사용할 spec 절/REQ 링크 형식을 정했다."
    echo "- [ ] 스펙의 금지/제약 조건을 체크 항목에 포함했다."
    echo "### 판정"
    echo "- [ ] PASS"
    echo "- [ ] PASS WITH COMMENT"
    echo "- [ ] FAIL"
    echo ""
    emit_group_file_checklist "Group 2. 계약/스키마/API (파일 단위)" "외부 계약/스키마 변경 파일을 파일 단위로 검증한다." "${contract_files[@]}"
    emit_group_file_checklist "Group 3. 핵심 구현 로직 (파일 단위)" "핵심 도메인/애플리케이션 로직 파일을 파일 단위로 검증한다." "${core_files[@]}"
    emit_group_file_checklist "Group 4. 테스트/회귀 보호 (파일 단위)" "테스트 파일을 파일 단위로 검증하고 요구사항 커버리지를 확인한다." "${test_files[@]}"
    emit_group_file_checklist "Group 5. 문서/설정/운영 경로 (파일 단위)" "운영/문서/설정 파일을 파일 단위로 검증한다." "${ops_files[@]}"
    echo "## Group 6. 잔여 리스크 및 최종 판정"
    echo "### 파일 단위 종합 체크리스트"
    echo "- [ ] FAIL 파일 목록을 정리했다."
    echo "- [ ] 각 FAIL 파일의 수정 액션을 정의했다."
    echo "- [ ] 재검증 필요 파일 목록을 분리했다."
    echo "### 최종 판정"
    echo "- [ ] APPROVE"
    echo "- [ ] REQUEST CHANGES"
    echo "- [ ] COMMENT ONLY"
    echo "- 한 줄 요약: "
    echo "- 블로킹 이슈(파일 경로 포함): "
    echo "- 후속 액션(담당/기한): "
    echo ""
    echo "## Group 7. 워크플로우 환류(프로젝트 독립)"
    echo "### 기록 파일"
    echo "- \`${SESSION_DIR}/improve_review.md\`"
    echo "### 체크리스트"
    echo "- [ ] 프로젝트 독립적으로 재사용 가능한 개선 항목을 최소 1개 이상 추출했다."
    echo "- [ ] 각 항목의 개선 포인트(문제/개선/효과)를 명시했다."
    echo "- [ ] 각 항목에 WHY(효과)/리스크/검증 방법을 작성했다."
    echo "- [ ] 추출 항목을 improve_review.md 세션 블록에 반영했다."
  } > "$review_file"

  rm -f "$diff_status_file" "$diff_numstat_file"
  printf '%s\n' "$review_file"
}

ensure_improve_review_file() {
  local improve_file="$SESSION_DIR/improve_review.md"
  if [[ ! -f "$improve_file" ]]; then
    cat > "$improve_file" <<'EOF'
# Improve Review

코드 리뷰에서 도출한 "프로젝트 독립적" 개선 항목을 누적하는 파일.
이 파일은 워크플로우/리뷰 프로세스 자체를 개선하기 위한 용도다.

기록 규칙:
1. 프로젝트 전용 정책/도메인 규칙은 제외한다.
2. 항목마다 문제, 개선안, 기대효과, 검증방법을 남긴다.
3. 상태는 proposed/applied/rejected 중 하나로 관리한다.
EOF
  fi
  printf '%s\n' "$improve_file"
}

append_improve_review_session_template() {
  local improve_file=$1
  local review_kind=$2
  local review_file=$3
  local marker="<!-- session:${SESSION_NAME}|kind:${review_kind} -->"

  if grep -qF "$marker" "$improve_file" 2>/dev/null; then
    printf '%s\n' "$improve_file"
    return 0
  fi

  {
    echo ""
    echo "## ${SESSION_NAME} | ${review_kind} | $(date '+%Y-%m-%d %H:%M:%S')"
    echo "$marker"
    echo "- Source review file: \`${review_file}\`"
    echo "- Source session dir: \`${SESSION_DIR}\`"
    echo ""
    echo "### Candidate 1"
    echo "- Problem:"
    echo "- Improvement:"
    echo "- Expected impact:"
    echo "- Validation plan:"
    echo "- Status: proposed"
    echo ""
    echo "### Candidate 2"
    echo "- Problem:"
    echo "- Improvement:"
    echo "- Expected impact:"
    echo "- Validation plan:"
    echo "- Status: proposed"
  } >> "$improve_file"

  printf '%s\n' "$improve_file"
}

generate_improve_instructions_file() {
  local workflow_label=$1
  local improve_source_file=$2
  local instructions_file="$SESSION_DIR/${workflow_label:l}-improve-instructions.md"
  local result_file="$SESSION_DIR/${workflow_label:l}-improve-result.md"
  local workflow_script="$GLOBAL_TEMPLATE_DIR/run-workflow.sh"
  local workflow_root="$GLOBAL_TEMPLATE_DIR"

  cat > "$instructions_file" <<EOF
# ${workflow_label} Improve Instructions

## Inputs
- Improve source: \`${improve_source_file}\`
- Workflow script: \`${workflow_script}\`
- Workflow root: \`${workflow_root}\`

## Goal
- improve_review.md의 항목을 반영해 ${workflow_label} 워크플로우를 개선한다.
- 기존 기능/동작/옵션은 절대 제거하지 않고 100% 유지한다.
- 개선은 확장 방식으로만 반영한다.

## Mandatory Rules
1. 기존 phase/agent/옵션/검증 로직은 보존한다.
2. 변경 범위가 커지면 phase를 분리하고, 분리된 phase별 agent를 새로 만든다.
3. 단일 대규모 수정 대신 작은 단위로 분할해 점진적으로 반영한다.
4. backward compatibility를 깨는 변경은 금지한다.
5. 수정 후 최소 \`zsh -n ${workflow_script}\` 문법 검증을 수행한다.

## Work Steps
1. improve_review.md 항목을 actionable task로 정리한다.
2. task를 phase/agent/스크립트 개선 항목으로 매핑한다.
3. 필요한 파일을 생성/수정하되 기존 기능은 유지한다.
4. 변경 결과와 검증 결과를 문서화한다.

## Output
- 결과 요약 파일: \`${result_file}\`
- 요약에는 아래를 반드시 포함한다.
  - 적용한 개선 항목
  - 보존한 기존 기능 체크
  - 분리된 phase/agent 목록(있다면)
  - 남은 TODO
EOF

  printf '%s\n' "$instructions_file"
}

launch_improve_assistant() {
  local assistant=${1:-codex}
  local instructions_file=$2
  local prompt="Read ${instructions_file} and execute all steps end-to-end. Preserve all existing behavior and apply improvements only by extension."
  case "$assistant" in
    codex)
      command -v codex >/dev/null 2>&1 || { echo "${YELLOW}경고: codex 미설치${NC}" >&2; return 0; }
      codex -C "$PROJECT_ROOT" --model "$MODEL_NAME" \
        -c "model_reasoning_effort=\"$REASONING_EFFORT\"" "$prompt"
      ;;
    claude)
      command -v claude >/dev/null 2>&1 || { echo "${YELLOW}경고: claude 미설치${NC}" >&2; return 0; }
      claude --model "$DEFAULT_CLAUDE_MODEL_NAME" --effort "$DEFAULT_CLAUDE_EFFORT" "$prompt"
      ;;
    none) return 0 ;;
    *)
      echo "${RED}에러: 지원하지 않는 assistant입니다: $assistant (codex|claude|none)${NC}" >&2
      return 1
      ;;
  esac
}

# review 모드에서 즉시 사용하기 위한 버전.
# (아래쪽에서 동일 이름 함수가 다시 정의되며, 두 정의 모두 공통 생성기를 호출한다)
generate_review_file() {
  generate_deep_review_file "CW" "cw-review.md"
}

launch_review_assistant() {
  local assistant=${1:-codex}
  local review_file=$2
  local prompt="Read ${review_file} first. Follow Group 0 to Group 7 order. In Group 2 to Group 5, review exactly one file at a time and WAIT for user confirmation before moving to the next file. For each file, fill WHAT/HOW/WHY/VERIFY/SIDE EFFECT checks. At the end (Group 7), extract project-independent improvements and write them to ${SESSION_DIR}/improve_review.md in this session block."
  case "$assistant" in
    codex)
      command -v codex >/dev/null 2>&1 || { echo "${YELLOW}경고: codex 미설치${NC}" >&2; return 0; }
      codex -C "$PROJECT_ROOT" --model "$MODEL_NAME" \
        -c "model_reasoning_effort=\"$REASONING_EFFORT\"" "$prompt"
      ;;
    claude)
      command -v claude >/dev/null 2>&1 || { echo "${YELLOW}경고: claude 미설치${NC}" >&2; return 0; }
      claude --model "$DEFAULT_CLAUDE_MODEL_NAME" --effort "$DEFAULT_CLAUDE_EFFORT" "$prompt"
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
IMPROVE_MODE=false
IMPROVE_FILE=""
REVIEW_ASSISTANT="codex"

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
    --improve)
      IMPROVE_MODE=true
      shift
      ;;
    --improve-file)
      IMPROVE_FILE="$2"
      shift 2
      ;;
    --assistant)
      REVIEW_ASSISTANT="$2"
      shift 2
      ;;
    --spec-split)
      split_spec_file="${2:-}"
      [[ -z "$split_spec_file" || "$split_spec_file" == -* ]] && echo "${RED}에러: spec 파일 경로 필요${NC}" >&2 && exit 1
      shift 2
      split_max_lines=500
      split_review_hours="1.5"
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --max-lines)
            split_max_lines="${2:-}"
            if ! printf '%s' "$split_max_lines" | grep -qE '^[1-9][0-9]*$'; then
              echo "${RED}에러: --max-lines 값은 1 이상의 정수여야 합니다: $split_max_lines${NC}" >&2
              exit 1
            fi
            shift 2
            ;;
          --review-hours)
            split_review_hours="${2:-}"
            if ! printf '%s' "$split_review_hours" | grep -qE '^[0-9]+\.?[0-9]*$'; then
              echo "${RED}에러: --review-hours 값은 양수 숫자여야 합니다: $split_review_hours${NC}" >&2
              exit 1
            fi
            if awk -v h="$split_review_hours" 'BEGIN{exit (h > 0) ? 0 : 1}'; then :; else
              echo "${RED}에러: --review-hours 값은 0보다 커야 합니다: $split_review_hours${NC}" >&2
              exit 1
            fi
            shift 2
            ;;
          *)
            break
            ;;
        esac
      done
      run_spec_split "$split_spec_file" "$split_max_lines" "$split_review_hours"
      exit $?
      ;;
    --model)
      MODEL_NAME="$2"
      shift 2
      ;;
    --reasoning-effort)
      REASONING_EFFORT="$2"
      shift 2
      ;;
    --clean)
      sessions=($SESSIONS_BASE_DIR/*(N/))
      if [[ ${#sessions[@]} -eq 0 ]]; then
        echo "${YELLOW}삭제할 세션이 없습니다.${NC}"
        exit 0
      fi
      echo "${CYAN}세션 목록:${NC}"
      for dir in "${sessions[@]}"; do
        name=$(basename "$dir")
        size=$(du -sh "$dir" 2>/dev/null | cut -f1)
        files=$(ls "$dir" 2>/dev/null | wc -l | tr -d ' ')
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
      echo "${CYAN}프로젝트 AGENTS.md에 cw 가이드를 설치/업데이트합니다...${NC}"
      agents_md_path=$(install_or_update_project_agents_md)
      echo "${GREEN}완료! AGENTS.md 갱신: ${agents_md_path}${NC}"
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

if $REVIEW_MODE && $IMPROVE_MODE; then
  echo "${RED}에러: --review와 --improve는 동시에 사용할 수 없습니다.${NC}" >&2
  exit 1
fi

if $REVIEW_MODE; then
  if [[ -z "$SESSION_NAME" ]]; then
    echo "${RED}에러: --review 사용 시 --session (-s) 옵션은 필수입니다.${NC}" >&2
    echo "예시: cw --review -s pr2-impl --assistant codex" >&2
    exit 1
  fi
  if [[ -n "${SESSION_NAME//[a-zA-Z0-9_-]/}" ]]; then
    echo "${RED}에러: 세션 이름은 영문, 숫자, 하이픈(-), 밑줄(_)만 허용됩니다: $SESSION_NAME${NC}" >&2
    exit 1
  fi
  SESSION_DIR=$(resolve_review_session_dir "$SESSION_NAME" || true)
  if [[ -z "$SESSION_DIR" ]]; then
    echo "${RED}에러: 세션 디렉토리를 찾을 수 없습니다: $SESSIONS_BASE_DIR/$SESSION_NAME${NC}" >&2
    print_review_session_candidates "$SESSION_NAME"
    exit 1
  fi
  if [[ "$SESSION_DIR" != "$SESSIONS_BASE_DIR/$SESSION_NAME" ]]; then
    echo "${CYAN}리뷰 세션 경로 자동 탐색: $SESSION_DIR${NC}"
  fi
  EVENT_LOG_FILE="$SESSION_DIR/cw-events.log"
  review_file=$(generate_review_file)
  improve_review_file=$(ensure_improve_review_file)
  append_improve_review_session_template "$improve_review_file" "CW" "$review_file" >/dev/null
  echo "${GREEN}리뷰 파일 생성 완료: $review_file${NC}"
  echo "${CYAN}개선 기록 파일: $improve_review_file${NC}"
  echo "${CYAN}리뷰 시작: 체크리스트 1번부터 사용자 확인을 받고 진행합니다.${NC}"
  launch_review_assistant "$REVIEW_ASSISTANT" "$review_file"
  exit $?
fi

if $IMPROVE_MODE; then
  if [[ -z "$SESSION_NAME" ]]; then
    echo "${RED}에러: --improve 사용 시 --session (-s) 옵션은 필수입니다.${NC}" >&2
    echo "예시: cw --improve -s pr2-impl --assistant codex" >&2
    exit 1
  fi
  if [[ -n "${SESSION_NAME//[a-zA-Z0-9_-]/}" ]]; then
    echo "${RED}에러: 세션 이름은 영문, 숫자, 하이픈(-), 밑줄(_)만 허용됩니다: $SESSION_NAME${NC}" >&2
    exit 1
  fi
  SESSION_DIR=$(resolve_review_session_dir "$SESSION_NAME" || true)
  if [[ -z "$SESSION_DIR" ]]; then
    echo "${RED}에러: 세션 디렉토리를 찾을 수 없습니다: $SESSIONS_BASE_DIR/$SESSION_NAME${NC}" >&2
    print_review_session_candidates "$SESSION_NAME"
    exit 1
  fi
  if [[ "$SESSION_DIR" != "$SESSIONS_BASE_DIR/$SESSION_NAME" ]]; then
    echo "${CYAN}개선 세션 경로 자동 탐색: $SESSION_DIR${NC}"
  fi

  if [[ -z "$IMPROVE_FILE" ]]; then
    if [[ -f "$SESSION_DIR/improve_review.md" ]]; then
      IMPROVE_FILE="$SESSION_DIR/improve_review.md"
    elif [[ -f "$SESSION_DIR/improve-review.md" ]]; then
      IMPROVE_FILE="$SESSION_DIR/improve-review.md"
    else
      IMPROVE_FILE=$(ensure_improve_review_file)
    fi
  fi

  if [[ ! -f "$IMPROVE_FILE" ]]; then
    echo "${RED}에러: 개선 입력 파일이 존재하지 않습니다: $IMPROVE_FILE${NC}" >&2
    exit 1
  fi
  IMPROVE_FILE="${IMPROVE_FILE:A}"

  improve_instructions_file=$(generate_improve_instructions_file "CW" "$IMPROVE_FILE")
  echo "${GREEN}개선 입력 파일: $IMPROVE_FILE${NC}"
  echo "${GREEN}개선 지시 파일: $improve_instructions_file${NC}"
  echo "${CYAN}개선 세션 시작: 기존 기능 보존 + 확장 방식 개선만 허용${NC}"
  if launch_improve_assistant "$REVIEW_ASSISTANT" "$improve_instructions_file"; then
    if zsh -n "$GLOBAL_TEMPLATE_DIR/run-workflow.sh"; then
      echo "${GREEN}개선 후 문법 검증 통과: $GLOBAL_TEMPLATE_DIR/run-workflow.sh${NC}"
      exit 0
    fi
    echo "${RED}개선 후 문법 검증 실패: $GLOBAL_TEMPLATE_DIR/run-workflow.sh${NC}" >&2
    exit 1
  fi
  exit $?
fi

if [[ ${#SPEC_PATHS[@]} -eq 0 ]]; then
  echo "${RED}에러: spec 파일 경로를 1개 이상 지정하세요.${NC}" >&2
  echo "사용법: cw -s <session_name> <spec_paths...> [options]" >&2
  echo "도움말: cw --help" >&2
  exit 1
fi

if [[ -z "$SESSION_NAME" ]]; then
  echo "${RED}에러: --session (-s) 옵션은 필수입니다.${NC}" >&2
  echo "예시: cw -s pr2-impl docs/spec.md -m src/app" >&2
  exit 1
fi

if [[ -n "${SESSION_NAME//[a-zA-Z0-9_-]/}" ]]; then
  echo "${RED}에러: 세션 이름은 영문, 숫자, 하이픈(-), 밑줄(_)만 허용됩니다: $SESSION_NAME${NC}" >&2
  exit 1
fi

SESSION_DIR="$SESSIONS_BASE_DIR/$SESSION_NAME"

for spec in "${SPEC_PATHS[@]}"; do
  if [[ ! -f "$spec" ]]; then
    echo "${RED}에러: $spec 파일이 존재하지 않습니다.${NC}" >&2
    exit 1
  fi
done

SPEC_FINGERPRINT=$(compute_spec_fingerprint "${SPEC_PATHS[@]}")

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

mkdir -p "$SESSION_DIR"
EVENT_LOG_FILE="$SESSION_DIR/cw-events.log"

if ! printf '%s' "$START_PHASE" | grep -qE '^[0-9]+$' || [[ "$START_PHASE" -gt 19 ]]; then
  echo "${RED}에러: 유효하지 않은 phase 번호입니다: $START_PHASE (0~19 범위)${NC}" >&2
  exit 1
fi

if [[ -z "$MODULE_PATH" ]]; then
  MODULE_PATH="."
fi

if [[ -z "$TEST_PATH" ]]; then
  if [[ -d "$MODULE_PATH/tests" ]]; then
    TEST_PATH="$MODULE_PATH/tests"
  else
    TEST_PATH="$MODULE_PATH"
  fi
fi

for spec in "${SPEC_PATHS[@]}"; do
  validate_path "$spec" "spec 경로"
done
validate_path "$MODULE_PATH" "--module"
validate_path "$TEST_PATH" "--test"
if [[ -n "$CUSTOM_TEMPLATE_DIR" ]]; then
  validate_path "$CUSTOM_TEMPLATE_DIR" "--templates"
fi

PLAN_PATH="$SESSION_DIR/cw-plan.md"
CHECKLIST_PATH="$SESSION_DIR/cw-checklist.md"
DIGEST_PATH="$SESSION_DIR/cw-spec-digest.md"
NOTES_PATH="$SESSION_DIR/cw-notes.md"

restore_context_files_if_missing

SPEC_LINES=$(compute_spec_lines)
SPEC_ADDEND=$(compute_spec_addend "$SPEC_LINES")
MAIN_BRANCH=$(detect_main_branch)

mkdir -p "$SESSION_DIR"

typeset -A PHASE_MAX_ITERATIONS
for phase in {0..19}; do
  base="${PHASE_BASE_ITERATIONS[$phase]}"
  PHASE_MAX_ITERATIONS[$phase]=$(compute_iterations "$base" "$N_MULTIPLIER" "$SPEC_ADDEND")
done

SPEC_LIST=""
for spec in "${SPEC_PATHS[@]}"; do
  SPEC_LIST+="- $spec"$'\n'
done
SPEC_LIST="${SPEC_LIST%$'\n'}"

typeset -A PHASE_DURATIONS
typeset -A PHASE_ITER_USED
typeset -A PHASE_EXIT_REASON
typeset -A PHASE_TOKENS
typeset -A PHASE_RETRIES
COMPLETED_PHASES=()
EXTENDED_PHASES=()
LAST_PHASE_TOKENS=0
LAST_PHASE_DURATION=0
LAST_PHASE_ERROR=""
LAST_ITER_PROMISE_SEEN=0
CONSECUTIVE_ZERO_TOKENS=0

generate_prompt() {
  local phase_num=$1
  local iter_num=$2
  local max_iter=$3

  local template_file
  template_file=$(find_template "${PHASE_FILES[$phase_num]}" "$CUSTOM_TEMPLATE_DIR")

  if [[ -z "$template_file" ]]; then
    echo "${RED}에러: 템플릿 파일을 찾을 수 없습니다: ${PHASE_FILES[$phase_num]}${NC}" >&2
    return 1
  fi

  local template
  template=$(<"$template_file")
  template="${template//\{\{SPEC_PATH\}\}/$SPEC_LIST}"
  template="${template//\{\{MODULE_PATH\}\}/$MODULE_PATH}"
  template="${template//\{\{TEST_PATH\}\}/$TEST_PATH}"
  template="${template//\{\{PLAN_PATH\}\}/$PLAN_PATH}"
  template="${template//\{\{CHECKLIST_PATH\}\}/$CHECKLIST_PATH}"
  template="${template//\{\{DIGEST_PATH\}\}/$DIGEST_PATH}"
  template="${template//\{\{NOTES_PATH\}\}/$NOTES_PATH}"
  local task_agent_guides
  task_agent_guides=$(build_task_agent_guides "$template" "$CUSTOM_TEMPLATE_DIR")

  cat <<EOF_PROMPT
# Codex Workflow Runner Context

- 현재 단계: Phase ${phase_num} (${PHASE_NAMES[$phase_num]})
- 현재 반복: ${iter_num}/${max_iter}

실행 원칙:
1) 템플릿에 Task(subagent_type='...')가 나오면, 아래에 첨부된 해당 agent reference 문서를 먼저 읽고 그 기준으로 수행한다.
2) phase 템플릿 지시를 실제 코드/문서 수정으로 반영한다.
3) 수정할 것이 없다면 코드 변경 없이 결과만 간결하게 정리한다.

아래는 Phase 템플릿 원문이다. 그대로 따르라.

---

${template}
EOF_PROMPT

  if [[ -n "$task_agent_guides" ]]; then
    cat <<EOF_PROMPT

---

# Agent References For This Phase

${task_agent_guides}
EOF_PROMPT
  fi
}

run_phase_iteration() {
  local phase_num=$1
  local iter_num=$2
  local max_iter=$3
  local phase_name="${PHASE_NAMES[$phase_num]}"

  local prompt
  prompt=$(generate_prompt "$phase_num" "$iter_num" "$max_iter") || return 1

  local prompt_file="$SESSION_DIR/cw-phase-${phase_num}-iter-${iter_num}-prompt.md"
  printf '%s\n' "$prompt" > "$prompt_file"

  if $DRY_RUN; then
    local template_file
    template_file=$(find_template "${PHASE_FILES[$phase_num]}" "$CUSTOM_TEMPLATE_DIR")
    echo "${YELLOW}[DRY RUN] Phase ${phase_num} ${phase_name} iter ${iter_num}/${max_iter}${NC}"
    echo "${YELLOW}[DRY RUN] Template: ${template_file}${NC}"
    echo "${YELLOW}[DRY RUN] Prompt (first 5 lines):${NC}"
    printf '%s\n' "$prompt" | head -5
    echo ""
    ITER_CHANGED=0
    LAST_PHASE_TOKENS=0
    LAST_PHASE_DURATION=0
    LAST_PHASE_ERROR=""
    LAST_ITER_PROMISE_SEEN=1
    ITER_SUCCESS=1
    return 0
  fi

  local before_fp
  before_fp=$(workspace_fingerprint)

  local -a cmd
  cmd=(codex exec --full-auto --color never --cd "$PROJECT_ROOT" --model "$MODEL_NAME")
  cmd+=(-c "model_reasoning_effort=\"$REASONING_EFFORT\"")
  cmd+=(-)

  local phase_start=$SECONDS
  local zero_token_retry=0
  LAST_ITER_PROMISE_SEEN=0

  while true; do
    local run_suffix=""
    local retry_label=""
    if (( zero_token_retry > 0 )); then
      run_suffix="-zt-${zero_token_retry}"
      retry_label=", token-retry ${zero_token_retry}회"
    fi

    local log_file="$SESSION_DIR/cw-phase-${phase_num}-iter-${iter_num}${run_suffix}.log"
    : > "$log_file"

    "${cmd[@]}" < "$prompt_file" > "$log_file" 2>&1 &
    ACTIVE_CODEX_PID=$!

    local cmd_exit=0
    local killed_for_stall=false
    local killed_for_prompt=false
    local run_start=$SECONDS
    local poll_interval=5
    local spin_chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local spin_idx=0
    local last_heartbeat=$SECONDS
    local last_stall_alert=$SECONDS
    local last_growth_check=$SECONDS
    local last_checkpoint_size
    last_checkpoint_size=$(get_log_size "$log_file")
    local last_log_active=$SECONDS
    local last_error_scan=$SECONDS
    local last_detected_error=""

    log_event "INFO" "iter_start" "phase=$phase_num iter=$iter_num retry=$zero_token_retry"

    while true; do
      if ! kill -0 "$ACTIVE_CODEX_PID" 2>/dev/null; then
        if wait "$ACTIVE_CODEX_PID"; then
          cmd_exit=0
        else
          cmd_exit=$?
        fi
        ACTIVE_CODEX_PID=""
        sleep 1
        break
      fi

      local elapsed=$((SECONDS - run_start))
      local dur
      dur=$(format_duration "$elapsed")
      local sc="${spin_chars:$((spin_idx % ${#spin_chars})):1}"
      spin_idx=$((spin_idx + 1))
      printf "\r${CYAN}%s Phase %d iter %d/%d %s (%s)%s${NC}  " \
        "$sc" "$phase_num" "$iter_num" "$max_iter" "$phase_name" "$dur" "$retry_label"

      if (( SECONDS - last_heartbeat >= 600 )); then
        echo ""
        echo "${CYAN}Phase $phase_num iter $iter_num 진행 중 (${dur}${retry_label})${NC}"
        last_heartbeat=$SECONDS
      fi

      local log_active=false
      if (( SECONDS - last_growth_check >= LOG_GROWTH_CHECK_INTERVAL )); then
        local cur_log_size
        cur_log_size=$(get_log_size "$log_file")
        local growth=$((cur_log_size - last_checkpoint_size))
        if (( growth > LOG_MEANINGFUL_GROWTH )); then
          last_log_active=$SECONDS
          log_active=true
        fi
        last_checkpoint_size=$cur_log_size
        last_growth_check=$SECONDS
      fi

      local log_stale_secs=$((SECONDS - last_log_active))
      if (( log_stale_secs >= STALL_KILL_THRESHOLD )); then
        local stale_min=$((log_stale_secs / 60))
        echo ""
        echo "${RED}⚠ Phase $phase_num iter $iter_num: 로그 ${stale_min}분간 무응답 → 강제 종료${NC}"
        log_event "ERROR" "stall_kill" "phase=$phase_num iter=$iter_num retry=$zero_token_retry stale=${stale_min}m"
        kill "$ACTIVE_CODEX_PID" 2>/dev/null || true
        local kill_wait=0
        while kill -0 "$ACTIVE_CODEX_PID" 2>/dev/null && (( kill_wait < 5 )); do
          sleep 1
          kill_wait=$((kill_wait + 1))
        done
        kill -9 "$ACTIVE_CODEX_PID" 2>/dev/null || true
        if wait "$ACTIVE_CODEX_PID"; then :; fi
        ACTIVE_CODEX_PID=""
        cmd_exit=124
        killed_for_stall=true
        break
      fi

      if (( SECONDS - last_stall_alert >= STALL_THRESHOLD )); then
        local stale_min=$((log_stale_secs / 60))
        echo ""
        if $log_active || (( log_stale_secs < LOG_GROWTH_CHECK_INTERVAL )); then
          echo "${YELLOW}⚠ Phase $phase_num iter $iter_num: 장시간 실행 중 (${stale_min}분, 로그 활성)${NC}"
          log_event "INFO" "long_iter" "phase=$phase_num iter=$iter_num retry=$zero_token_retry stale=${stale_min}m active=true"
        else
          echo "${YELLOW}⚠ Phase $phase_num iter $iter_num: 로그 ${stale_min}분간 큰 변화 없음${NC}"
          log_event "WARN" "stall_log" "phase=$phase_num iter=$iter_num retry=$zero_token_retry stale=${stale_min}m"
        fi
        last_stall_alert=$SECONDS
      fi

      if (( SECONDS - last_error_scan >= 30 )); then
        local detected
        detected=$(detect_log_errors "$log_file")
        if [[ -n "$detected" ]] && [[ "$detected" != "$last_detected_error" ]]; then
          echo ""
          echo "${YELLOW}⚠ Phase $phase_num iter $iter_num: 에러 패턴 감지 — $detected${NC}"
          log_event "WARN" "log_error" "phase=$phase_num iter=$iter_num retry=$zero_token_retry pattern=$detected"
          last_detected_error="$detected"
        fi
        last_error_scan=$SECONDS
      fi

      # stop hook 에러 후 프롬프트 대기 상태로 멈추는 경우 조기 종료
      if (( SECONDS - run_start >= 120 )); then
        local tail_clean
        tail_clean=$(tail -c 4096 "$log_file" 2>/dev/null \
          | sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1b][^\x07]*\x07//g; s/\r//g' 2>/dev/null || true)
        if printf '%s' "$tail_clean" | grep -qi 'Stop hook error' 2>/dev/null && \
           printf '%s' "$tail_clean" | grep -qE '❯|bypass permissions|waiting for input|prompt' 2>/dev/null; then
          echo ""
          echo "${RED}⚠ Phase $phase_num iter $iter_num: stop hook 프롬프트 대기 감지 → 강제 종료${NC}"
          log_event "ERROR" "prompt_stuck" "phase=$phase_num iter=$iter_num retry=$zero_token_retry"
          kill "$ACTIVE_CODEX_PID" 2>/dev/null || true
          local kill_wait=0
          while kill -0 "$ACTIVE_CODEX_PID" 2>/dev/null && (( kill_wait < 5 )); do
            sleep 1
            kill_wait=$((kill_wait + 1))
          done
          kill -9 "$ACTIVE_CODEX_PID" 2>/dev/null || true
          if wait "$ACTIVE_CODEX_PID"; then :; fi
          ACTIVE_CODEX_PID=""
          cmd_exit=125
          killed_for_prompt=true
          break
        fi
      fi

      sleep "$poll_interval"
    done
    printf "\r\033[K"

    local tokens=0
    if [[ -f "$log_file" ]]; then
      tokens=$(extract_tokens_from_log "$log_file")
    fi
    LAST_PHASE_TOKENS=$tokens
    PHASE_TOKENS[$phase_num]=$((${PHASE_TOKENS[$phase_num]:-0} + tokens))

    local tokens_fmt
    tokens_fmt=$(format_tokens "$tokens")
    local detected_error
    detected_error=$(detect_log_errors "$log_file")
    LAST_PHASE_ERROR="$detected_error"
    local promise="${PHASE_PROMISES[$phase_num]}"
    if check_promise_in_log "$log_file" "$promise"; then
      LAST_ITER_PROMISE_SEEN=1
    else
      LAST_ITER_PROMISE_SEEN=0
    fi

    if [[ "$cmd_exit" -eq 0 ]]; then
      local after_fp
      after_fp=$(workspace_fingerprint)

      if [[ "$before_fp" == "$after_fp" ]]; then
        ITER_CHANGED=0
      else
        ITER_CHANGED=1
      fi

      if [[ "$ITER_CHANGED" -eq 0 ]] && [[ "$tokens" -eq 0 ]] && is_token_limit_error "$detected_error"; then
        CONSECUTIVE_ZERO_TOKENS=$((CONSECUTIVE_ZERO_TOKENS + 1))
        if (( CONSECUTIVE_ZERO_TOKENS >= MAX_ZERO_TOKEN_RETRIES )); then
          local zt_hours=$((CONSECUTIVE_ZERO_TOKENS * ZERO_TOKEN_WAIT / 3600))
          local elapsed_fail=$((SECONDS - phase_start))
          local fail_dur
          fail_dur=$(format_duration "$elapsed_fail")
          LAST_PHASE_DURATION=$elapsed_fail
          echo "${RED}✘ Phase $phase_num ${phase_name} iter ${iter_num}/${max_iter} 중단 (${fail_dur}, 0-토큰 ${zt_hours}시간 지속)${NC}"
          log_event "ERROR" "zero_tokens_timeout" "phase=$phase_num iter=$iter_num retry=$zero_token_retry hours=$zt_hours"
          ITER_CHANGED=0
          ITER_SUCCESS=0
          return 1
        fi
        zero_token_retry=$((zero_token_retry + 1))
        local zt_elapsed=$((CONSECUTIVE_ZERO_TOKENS * ZERO_TOKEN_WAIT / 60))
        local zt_max=$((MAX_ZERO_TOKEN_RETRIES * ZERO_TOKEN_WAIT / 60))
        echo "${YELLOW}⚠ Phase $phase_num iter $iter_num: 0 토큰(token limit 추정, 연속 ${CONSECUTIVE_ZERO_TOKENS}회, ${zt_elapsed}/${zt_max}분). 10분 후 재시도${NC}"
        log_event "WARN" "zero_tokens" "phase=$phase_num iter=$iter_num retry=$zero_token_retry consecutive=$CONSECUTIVE_ZERO_TOKENS"
        sleep_with_countdown "$ZERO_TOKEN_WAIT" "Phase $phase_num iter $iter_num token limit 대기"
        continue
      fi

      CONSECUTIVE_ZERO_TOKENS=0
      local elapsed=$((SECONDS - phase_start))
      local dur
      dur=$(format_duration "$elapsed")
      LAST_PHASE_DURATION=$elapsed
      local change_mark="no-change"
      [[ "$ITER_CHANGED" -eq 1 ]] && change_mark="changed"
      local promise_mark="promise-missing"
      [[ "$LAST_ITER_PROMISE_SEEN" -eq 1 ]] && promise_mark="promise-ok"
      echo "${GREEN}✔ Phase $phase_num ${phase_name} iter ${iter_num}/${max_iter} 완료 (${dur}, ${change_mark}, ${promise_mark}, ↓ $tokens_fmt${retry_label})${NC}"
      log_event "INFO" "iter_done" "phase=$phase_num iter=$iter_num changed=$ITER_CHANGED promise=$LAST_ITER_PROMISE_SEEN tokens=$tokens retry=$zero_token_retry"
      ITER_SUCCESS=1
      return 0
    fi

    if [[ "$tokens" -eq 0 ]] && is_token_limit_error "$detected_error"; then
      CONSECUTIVE_ZERO_TOKENS=$((CONSECUTIVE_ZERO_TOKENS + 1))
      if (( CONSECUTIVE_ZERO_TOKENS >= MAX_ZERO_TOKEN_RETRIES )); then
        local zt_hours=$((CONSECUTIVE_ZERO_TOKENS * ZERO_TOKEN_WAIT / 3600))
        local elapsed_fail=$((SECONDS - phase_start))
        local fail_dur
        fail_dur=$(format_duration "$elapsed_fail")
        LAST_PHASE_DURATION=$elapsed_fail
        echo "${RED}✘ Phase $phase_num ${phase_name} iter ${iter_num}/${max_iter} 중단 (${fail_dur}, 0-토큰 ${zt_hours}시간 지속)${NC}"
        log_event "ERROR" "zero_tokens_timeout" "phase=$phase_num iter=$iter_num retry=$zero_token_retry hours=$zt_hours"
        ITER_CHANGED=0
        ITER_SUCCESS=0
        return 1
      fi
      zero_token_retry=$((zero_token_retry + 1))
      local zt_elapsed=$((CONSECUTIVE_ZERO_TOKENS * ZERO_TOKEN_WAIT / 60))
      local zt_max=$((MAX_ZERO_TOKEN_RETRIES * ZERO_TOKEN_WAIT / 60))
      echo "${YELLOW}⚠ Phase $phase_num iter $iter_num 실패: 0 토큰(token limit 추정, 연속 ${CONSECUTIVE_ZERO_TOKENS}회, ${zt_elapsed}/${zt_max}분). 10분 후 재시도${NC}"
      log_event "WARN" "zero_tokens_fail" "phase=$phase_num iter=$iter_num retry=$zero_token_retry consecutive=$CONSECUTIVE_ZERO_TOKENS"
      sleep_with_countdown "$ZERO_TOKEN_WAIT" "Phase $phase_num iter $iter_num token limit 대기"
      continue
    fi

    CONSECUTIVE_ZERO_TOKENS=0
    local elapsed_fail=$((SECONDS - phase_start))
    local fail_dur
    fail_dur=$(format_duration "$elapsed_fail")
    LAST_PHASE_DURATION=$elapsed_fail
    local fail_reason="실행 실패"
    if $killed_for_prompt; then
      fail_reason="stop hook 프롬프트 대기 감지로 강제 종료"
    elif $killed_for_stall; then
      fail_reason="정체 감지로 강제 종료"
    fi
    if [[ -n "$detected_error" ]]; then
      fail_reason="${fail_reason}: ${detected_error}"
    fi
    echo "${RED}✘ Phase $phase_num ${phase_name} iter ${iter_num}/${max_iter} 실패 (${fail_dur}, ↓ $tokens_fmt, ${fail_reason}${retry_label})${NC}"
    log_event "ERROR" "iter_fail" "phase=$phase_num iter=$iter_num retry=$zero_token_retry tokens=$tokens reason=$fail_reason"
    ITER_CHANGED=0
    ITER_SUCCESS=0
    return 1
  done
}

compute_total_tokens() {
  local total=0
  for phase in "${COMPLETED_PHASES[@]}"; do
    total=$((total + ${PHASE_TOKENS[$phase]:-0}))
  done
  printf '%s\n' "$total"
}

compute_code_stats() {
  local base_ref stat_line
  base_ref=$(git merge-base HEAD "$MAIN_BRANCH" 2>/dev/null || printf '%s\n' "HEAD~1")
  stat_line=$(git diff --stat "$base_ref" 2>/dev/null | tail -1 || true)
  FILES_CHANGED=$(printf '%s\n' "$stat_line" | grep -oE '[0-9]+ file' | grep -oE '[0-9]+' || true)
  LINES_ADDED=$(printf '%s\n' "$stat_line" | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+' || true)
  LINES_DELETED=$(printf '%s\n' "$stat_line" | grep -oE '[0-9]+ deletion' | grep -oE '[0-9]+' || true)
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
  generate_deep_review_file "CW" "cw-review.md"
}

launch_review_assistant() {
  local assistant=${1:-codex}
  local review_file=$2
  local prompt="Read ${review_file} first. Follow Group 0 to Group 7 order. In Group 2 to Group 5, review exactly one file at a time and WAIT for user confirmation before moving to the next file. For each file, fill WHAT/HOW/WHY/VERIFY/SIDE EFFECT checks. At the end (Group 7), extract project-independent improvements and write them to ${SESSION_DIR}/improve_review.md in this session block."

  case "$assistant" in
    codex)
      if ! command -v codex >/dev/null 2>&1; then
        echo "${YELLOW}경고: codex 명령을 찾을 수 없어 자동 실행을 건너뜁니다.${NC}" >&2
        return 0
      fi
      codex -C "$PROJECT_ROOT" --model "$MODEL_NAME" \
        -c "model_reasoning_effort=\"$REASONING_EFFORT\"" "$prompt"
      ;;
    claude)
      if ! command -v claude >/dev/null 2>&1; then
        echo "${YELLOW}경고: claude 명령을 찾을 수 없어 자동 실행을 건너뜁니다.${NC}" >&2
        return 0
      fi
      claude --model "$DEFAULT_CLAUDE_MODEL_NAME" --effort "$DEFAULT_CLAUDE_EFFORT" "$prompt"
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

print_summary() {
  local total_seconds=$1
  local total_dur
  total_dur=$(format_duration "$total_seconds")
  local total_tokens
  total_tokens=$(compute_total_tokens)
  local total_tokens_fmt
  total_tokens_fmt=$(format_tokens "$total_tokens")

  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  Codex Workflow 실행 요약  [$SESSION_NAME]"
  echo "═══════════════════════════════════════════════════════════"
  echo ""
  echo "  Spec: ${SPEC_LINES}줄, +${SPEC_ADDEND}/phase (300줄당 +1), multiplier: ×${N_MULTIPLIER}"
  echo "  Model: ${MODEL_NAME}, Reasoning: ${REASONING_EFFORT}"
  echo ""

  for phase in "${COMPLETED_PHASES[@]}"; do
    local name="${PHASE_NAMES[$phase]}"
    local dur
    dur=$(format_duration "${PHASE_DURATIONS[$phase]:-0}")
    local iter_used="${PHASE_ITER_USED[$phase]:-0}"
    local reason="${PHASE_EXIT_REASON[$phase]:-unknown}"
    local tok
    tok=$(format_tokens "${PHASE_TOKENS[$phase]:-0}")
    local retries="${PHASE_RETRIES[$phase]:-0}"
    local retry_info=""
    if (( retries > 0 )); then
      retry_info=", retry ${retries}회"
    fi
    printf "  Phase %2d %-14s —  %10s  —  iter %2s  —  ↓ %6s  —  %s%s\n" "$phase" "$name" "$dur" "$iter_used" "$tok" "$reason" "$retry_info"
  done

  echo "  ─────────────────────────────────────────────────────"
  printf "  TOTAL    %-14s —  %10s  —  ↓ %6s\n" "" "$total_dur" "$total_tokens_fmt"

  compute_code_stats
  if [[ "$FILES_CHANGED" -gt 0 ]] 2>/dev/null; then
    printf "  코드: %s files changed, +%s -%s\n" "$FILES_CHANGED" "$LINES_ADDED" "$LINES_DELETED"
  fi

  if [[ ${#EXTENDED_PHASES[@]} -gt 0 ]]; then
    echo ""
    echo "  ${YELLOW}⚠ Promise 미감지 phase: ${EXTENDED_PHASES[*]}${NC}"
    echo "    (재시도 한도 도달 후 강제 진행)"
  fi

  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo ""
}

END_PHASE=19

if [[ "$START_PHASE" -eq 0 ]] && [[ ! -f "$NOTES_PATH" ]]; then
  cat > "$NOTES_PATH" << 'NOTES_EOF'
# Phase 간 공유 메모

이전 Phase에서 발견/수정한 사항을 기록한다. 후속 Phase에서 참조한다.

**기록 형식**: `[Phase N] [심각도] [파일:라인] 설명`

---

NOTES_EOF
fi

echo "${CYAN}Codex Workflow 시작: Phase ${START_PHASE}~${END_PHASE}, spec ${#SPEC_PATHS[@]}개 (${SPEC_LINES}줄, ×${N_MULTIPLIER})${NC}"
echo "${CYAN}사용 모델: $MODEL_NAME${NC}"
echo "${CYAN}추론 강도: $REASONING_EFFORT${NC}"

WORKFLOW_START=$SECONDS
ALL_DONE=true
LAST_PHASE_ATTEMPTED=$START_PHASE

for phase in $(seq "$START_PHASE" "$END_PHASE"); do
  LAST_PHASE_ATTEMPTED=$phase
  if ! $DRY_RUN; then
    save_session_state "in_progress" "$phase"
  fi

  phase_name="${PHASE_NAMES[$phase]}"
  max_iter="${PHASE_MAX_ITERATIONS[$phase]}"
  max_retries=$(compute_max_retries "$max_iter")
  phase_start=$SECONDS

  echo ""
  echo "${CYAN}▶ Phase $phase/$END_PHASE: $phase_name (iter ${max_iter}회, 재시도 최대 ${max_retries}회)${NC}"

  phase_reason="max-iterations-no-promise"
  phase_ok=false
  iter_used=0
  retry=0

  while true; do
    if (( retry > 0 )); then
      echo "${YELLOW}⚠ Phase $phase promise 미검출 재시도 ${retry}/${max_retries}${NC}"
    fi

    phase_failed=false
    phase_reason="max-iterations-no-promise"

    for iter in $(seq 1 "$max_iter"); do
      iter_used=$iter
      if ! run_phase_iteration "$phase" "$iter" "$max_iter"; then
        phase_failed=true
        phase_reason="iteration-failed"
        break
      fi

      if [[ "$LAST_ITER_PROMISE_SEEN" -eq 1 ]]; then
        phase_reason="promise-detected"
        phase_ok=true
        break
      fi

      if [[ "$ITER_CHANGED" -eq 0 ]]; then
        phase_reason="no-change-no-promise"
        break
      fi
    done

    if $phase_ok; then
      PHASE_RETRIES[$phase]=$retry
      break
    fi

    if $phase_failed; then
      PHASE_RETRIES[$phase]=$retry
      break
    fi

    retry=$((retry + 1))
    if (( retry > max_retries )); then
      phase_ok=true
      phase_reason="forced-without-promise"
      PHASE_RETRIES[$phase]=$((retry - 1))
      EXTENDED_PHASES+=("$phase")
      echo "${YELLOW}⚠ Phase $phase: promise 미검출 상태로 재시도 한도 초과 → 강제 진행${NC}"
      log_event "WARN" "force_proceed" "phase=$phase retries=$((retry - 1)) reason=$phase_reason"
      break
    fi
    log_event "INFO" "promise_retry" "phase=$phase retry=$retry max=$max_retries reason=$phase_reason"
  done

  phase_elapsed=$((SECONDS - phase_start))
  PHASE_DURATIONS[$phase]=$phase_elapsed
  PHASE_ITER_USED[$phase]=$iter_used
  PHASE_EXIT_REASON[$phase]="$phase_reason"

  if $phase_ok; then
    COMPLETED_PHASES+=("$phase")
    echo "${GREEN}✓ Phase $phase 완료 (reason: $phase_reason, iter: ${iter_used}/${max_iter})${NC}"
  else
    ALL_DONE=false
    echo "${RED}✘ Phase $phase 실패 (reason: $phase_reason)${NC}"
    break
  fi
done

if ! $DRY_RUN; then
  if $ALL_DONE; then
    save_session_state "completed" "$END_PHASE"
  else
    save_session_state "in_progress" "$LAST_PHASE_ATTEMPTED"
  fi

  for f in "$PLAN_PATH" "$CHECKLIST_PATH" "$DIGEST_PATH" "$NOTES_PATH"; do
    [[ -f "$f" ]] && cp "$f" "$SESSION_DIR/" 2>/dev/null || true
  done
fi

TOTAL_ELAPSED=$((SECONDS - WORKFLOW_START))

if [[ ${#COMPLETED_PHASES[@]} -gt 0 ]]; then
  print_summary "$TOTAL_ELAPSED"
fi

if ! $DRY_RUN; then
  REVIEW_FILE_PATH=$(generate_review_file)
  echo "${CYAN}리뷰 파일: $REVIEW_FILE_PATH${NC}"
  echo "${CYAN}리뷰 시작 명령: cw --review -s ${SESSION_NAME} --assistant codex${NC}"
  echo "${CYAN}개선 시작 명령: cw --improve -s ${SESSION_NAME} --assistant codex${NC}"
  log_event "INFO" "review_file" "path=$REVIEW_FILE_PATH"
fi

if $ALL_DONE; then
  echo "${GREEN}워크플로우 완료${NC}"
else
  echo "${YELLOW}워크플로우 중단. 세션을 재개하려면 동일 spec으로 다시 실행하세요.${NC}"
  exit 1
fi
