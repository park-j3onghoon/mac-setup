# Codex 파일 핸들 고갈 수정 검증 — 2026-11-18

## DEBUG REPORT

| 항목 | 결과 |
| --- | --- |
| 증상 | 공유 app-server가 soft limit 256 근처에서 `Too many open files`로 실패. 종료한 대화의 자원과 감독 연결이 남는지 의심됨. |
| 근본 원인 | 작은 시작 한도, 감독에 자동으로 붙은 하위 대화 구독, 수신 실패 후 실제 소켓을 닫지 않는 RPC 경로가 겹침. 열린 TUI의 구독은 정상 동작상 유휴 런타임을 유지함. |
| 수정 | `runtime.py`·`supervisor.py`: 감독의 유휴 구독 반환. `rpc.py`: 수신 종료 시 소켓 닫기. `launcher.py`: 독립 실행까지 시작 한도 보완. `idle.py`: 새 자동 터미널의 안전한 유휴 구독 해제와 동일 대화 재개. |
| 증거 | 소켓 누수·독립 실행 한도 테스트 red→green. 실제 0.169.0 바이너리에서 구독 잔류 재현, 12회 대화 회수, 8회 MCP reload, 유휴 회수와 작업·기록 보존 검증. |
| 회귀 테스트 | `test_rpc.py`, `test_runtime.py`, `test_idle.py`, `test_switcher.py`; 실제 바이너리 재현은 `probe_lifecycle.py`, `probe_subscriptions.py`. |
| 관련 | `71d6d71`의 용량 보완과 `260ac7f`의 감독 알림 차단을 유지. 자원 회수 수정의 첫 커밋은 `291162c`. |
| 상태 | **DONE_WITH_CONCERNS** — 확인한 경로는 수정·검증 완료. 이미 실행 중인 독립 세션에는 소급 적용되지 않으며, 모든 외부 MCP의 내부 누수까지 검증한 것은 아님. |

## 기존 커밋과 실제 적용

`71d6d71`은 새 공유 서버 시작 전 soft limit을 올리는 용량 보완으로 올바르다.
hard limit과 이미 더 높은 soft limit을 보존한다. 다만 기존 서버 재연결과
`--no-daemon`·명시적 `CODEX_HOME` 경로에는 적용되지 않았다. 실행기 진입에서도
같은 함수를 호출하도록 보완했다. 300개 파일을 실제 여는 자식 프로세스가 수정 전
실패하고 수정 후 성공한다. hard limit 512와 기존 soft limit 8192도 그대로 보존한다.

14:25 KST에 자식 명령이 상속한 `RLIMIT_NOFILE`을 별도로 측정했다.

| 대상 | 시작 시각 / PID | soft / hard |
| --- | --- | --- |
| 이번 `--no-daemon` 세션 | 13:33:03 / 92008 | **256 / unlimited** |
| 현재 공유 서버 | 13:48:26 / 717 | **4096 / unlimited** |
| 수정된 실행기로 새로 시작한 격리 app-server | 임시 홈, 측정 후 종료 | **4096 / unlimited** |

handoff의 공유 서버는 PID 5380이었다. 조사 중 이 세션 밖에서 공유 서버가 교체되어
현재 감독 716과 서버 717은 13:48:26에 시작한 상태다. 이번 작업에서는 공유 서버나
감독을 종료·재시작하지 않았다. 현재 실행기의 심볼릭 링크는 이 저장소 `launcher.py`를
가리킨다. 감독·런타임 수정 파일은 각각 13:42·13:43에 저장되어 새 감독 시작보다 빠르다.
다만 운영 감독의 개별 구독 해제 이벤트는 별도 계측하지 않았으므로, 시작 시각을 근거로
모든 운영 회수 동작이 관측됐다고 주장하지 않는다.

새 유휴 프록시는 앞으로 일반 `codex`로 여는 자동 터미널부터 적용된다.
기존 연결과 이번 독립 세션에는 붙이지 않았다. 현재 독립 세션의 한도 256도 유지된다.
한도 증설은 누수 해결의 증거가 아니다.

14:28 점검에서 작업 도중 **14:06:46~14:12:42에 시작한 운영 프록시 7개**도 발견했다
(PID 16685, 21462, 24253, 24430, 24662, 24792, 25066). 저장소를 직접 가리키는 실행기를
통해 열린 연결이며, 격리 실험의 잔류 프로세스가 아니다. 최종 경계 조건 수정 전의 코드를
메모리에 갖고 있으므로 최신 동작이 모두 적용됐다고 볼 수 없다. 활성 작업을 끊지 않기 위해
종료하지 않았다. 이 터미널은 작업을 마친 뒤 새로 열어야 최종 프록시가 적용된다.

## 원인별 격리 재현

공식 `codex 0.169.0`, 임시 `CODEX_HOME`, 가짜 stdio MCP와 localhost Responses 서버를
사용했다. 사용자 인증·설정을 복사하지 않고 실제 모델 호출 없이 수행했다.
FD는 `lsof -F ft`에서 숫자 descriptor만 세고, 부모와 직접 자식의 종류를 따로 기록했다.
실험 서버의 unload 유예는 1초, 재시작 경계 실험은 5초로 줄였다.

| 경로 | 관측 | 판단·수정 |
| --- | --- | --- |
| RPC reader 오류 | 수정 전 소켓 `fileno()`가 3으로 남음. 수정 후 -1 | 닫힘 플래그만 갱신하던 경로에서 실제 소켓을 닫음. |
| 감독과 같은 관찰자 연결 | 소유자 종료 후 자식 1개가 loaded 상태로 남음. 관찰자 구독 해제 후 0개, 서버 FD 49→47 | 알림 opt-out은 구독 해제가 아님. 감독이 60초마다 자신의 유휴 구독을 반환하도록 수정. |
| 대화 12회 생성·종료 | 각 종료 후 FD **35**로 복귀, loaded 0, 호출한 MCP PID 모두 사라짐 | 이 반복 경로에서 누적 증가 없음. 생성 직후 대개 41, 초기 기준 34. 워밍업 IPv4 소켓 1개를 구분함. |
| 동일 설정 MCP reload 8회 | FD 40→38, 동일 MCP worker 유지 | 이 재현에서는 누적 누수 없음. 매번 프로세스를 새로 띄운다는 가설을 지지하지 않음. |
| 터미널 연결을 유지한 유휴 회수 | FD **54→48**, PIPE **7→2**, 가짜 MCP 자식 1→0 | 연결은 유지하고 대화 런타임 회수. 다음 입력은 같은 thread ID, 기록 1→2턴. |
| 실행 중 응답 | 3초 동안 active 유지. 완료 후 FD 53→48 | active 턴을 회수하지 않음. 이후 같은 대화의 기록 3턴 확인. |
| idle 상태의 백그라운드 명령 | 4초 후에도 같은 processId **79373** | `idle` 상태만으로 회수하지 않음. backgroundTerminals를 별도 검사. |
| 부모·자식과 대기 메시지 | loaded 2→부모만 유지. 자식 재개 후 sentinel 전달 확인, 부모 기록 3턴 | 부모의 메모리 mailbox·환경 보존. 조회 목적으로 자식을 다시 열었다 닫아도 재회수됨. |
| native unload 유예 중 자식 재시작 | 5초 유예 안에 재시작한 뒤 7초 후에도 같은 background processId **52598** | status 알림에서 실제 resume으로 재구독하여 후속 백그라운드 명령 보존. |

대화 회수 뒤 남아 있는 `git` 자식은 MCP가 아니다. 총 FD에는 초기 셸·git 작업과
연결 워밍업도 섞이므로 전체 차이를 전부 MCP 효과로 해석하지 않았다.
모든 외부 DataHub·Redash·Chrome 구현을 장시간 부하 시험한 결과는 아니다.

## 유휴 회수의 보존 조건

기본 `CODEX_IDLE_SECONDS=900`이다. 프록시가 마지막 대화 활동 후 15분에 다음 조건을
확인하고 **자기 연결의 구독만** 해제한다. 모든 구독이 사라지고 계속 idle이면 공식
서버가 기본 60초 뒤 런타임을 내리므로, 다른 구독이 없는 경우 대략 16분이다.
[공식 app-server 문서](https://learn.chatgpt.com/docs/app-server)의 구독·회수 계약을 사용한다.

- 실행 중 응답·승인·요청이 없고, 백그라운드 명령·미완료 goal·대기 입력이 없어야 한다.
- 저장된 턴이 있어야 한다. 기록 파일과 터미널 입력 초안은 유지하며 다음 요청 전에 같은 ID로 재개한다.
- ephemeral, realtime, 동적 도구·특수 환경, 변경된 sticky 설정 등 정확히 복원할 수 없는 상태는 유지한다.
- 자식의 mailbox·환경을 소유하는 부모와 조상은 유지한다. 기존 기록을 resume·fork한 최상위 대화도 숨은 ephemeral 자식 상태를 확인할 수 없어 유지한다.
- 하위 대화의 재시작을 감지하면 실제 구독을 복구한다. native의 일시적인 closing 응답은 최대 30초 재시도한다.
- 재개 실패 시 입력을 전송하기 전에 거절하여 TUI가 composer에 복원하도록 한다.

공식 TUI는 `thread/closed`를 받으면 종료하므로, 프록시는 자신이 의도한 회수의 종료
알림을 TUI에 전달하지 않는다. 최대 메시지 크기는 공식 remote TUI와 같은 128 MiB다.
프록시는 터미널마다 별도 소형 프로세스·전용 소켓을 사용하며 연결 종료 시 정리한다.
공유 서버에 강제 unload 또는 전역 종료 명령을 보내지 않는다.

원복은 새 터미널에서 `CODEX_IDLE_SECONDS=0 codex`로 한다. 30분으로 바꾸려면
`CODEX_IDLE_SECONDS=1800 codex`를 쓴다. `--no-daemon`, 고정 계정, 명시적
`CODEX_HOME`·`--remote`, 이미 열린 연결은 프록시 대상이 아니다.

## 로컬 MCP 실행 줄이기

현재 로컬 DataHub·Redash는 데이터 플러그인의 stdio 프로세스이고, Chrome은 브리지
클라이언트와 공유 데몬 구조다. 데이터·브라우저 도구가 필요 없는 **새 독립 세션**에만:

```sh
codex --no-daemon \
  -c 'plugins."<data-plugin>@<marketplace>".enabled=false' \
  -c 'mcp_servers.chrome-devtools.enabled=false'
```

전역 설정이나 다른 활성 세션을 바꾸지 않는다. 공유 Chrome 데몬을 종료하지 않는다.
원격 앱 도구가 많다는 이유만으로 같은 수의 로컬 프로세스가 생기는 것도 아니다.

`codex --no-daemon --enable mcp_lazy_stdio_startup`은 0.169.0의 실험적 대안이다.
첫 캐시 수집 때는 MCP가 시작됐고, 두 번째·세 번째 대화는 호출 전 MCP 0개/FD 36,
호출 후 MCP 1개/FD 39였다. unload 뒤 MCP 0개/FD 35로 돌아왔다.
캐시·플러그인 선택·필수 서버 조건에 따라 여전히 미리 실행할 수 있다.
도구 설명의 지연 노출이 stdio 시작 지연을 의미하지는 않는다.

`mcp_connection_sharing`도 실험 기능이며 최신 lease 프로토콜을 지원하는 서버가
필요하다. 기존 2025-06-18 stdio 서버에 플래그만 켜서 프로세스가 모두 공유된다고
가정하지 않는다. 설정 선택지는 [공식 설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference)와
설치 버전의 소스를 함께 확인했다. 기본 설정을 일괄 비활성화하지 않았다.

## 테스트·증거 보존

전체 단위 테스트 68개가 Python 3.15와 운영 감독의 Python 3.10에서 모두 통과했다.
실제 바이너리 통합 실험 여섯 가지도 모두 종료 코드 0.
리뷰 뒤 진단 RPC 자체를 실패시키는 결함 주입으로 실험용 프로세스 정리도 확인했다.

```sh
python3 -m unittest discover -s codex/account-switcher -p 'test_*.py' -v
python3 codex/account-switcher/probe_lifecycle.py
python3 codex/account-switcher/probe_lifecycle.py --lazy --cycles 3
python3 codex/account-switcher/probe_subscriptions.py
python3 codex/account-switcher/probe_subscriptions.py --proxy
python3 codex/account-switcher/probe_subscriptions.py --proxy --active
python3 codex/account-switcher/probe_subscriptions.py --proxy --background
python3 codex/account-switcher/probe_subscriptions.py --proxy --child
python3 codex/account-switcher/probe_subscriptions.py --proxy --child --child-restart
```

probe는 macOS의 `/opt/homebrew/bin/codex`, `/opt/homebrew/bin/python3`, `lsof`, `ps`를
사용한다. 출력 JSON·로그는 `/private/tmp/codex-*.json`·로그 파일에 남는다.
최종 검증 출력과 red→green 증거 사본은 아래 복구 디렉터리의 `validation/`에 보존한다.

`~/<작업 폴더>/.codex-recovery/<thread-id>/`

기존 백업 rollout 9개, **211,566,984 bytes**의 SHA-256이 원래 manifest와 모두 일치했다
(14:16:47 KST). 원래 handoff·manifest·rollout을 수정하지 않았다.
14:02 운영 스냅샷은 공유 서버 FD 152, 감독 9, 이번 독립 세션 88이었다.
이 값은 활성 대화를 포함한 현황이며 격리 실험의 회수 전후 값과 직접 비교하지 않는다.
`application-limits-20261118.json`과 `live-resources-20261118.json`에 적용·프로세스 증거가 있다.

설치 버전 근거는 공식 소스 commit `d32063f96c2dff1dc96af839b3952abb6acfeda4`이다:
[자동 구독](https://github.com/openai/codex/blob/d32063f96c2dff1dc96af839b3952abb6acfeda4/codex-rs/app-server/src/lib.rs),
[하위 대화 회수와 mailbox](https://github.com/openai/codex/blob/d32063f96c2dff1dc96af839b3952abb6acfeda4/codex-rs/core/src/agent/control/residency.rs),
[TUI 종료 처리](https://github.com/openai/codex/blob/d32063f96c2dff1dc96af839b3952abb6acfeda4/codex-rs/tui/src/chatwidget/protocol_requests.rs).
