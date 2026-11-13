#!/bin/bash
# /refresh-session(Claude Code)이 부른다. 지금 세션을 끄고 설치된 최신 Claude Code로 새 세션을 띄워 첫 프롬프트를 잇는다.
# 사용:
#   restart.sh tab     <디렉토리> <모델> <effort> <권한 모드> <첫 프롬프트>
#   restart.sh restart <디렉토리> <모델> <effort> <권한 모드> <세션 pid> <첫 프롬프트>
# tab은 새 탭에서 칠 명령을 클립보드에 넣고 출력한다. restart는 세션 종류에 따라 다시 띄우고 사용자에게 보일 줄을 출력한다.
#   백그라운드 세션: 새 백그라운드 세션을 띄우고, 이 세션은 턴이 끝나면 claude stop한다.
#     claude respawn은 붙어 있던 화면을 떼어 내서(이어서 입력할 곳이 사라진다) 쓰지 않는다.
#   cmux 탭의 대화형 세션: 이 탭에 /exit를 입력해 두고, Claude Code가 끝나면 같은 탭 셸에 재시작 명령을 입력한다.
#   그 밖(claude agents 목록에서 종류를 확인하지 못한 경우 포함): 재시작 명령을 클립보드에 넣는다.
# 턴이 끝나기를 기다리는 일은 떼어 낸 프로세스가 하고, 그 기록은 ~/.claude/state/refresh-session/restart.log에 남는다.
set -euo pipefail

state_dir="$HOME/.claude/state/refresh-session"
log="$state_dir/restart.log"
# 턴이 끝나거나 Claude Code가 꺼지기를 기다리는 한도(초)
wait_limit=600

main() {
	local mode=${1:-}
	shift || true
	case $mode:$# in
	tab:5) copy_tab_command "$@" ;;
	restart:6) restart "$@" ;;
	stop-when-idle:2) stop_when_idle "$@" ;;
	type-after-exit:3) type_after_exit "$@" ;;
	*)
		echo "사용: restart.sh tab|restart <디렉토리> <모델> <effort> <권한 모드> [<세션 pid>] <첫 프롬프트>" >&2
		return 2
		;;
	esac
}

# copy_tab_command <디렉토리> <모델> <effort> <권한 모드> <첫 프롬프트>
copy_tab_command() {
	local cmd
	cmd=$(restart_command "$@")
	printf '%s' "$cmd" | pbcopy
	printf '%s\n' "$cmd"
}

# restart <디렉토리> <모델> <effort> <권한 모드> <세션 pid> <첫 프롬프트>
restart() {
	local pid=$5 info kind id
	# pid가 틀리면 기다리는 쪽이 곧바로 끝난 것으로 보고, 아직 도는 Claude Code 입력칸에 명령을 친다.
	if ! [[ $pid =~ ^[0-9]+$ && $(ps -o command= -p "$pid" 2>/dev/null) == *claude* ]]; then
		echo "세션 pid가 Claude Code 프로세스가 아닙니다: '$pid'" >&2
		return 1
	fi
	info=$(session_info pid "$pid" || true)
	read -r kind id _ <<<"$info" || true
	# 탭에 /exit를 치는 일은 그 탭에서 도는 대화형 세션으로 확인될 때만 한다. agent view 목록 화면에 치면 새 세션이 생긴다.
	if [[ $kind == background ]]; then
		restart_background "$1" "$2" "$3" "$4" "$id" "$pid" "$6"
	elif [[ $kind == interactive && -n ${CMUX_SURFACE_ID:-} ]]; then
		restart_in_tab "$1" "$2" "$3" "$4" "$pid" "$6"
	else
		copy_command "$1" "$2" "$3" "$4" "$6"
	fi
}

# restart_background <디렉토리> <모델> <effort> <권한 모드> <세션 id> <세션 pid> <첫 프롬프트>
restart_background() {
	local dir=$1 id=$5 pid=$6 prompt=$7 settings out new
	local args=(--bg -n "$(session_name "$prompt")" --model "$2" --effort "$3" --permission-mode "$4")
	settings=$(agent_view_settings)
	[[ -z $settings ]] || args+=(--settings "$settings")
	out=$(cd "$dir" && claude "${args[@]}" -- "$prompt" 2>&1) || {
		echo "claude --bg 실패: $out" >&2
		return 1
	}
	new=$(sed -n 's/^backgrounded · \([0-9a-f]*\) · .*/\1/p' <<<"$out")
	if [[ -z $new ]]; then
		echo "claude --bg 출력에서 새 세션 id를 찾지 못해 이 세션을 멈추지 않았습니다: $out" >&2
		return 1
	fi
	detach stop-when-idle "$id" "$pid"
	printf '새 세션 %s(Claude Code %s)에서 `%s`를 실행합니다. ' "$new" "$(installed_version)" "$prompt"
	printf '이 세션은 이 턴이 끝나면 멈춥니다(`claude attach %s`로 다시 열 수 있습니다). ' "$id"
	echo "agent view에서 새 행을 여세요."
	[[ -n $settings ]] || echo "agent view의 cmux 설정을 찾지 못해 새 세션에는 cmux 알림이 없습니다."
}

# restart_in_tab <디렉토리> <모델> <effort> <권한 모드> <세션 pid> <첫 프롬프트>
restart_in_tab() {
	local pid=$5 cmd
	cmd=$(restart_command "$1" "$2" "$3" "$4" "$6")
	# 턴 중에 입력한 /exit는 턴이 끝날 때까지 큐에서 기다린다.
	cmux send --surface "$CMUX_SURFACE_ID" -- /exit >/dev/null
	cmux send-key --surface "$CMUX_SURFACE_ID" enter >/dev/null
	detach type-after-exit "$pid" "$CMUX_SURFACE_ID" "$cmd"
	printf '이 턴이 끝나면 Claude Code를 끄고 같은 탭에서 다시 띄웁니다: `%s`\n' "$cmd"
}

# copy_command <디렉토리> <모델> <effort> <권한 모드> <첫 프롬프트>
copy_command() {
	local cmd
	cmd=$(restart_command "$@")
	printf '%s' "$cmd" | pbcopy
	printf '`/exit` 뒤 붙여 넣으세요. 클립보드에 복사했습니다: `%s`\n' "$cmd"
}

# stop_when_idle <세션 id> <세션 pid>: 그 세션의 턴이 끝나면 claude stop한다.
# 그 사이 다른 프로세스로 다시 떴거나 목록에서 빠졌으면 멈추지 않는다.
stop_when_idle() {
	local id=$1 pid=$2 info waited=0
	while ((waited < wait_limit)); do
		info=$(session_info id "$id" || true)
		case $info in
		"background $id $pid idle")
			if claude stop "$id"; then log "세션을 멈췄습니다: ${id}"; else notify "claude stop $id 실패"; fi
			return
			;;
		"background $id $pid "*) ;;
		*)
			notify "세션이 다른 프로세스로 바뀌었거나 목록에 없어 멈추지 않았습니다: ${id} (${info:-목록에 없음})"
			return
			;;
		esac
		sleep 2
		waited=$((waited + 2))
	done
	notify "세션 ${id}의 턴이 ${wait_limit}초 안에 끝나지 않아 멈추지 않았습니다. 직접 멈추려면: claude stop $id"
}

# type_after_exit <세션 pid> <cmux 탭> <명령>: 그 Claude Code가 끝나면 그 탭 셸에 명령을 입력한다.
type_after_exit() {
	local pid=$1 surface=$2 cmd=$3 waited=0
	while kill -0 "$pid" 2>/dev/null; do
		if ((waited >= wait_limit)); then
			notify "Claude Code(pid $pid)가 ${wait_limit}초 안에 끝나지 않아 다시 띄우지 않았습니다"
			return
		fi
		sleep 1
		waited=$((waited + 1))
	done
	if cmux send --surface "$surface" -- "$cmd" >/dev/null && cmux send-key --surface "$surface" enter >/dev/null; then
		log "탭 ${surface}에 입력했습니다: $cmd"
	else
		notify "탭에 재시작 명령을 입력하지 못했습니다: $cmd"
	fi
}

# session_info <pid|id> <값>: claude agents --json에서 그 세션의 "kind id pid status"를 출력한다. 없으면 빈 출력이다.
session_info() {
	claude agents --json | /usr/bin/python3 -I -c '
import json, sys
key, value = sys.argv[1], sys.argv[2]
for s in json.load(sys.stdin):
    if str(s.get(key)) == value:
        print(s.get("kind"), s.get("id"), s.get("pid"), s.get("status"))
        break
' "$1" "$2"
}

# agent_view_settings: cmux가 이 탭의 claude(agent view)에 넘긴 --settings JSON을 출력한다. 찾지 못하면 빈 출력이다.
# claude --bg로 띄운 세션은 agent view의 설정을 받지 않아서, cmux 알림 훅을 이것으로 넘긴다.
agent_view_settings() {
	[[ -n ${CMUX_CLAUDE_PID:-} ]] || return 0
	ps -ww -o args= -p "$CMUX_CLAUDE_PID" 2>/dev/null | /usr/bin/python3 -I -c '
import json, re, sys
m = re.search(r" --settings (\{.*\})(?= --|\s*$)", sys.stdin.read())
if m:
    try:
        json.loads(m.group(1))
    except ValueError:
        sys.exit(0)
    print(m.group(1))
' || true
}

# session_name <첫 프롬프트>: 슬래시 명령이면 그 이름을, 아니면 refresh를 새 세션 이름으로 출력한다.
session_name() {
	local first=${1%%[[:space:]]*}
	if [[ $first =~ ^/([A-Za-z0-9:_-]+)$ ]]; then printf '%s' "${BASH_REMATCH[1]}"; else printf 'refresh'; fi
}

installed_version() {
	claude --version | cut -d' ' -f1
}

# restart_command <디렉토리> <모델> <effort> <권한 모드> <첫 프롬프트>: 셸에 칠 재시작 명령을 출력한다.
restart_command() {
	printf 'cd %s && claude --model %s --effort %s --permission-mode %s -- %s' \
		"$(shell_dir "$1")" "$(word "$2")" "$(word "$3")" "$(word "$4")" "$(quote "$5")"
}

# shell_dir <디렉토리>: 홈 아래이고 셸 특수 문자가 없으면 ~/…로, 아니면 작은따옴표로 감싸 출력한다.
shell_dir() {
	local rest=${1#"$HOME"/}
	if [[ $rest != "$1" && $rest =~ ^[A-Za-z0-9._/-]+$ ]]; then printf '~/%s' "$rest"; else quote "$1"; fi
}

# word <글>: 셸 특수 문자가 없으면 그대로, 있으면 작은따옴표로 감싸 출력한다(opus[1m]의 []는 zsh glob이다).
word() {
	if [[ $1 =~ ^[A-Za-z0-9._:/=-]+$ ]]; then printf '%s' "$1"; else quote "$1"; fi
}

# quote <글>: 작은따옴표로 감싸고, 안의 '는 '\''로 바꾼다.
quote() {
	local sq="'" escaped="'\\''"
	printf "'%s'" "${1//"$sq"/$escaped}"
}

# detach <인자...>: 이 스크립트를 새 세션으로 떼어 돌린다. Claude Code가 이 세션을 멈추거나 끝내도 남는다.
detach() {
	mkdir -p "$state_dir"
	/usr/bin/perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' bash "$0" "$@" >>"$log" 2>&1 </dev/null &
}

log() {
	printf '%s %s\n' "$(date '+%F %T')" "$1"
}

# notify <글>: 로그에 남기고, cmux 안이면 알림으로도 띄운다.
notify() {
	log "$1"
	[[ -z ${CMUX_SURFACE_ID:-} ]] || cmux notify --title refresh-session --body "$1" >/dev/null 2>&1 || true
}

main "$@"
