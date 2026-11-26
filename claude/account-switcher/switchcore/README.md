# 계정 전환기 공용 코드 (switchcore)

[Claude 전환기](../README.md)와 [Codex 전환기](../../../codex/account-switcher/README.md)가 함께 쓰는 코드다. 원본은 이 폴더이고, `codex/account-switcher/switchcore`는 이 폴더를 가리키는 상대 심링크다.

## 바꿀 수 있는 것

| 무엇 | 인터페이스 | 내장 구현(설정 이름) |
|---|---|---|
| 전환 규칙과 조회 간격 | `policy.SwitchPolicy` | `priority`(Claude 기본), `strict-priority`(Codex 기본) |
| 재시작 도우미가 쓰는 터미널 | `terminal.Terminal` | `cmux`(기본) |

구현은 각 컴퓨터의 로컬 설정 파일(git이 추적하지 않는 `private/`)에 적은 이름으로만 고른다. repo 밖 Python 파일은 불러오지 않는다. 두 전환기 모두 두 계정의 token을 다루는 프로세스라서 그 안에서 남의 코드가 돌 길을 만들지 않는다.

그 밖의 기능(사용량 조회, 로그인 교체, Keychain, launchd, Codex 공유 서버 운영, Claude 측정)은 전환기마다 구현이 하나라 인터페이스로 나누지 않았다.

### 전환 규칙 `SwitchPolicy`

- `choose(order, active, readings, now)`: 지금 쓸 계정. `order`는 우선 계정이 앞에 온 계정 이름 목록이고, `readings`는 이번 주기에 읽은 계정의 `quota.Usage`다. `Decision.target`이 None이면 바꾸지 않는다.
- `available(usage, now)`: 그 계정으로 바꿔도 되는지. 두 전환기는 로그인을 바꾸기 직전에 이것으로 한 번 더 묻는다.
- `poll_seconds(usage)`: 다음 사용량 조회까지의 초. 전환기는 `poll_interval(policy, usage)`로 물어 `LONGEST_POLL_SECONDS`(540초)를 넘지 않게 한다. 작업 대시보드가 상태 파일을 믿는 10분과 Claude 재시작 도우미가 전환을 기다리는 15분보다 짧아야 하기 때문이다.

두 내장 규칙은 지금 두 전환기의 규칙을 그대로 옮긴 것이다. 조회 간격 계단은 같다. 기준까지 30%p 이상 남으면 540초, 15%p 이상 300초, 5%p 이상 120초, 그보다 가깝거나 사용량이 없으면 가장 짧은 간격이다(`POLL_TIERS`).

| 경우 | `priority` | `strict-priority` |
|---|---|---|
| 우선 계정 사용량을 확인 못 함 | 지금 계정 유지 | 결정 없음 |
| 모든 계정이 기준 이상 | 결정 없음 | 지금 계정(없으면 우선 계정) |
| 조회 시각 | 90초 안의 조회만 믿음 | 보지 않음 |

`priority`가 확인 못 한 우선 계정에서 지금 계정을 유지하는 이유는 Claude 사용량 API가 조회의 절반가량에 HTTP 429로 답해서다. 이걸 한도 도달로 읽었더니 1~2분마다 계정이 바뀌었다(2026-11-13, 36번).

### 터미널 `Terminal`

- `pane_in(environment)`: 그 환경 변수를 가진 프로세스가 떠 있는 창. 이 터미널 밖이면 None이다. 훅은 자기 환경으로, 멈춘 세션 찾기는 다른 Claude 프로세스의 환경으로 부른다.
- `read_screen(pane, lines)`: 창의 마지막 줄들. 지금 못 읽으면 `TerminalUnavailable`을 낸다. 도우미는 기다리는 동안에는 이것을 「아직 준비 안 됨」으로 보고 다시 본다.
- `submit(pane, text)`: 글자와 Enter를 한 요청으로 넣는다. 제출을 확인하지 못하면 `OSError`이고, 이때는 글이 들어갔을 수도 있다.

도우미는 입력창이 비었는지 마지막으로 확인한 직후에 `submit`을 부른다. 확인과 넣기 사이에 사용자가 친 글이 섞일 수 있는 틈만 남는다. 넣는 글은 코드 상수(`/restart`와 이어하기 지시)뿐이다. Claude Code 입력창은 `!`로 시작하는 줄을 셸 명령으로 돌리기 때문에, 설정이나 대화 기록에서 온 글은 넣지 않는다.

## 로컬 설정

### Claude: `private/claude/account-switcher/config.json`

`switcher.py init`이 만든 파일에 선택 키를 더한다. 키가 없으면 지금 구현이다.

```json
{"policy": "priority", "terminal": "cmux"}
```

서비스는 시작할 때 읽고, Stop 훅은 턴이 끝날 때마다 `terminal`을 읽는다. 훅이 모르는 터미널 이름을 만나면 아무것도 띄우지 않고 상태 폴더 `session-restarts.log`에 `config_error:terminal`을 남긴다. 파일 자체를 못 읽으면 다른 훅 오류처럼 아무것도 하지 않는다.

### Codex: `private/codex/account-switcher/config.json`

파일이 없으면 지금 기본값(Codex README 「실행 구조」의 회사와 개인 홈, 90%, `strict-priority`)이다.

```json
{"homes": {"company": ".codex-work", "personal": ".codex"}, "threshold": 90, "policy": "strict-priority"}
```

- `homes`: 홈 바로 아래 폴더 이름이다. 계정 이름은 `company`와 `personal` 두 개로 고정이다. 작업 대시보드와 `CODEX_ACCOUNT` 값이 이 이름을 쓴다.
- `threshold`: 1~100 사이의 숫자다.
- 우선 계정은 이 파일이 아니라 `~/.codex-auto/preference.json`으로 고른다.
- 폴더와 파일이 링크이거나 내 소유가 아니면 읽지 않는다. 폴더는 시작할 때 0700으로 맞춘다.
- 잘못된 값이 있으면 실행기는 고칠 값을 알려 주고 멈춘다. `CODEX_ACCOUNT`로 계정을 고른 실행도 멈추고, `CODEX_HOME`을 직접 준 실행만 이 파일을 읽지 않고 돈다. 감독은 상태 파일에 `status: failed`와 `settings_error`를 남긴다.
- 홈을 다른 워크스페이스가 든 폴더로 바꾸면, 그 이름을 `codex --account-register company`(또는 `personal`)로 다시 등록할 때까지 그 계정을 쓰지 않는다(`degraded`).

### 설정을 바꾼 뒤

Claude `terminal`은 다음 턴 끝부터 쓰인다. Codex 실행기는 `codex`를 실행할 때마다 읽는다. 나머지는 서비스가 시작할 때 읽으므로 서비스를 다시 띄운다.

```sh
launchctl kickstart -k "gui/$(id -u)/local.claude-account-switcher"
launchctl kickstart -k "gui/$(id -u)/local.codex-account-switcher"
```

Codex 감독을 다시 띄워도 공유 서버와 열린 대화는 그대로다(Codex README). 회사 홈을 바꿨다면 공유 서버는 다음에 새로 뜰 때부터 새 홈의 `config.toml`을 쓴다.

## 새 구현 더하기

1. 이 폴더에 구현을 둔다. 인터페이스의 메서드만 맞추면 되고 상속은 필요 없다. 생성자는 규칙이 `cls(threshold, shortest_poll)`, 터미널이 `cls()` 모양이어야 한다. 전환기가 이 모양으로 만든다. 규칙의 예는 `policy.py`의 두 내장 규칙이다. 터미널의 가장 작은 예는 `../tests/test_refresh.py`의 `FakeTerminal`이고, 테스트가 이 가짜로 재시작 흐름 전체를 돌린다.
2. 이름표에 한 줄을 더한다. 터미널은 `choices.py`의 `TERMINALS`, 규칙은 `policy.py` 끝의 `POLICIES`다. 훅은 매 턴 돌기 때문에 터미널 이름표가 규칙 모듈을 불러오지 않게 표를 나눴다.
3. 로컬 설정에 그 이름을 쓴다.
4. `tests/`에 테스트를 더하고 아래 명령으로 확인한다.

예를 들어 tmux 터미널은 이런 모양이 된다. 두 메서드의 tmux 명령은 직접 정하고 시험해야 한다.

```python
# switchcore/tmux.py
class TmuxTerminal:
    def pane_in(self, environment):
        return environment.get('TMUX_PANE') or None  # tmux가 창 안 프로세스에 주는 창 ID

    def read_screen(self, pane, lines):
        ...  # 그 창의 마지막 lines줄. 못 읽으면 TerminalUnavailable

    def submit(self, pane, text):
        ...  # 글자와 Enter를 한 요청으로. 제출을 확인하지 못하면 OSError

# switchcore/choices.py
TERMINALS = {'cmux': CmuxTerminal, 'tmux': TmuxTerminal}
```

그다음 Claude 설정에 `"terminal": "tmux"`를 쓴다. 창 ID는 재시작 기록 이름에 해시로만 들어가므로 형식 제약이 없다.

## 테스트

switchcore 안에서는 상대 import만 쓰고 파일 경로를 만들지 않는다. Codex 폴더에 `policy.py`와 `usage.py`가 따로 있어서 맨이름 import는 폴더마다 다른 파일로 풀린다. 심링크로 불린 모듈의 `__file__`은 Codex 쪽 경로이고 `resolve()`하면 이 폴더라서, 파일 경로도 어느 쪽으로 만드느냐에 따라 달라진다. 그래서 switchcore 테스트는 두 전환기 폴더에서 모두 돌린다.

Python 3.10에서도 돌아야 한다(3.11 이후 API를 쓰지 않는다). Claude 서비스는 `service-install`을 실행한 Python으로, Codex 감독은 감독을 설치한 `codex` 실행의 Python 버전으로, 훅과 Codex 실행기는 PATH의 `python3`로 돌아 버전이 서로 다를 수 있다. 테스트는 그 컴퓨터에서 쓰는 버전 모두로 돌린다.

```sh
cd "$HOME/git/mac-setup/claude/account-switcher"
python3 -m unittest discover -s tests
python3 -m unittest discover -s switchcore/tests
cd "$HOME/git/mac-setup/codex/account-switcher"
python3 -m unittest discover -s switchcore/tests
cd "$HOME/git/mac-setup"
python3 -m unittest discover -s codex/account-switcher -p 'test_*.py'
```
