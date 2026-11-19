# Oh My Zsh가 심링크를 통해 이 파일을 읽어도 실제 저장소의 실행기를 사용한다.
typeset -g _mac_setup_ai_launcher="${${(%):-%x}:A:h:h}/codex/account-switcher/launcher.py"

function codex claude {
  if [[ $# -eq 1 && $1 == update ]]; then
    "$_mac_setup_ai_launcher" update
  else
    command "${funcstack[1]}" "$@"
  fi
}
