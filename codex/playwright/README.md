# 공유 Playwright 브라우저 연결

여러 AI 세션이 Node 서버 하나를 공유한다. Chrome의 기존 로그인은 유지하고 각 AI가 제어하는 탭은 확장 프로그램이 분리한다.

## 설치

1. 사용할 Chrome 프로필에 [Microsoft Playwright Extension](https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm)을 설치한다. 백그라운드 연결에는 확장 0.5.0 이상과 Chrome 158.0.8127.2 이상이 필요하다.
2. 이 디렉토리에서 `npm ci --ignore-scripts`를 실행한다. 버전과 의존성 무결성은 `package-lock.json`으로 고정한다.
3. 확장 아이콘의 Manage clients 페이지에서 토큰을 확인한다. `python3 install.py --profile Default`를 실행하고 비밀번호 입력 칸에 토큰 값만 붙여 넣는다. 토큰은 셸 명령 인자나 Git에 넣지 않는다.
4. Codex 설정에 아래 연결을 추가한다. 새 연결이 검증되면 기존 `chrome-devtools` 서버를 비활성화한다. 이미 실행 중인 Chrome 공유 서버는 다른 세션이 사용하므로 강제로 종료하지 않는다.

```toml
[mcp_servers.playwright]
url = "http://127.0.0.1:8931/mcp"
startup_timeout_sec = 60
tool_timeout_sec = 60
```

서버는 `127.0.0.1`에만 바인딩하며 launchd가 로그인 시 실행하고 예기치 않은 종료 뒤 다시 실행한다. 토큰은 `~/Library/LaunchAgents/local.codex-playwright.plist`에 사용자만 읽고 쓸 수 있는 권한(0600)으로 저장된다. 해당 파일과 `launchctl print`의 환경 변수 출력은 공유하지 않는다. 설치 명령을 다시 실행하면 이 서버만 재시작하므로 활성 세션이 없는 때 수행한다.

서버 프로세스만 공유한다. `--shared-browser-context`를 켜면 확장 연결까지 합쳐져 세션별 탭 소유권의 경계가 달라지므로 사용하지 않는다. 각 세션은 자신의 탭을 열고 닫으며 다른 세션의 탭을 조작하지 않는다. 로그인 쿠키는 같은 Chrome 프로필을 사용하므로 공유된다.

토큰으로 연결한 새 클라이언트는 빈 작업 탭에서 시작한다. `--background`로 사용자의 활성 탭과 포커스를 유지한다. 작업 탭은 확인을 마치면 닫고 사용자에게 보여 준 탭은 남긴다.

## 상태 확인과 인증 변경

- 서비스 이름: `local.codex-playwright`
- 로그: `~/.local/share/codex-playwright/server.log`
- 토큰을 교체하면 새 토큰으로 설치 명령을 다시 실행한다.
- 사이트 로그인 만료와 확장 토큰은 별개다.
- 전환 취소 시 Codex의 `playwright`를 비활성화하고 기존 `chrome-devtools` 설정을 다시 활성화한다. 서버 종료는 `launchctl bootout gui/$(id -u)/local.codex-playwright`로 수행한다.

공식 근거: [HTTP 공유 서버](https://github.com/microsoft/playwright-mcp#standalone-mcp-server), [확장 토큰과 탭 소유권](https://github.com/microsoft/playwright/blob/main/packages/extension/README.md).
