# Oh My Zsh가 심링크를 통해 이 파일을 읽어도 실제 저장소의 실행기를 사용한다.
typeset -g _mac_setup_ai_launcher="${${(%):-%x}:A:h:h}/codex/account-switcher/launcher.py"
typeset -g _mac_setup_claude_session="${${(%):-%x}:A:h:h}/claude/account-switcher/managed_session.py"

function codex claude {
  if [[ $# -eq 1 && $1 == update ]]; then
    "$_mac_setup_ai_launcher" update
  elif [[ ${funcstack[1]} == claude && -t 0 && -t 1 && -n ${commands[claude]:-} && -x /opt/homebrew/opt/python@3.14/bin/python3.14 ]]; then
    /opt/homebrew/opt/python@3.14/bin/python3.14 "$_mac_setup_claude_session" "${commands[claude]}" "$@"
  else
    command "${funcstack[1]}" "$@"
  fi
}
