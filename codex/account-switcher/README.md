# Codex 사용량에 따른 계정 자동 전환

`codex`로 시작하는 대화형 세션은 회사 계정을 우선 사용한다. 회사가 90% 이상이고
개인이 90% 미만이면 개인으로 전환한다. 둘 다 90% 이상이면 회사 계정을 선택한다.
각 서비스의 실제 사용 한도는 그대로 적용되며 이 실행기가 한도를 늘리지는 않는다.

```sh
codex                            # 세션 중 자동 전환 활성화
codex resume --last              # 자동 전환 세션의 대화 계속
codex --account-status           # 사용률, 초기화 시각, 마지막 조회, 현재 계정
CODEX_ACCOUNT=company codex      # 회사 고정, 자동 전환 없음
CODEX_ACCOUNT=personal codex     # 개인 고정, 자동 전환 없음
```

## 전환과 초기화

- 60초마다 두 계정의 사용량을 공식 `account/rateLimits/read`로 확인한다.
- 알려진 초기화 시각이 더 빠르면 그 직후 다시 조회한다.
- 한도별 사용률·초기화 시각·조회 시각을 `~/.codex-auto/account-switcher.json`에 저장한다.
- 초기화 예정 시각이 지났다는 이유만으로 사용률을 0으로 바꾸지 않는다.
  실제 조회에서 다음 사용 기간으로 넘어간 것을 확인하면 `last_reset_confirmed_at`과
  `previous_resets_at`도 기록한다. 재시작 후에도 이전 기록을 사용한다.
- 회사가 다시 90% 미만이 되면 회사로 돌아간다. 조회 실패 시 이전 사용량을 새 정보로
  간주하지 않고 기존 계정을 유지한다. 상태 명령에는 조회 실패 여부를 표시한다.
- 전환 대상이 바뀌면 자동 서버의 모든 열린 대화가 쉬는지 확인한다.
  실행 중인 응답·도구·승인 대기가 있으면 전환을 보류하고 2초마다 다시 확인한다.
  모델 응답을 받는 도중에 인증을 바꾸면 그 턴이 「application network permission was
  revoked」로 실패하고 대화가 `systemError`가 되기 때문이다(0.168.0, 2026-11-13 실측).
  `systemError`로 멈춘 대화는 아무것도 실행하지 않으므로 기다리지 않는다.
  90%는 엄격한 실시간 차단선이 아니다.
- 전환한 계정이 90% 미만이면, 마지막 턴이 사용 한도(`usageLimitExceeded`)로 실패한
  대화마다 「이어서 해줘」 턴을 한 번 시작한다. 사용자가 그 뒤에 이미 입력한 대화는
  건드리지 않는다. 그 턴의 화면 표시와 명령 승인 요청은 대화를 연 터미널로 간다.

## 실행 구조

`~/.local/bin/codex`는 이 디렉터리의 `launcher.py`를 가리킨다. 실제 CLI는
`/opt/homebrew/bin/codex`다. 최초 실행 시 백그라운드 감독 프로세스를 시작하고,
같은 사용자 전용 Unix 소켓으로 공식 Codex 터미널을 연결한다. 추가 패키지는 없다.

원래 로그인은 회사 `~/.codex-work`, 개인 `~/.codex`에 각각 남는다. 공식 Codex가
각 로그인의 갱신을 담당한다. 자동 서버에는 `chatgptAuthTokens` 인증으로 선택된
자격증명을 메모리에 전달하며, 원래 인증 파일을 덮어쓰거나 자동 서버에 복사하지 않는다.
사용량 응답의 실제 계정 ID를 확인한 뒤 전환 성공으로 기록한다.

이 인증 방식은 공식 문서의 실험적 app-server 인터페이스다. 설치된 0.167.2의
스키마에는 내부용이라는 표시도 있으므로 안정적인 호환성 계약으로 간주하지 않는다.
버전 변경 뒤 인터페이스가 거부되면 자동 실행을 중단하고 고정 계정 실행을 안내한다.
2026-11-13에 실제 회사 → 개인 → 회사 인증 전환, 각 계정 사용량 조회,
모델 호출 없는 동일한 임시 대화 유지, Unix 소켓 연결을 검증했다. 같은 날 0.168.0
시험 서버에서 한 대화에 회사 → 개인 → 회사 순서로 모델 턴 세 번을 돌려 모두 성공했다
(앞 계정의 암호화 추론 항목이 든 기록 포함). 감독 연결이 시작한 턴의 알림·승인 요청이
대화를 연 연결로 가는 것과, 한도 초과로 끝난 실제 기록 사본에서 「이어서 해줘」가 한 번만
시작되는 것도 확인했다.

자동 세션의 기록은 `~/.codex-auto`에 저장되며 설정·스킬·플러그인은 기존 설정을
공유한다. 모든 자동 세션은 같은 서버와 활성 계정을 사용한다. 이미 열려 있던 기존
세션은 전환 대상에 포함되지 않는다. 이전 개인·회사 프로필의 대화는 각각
`CODEX_ACCOUNT=personal codex resume` 또는 `CODEX_ACCOUNT=company codex resume`으로 연다.

`exec`, `review` 등 비대화형 명령은 시작할 때만 계정을 선택한다. `login`, `logout`,
`mcp`, `plugin`, `queue`, `archive`, `delete` 등 관리 명령은 회사를 기본으로 사용한다.
명시적인 `CODEX_HOME`, `--remote`, `--no-daemon`은 자동 서버를 사용하지 않는다.
`CODEX_HOME="$HOME/.codex-work" codex`로 연 세션은 회사 계정에 고정되어 전환되지
않는다. 회사 우선 자동 전환은 그냥 `codex`로 연다.
자동 기록에 관리 명령을 적용할 때는 `CODEX_HOME="$HOME/.codex-auto"`를 명시한다.

## 검증

```sh
python3 -m unittest discover -s codex/account-switcher -p 'test_*.py' -v
codex --account-status
```

공식 문서: [인증](https://learn.chatgpt.com/docs/auth),
[app-server 인증·사용량·대화 상태](https://learn.chatgpt.com/docs/app-server).
