# 공유 Playwright 브라우저 연결

여러 AI 세션이 Node 서버 하나를 공유한다. Chrome의 기존 로그인은 유지하고 각 AI가 제어하는 탭은 확장 프로그램이 분리한다.

## 설치

1. 사용할 Chrome 프로필에 [Microsoft Playwright Extension](https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm)을 설치한다. 백그라운드 연결에는 확장 0.5.0 이상과 Chrome 158.0.8127.2 이상이 필요하다.
2. 이 디렉토리에서 `npm ci --ignore-scripts`를 실행한다. 버전과 의존성 무결성은 `package-lock.json`으로 고정한다.
3. 확장 아이콘의 Manage clients 페이지에서 토큰을 확인한다. 영구 설치 경로인 `~/git/mac-setup/codex/playwright`에서 `python3 install.py --profile Default`를 실행하고 비밀번호 입력 칸에 토큰 값만 붙여 넣는다. 임시 worktree에서 설치하면 서비스가 임시 경로를 계속 참조하므로 사용하지 않는다. 토큰은 셸 명령 인자나 Git에 넣지 않는다.
4. Codex 설정에 아래 연결을 추가한다. 새 연결이 검증되면 기존 `chrome-devtools` 서버를 비활성화한다. 이미 실행 중인 Chrome 공유 서버는 다른 세션이 사용하므로 강제로 종료하지 않는다.

```toml
[mcp_servers.playwright]
url = "http://127.0.0.1:8932/mcp"
startup_timeout_sec = 60
tool_timeout_sec = 90
```

서버는 `127.0.0.1`에만 바인딩하며 launchd가 로그인 시 실행하고 예기치 않은 종료 뒤 다시 실행한다. 토큰은 `~/Library/LaunchAgents/local.codex-playwright-performance.plist`에 사용자만 읽고 쓸 수 있는 권한(0600)으로 저장된다. 해당 파일과 `launchctl print`의 환경 변수 출력은 공유하지 않는다. 설치 명령은 로드된 서비스를 덮어쓰지 않는다. 기존 8931 서비스와 연결은 전환 중 유지하며 새 세션은 8932를 사용한다.

서버 프로세스만 공유한다. `--shared-browser-context`를 켜면 확장 연결까지 합쳐져 세션별 탭 소유권의 경계가 달라지므로 사용하지 않는다. 각 세션은 자신의 탭을 열고 닫으며 다른 세션의 탭을 조작하지 않는다. 로그인 쿠키는 같은 Chrome 프로필을 사용하므로 공유된다.

HTTP 엔드포인트에는 별도 인증이 없으므로 같은 머신의 로컬 프로세스도 접근할 수 있다. 확장 토큰은 서버와 Chrome 확장 사이의 연결 인증이다.

토큰으로 연결한 새 클라이언트는 확장 연결 페이지에서 시작한다. `--background`로 사용자의 활성 탭과 포커스를 유지한다. 도구 실행 중에만 해당 페이지에 focus emulation을 적용하고 마지막에 해제한다. 작업 탭은 확인을 마치면 닫는다. 사용자에게 남길 탭은 `browser_keep_tab(keep=true)`로 표시해야 종료와 유휴 정리 후에도 남는다. 이 표시는 탭을 앞으로 가져오지 않는다. 다른 사용자 탭을 자동 정리 대상으로 등록하지 않는다.

로컬 HTML은 Playwright의 기본 설정에서 `file://`로 탐색할 수 없다. 검증할 파일 디렉토리만 loopback HTTP 서버로 제공하고 검증 후 서버를 닫는다. 완성된 로컬 리포트의 최종 표시는 승인된 macOS 파일 열기 경로를 사용한다. 이 용도로 전역 파일 접근 제한을 해제하지 않는다.

## 상태 확인과 인증 변경

- `node verify.mjs http://127.0.0.1:8932/mcp`는 실제 Chrome에서 세 클라이언트의 클릭, 탭과 파일 분리, 독립 종료와 재연결을 검증한다. 로컬 시험 페이지와 작업 탭은 끝나면 닫는다.
- 서비스 이름: `local.codex-playwright-performance`
- 로그: `~/.local/share/codex-playwright/performance-server.log`
- 토큰을 교체하면 새 토큰으로 설치 명령을 다시 실행한다.
- 사이트 로그인 만료와 확장 토큰은 별개다.
- 전환 취소 시 아직 실행 중인 8931 서비스로 URL을 되돌린다. 서비스 종료는 활성 세션이 없음을 확인한 뒤 `launchctl bootout gui/$(id -u)/local.codex-playwright-performance`로 수행한다.

## 성능 제한과 동작

| 항목 | 적용 |
|---|---|
| 1. 백그라운드 클릭 | 승인된 페이지 CDP 세션에 실행 중 focus emulation, 종료 시 해제 |
| 2. 잔류 작업 탭 | 세션 종료와 유휴 회수 때 생성한 탭만 정리, keep 표시 보존 |
| 3. 요청 기록 | 탭당 최신 500개와 생략 안내 |
| 4. 평가 대기 | 기본 추가 대기 없음, 반환 Promise는 await |
| 5. 큰 DOM | 자동 스냅샷 없음, 명시적 snapshot의 큰 결과는 파일 |
| 6. 파일과 서버 로그 | 자동 산출물 64 MiB 정리 기준, 7일 보관, 로그 4 MiB 순환 |
| 7. 이벤트 | 탭당 최신 1,000개와 생략 안내 |
| 8. 콘솔 | 100ms 묶음 쓰기, 대기 1,000개, 메시지 8 KiB, 파일 8 MiB 제한 |
| 9. 탭 헤더 | 일반 응답은 현재 탭 조회, 명시적 탭 목록은 전체 갱신 |
| 10. WebMCP | 자동 탐색 비활성화 |
| 11. 관련 없는 네트워크 | 추가 완료 대기는 waitForSettled=true로 선택 |
| 12. 스크린샷 | CSS 해상도 기본, 사전 계산 800만 픽셀 초과 거부 |
| 13. 반환값 | 페이지에서 직렬화 예산 8 MiB, 10만 값, 깊이 30, 인라인 64 KiB |
| 14. 동시 작업 | 전역 4개 실행과 32개 대기, 세션당 1개 실행, 대기 취소 지원 |
| 15. 연결 | 생성 중 연결을 포함해 최대 16개 |
| 16. 확장 리스너 | 공식 소유권 필터 유지, 연결 상한과 유휴 회수로 비용 제한 |
| 17. 유휴 | 마지막 도구 완료 후 30분, 다음 호출에서 재연결 |
| 18. 생존 확인 | 15초 간격, 응답 여유 30초, 완료와 종료 시 타이머 정리 |
| 19. 시간 제한 | 탐색 45초, 평가 40초, Codex 도구 90초 |
| 20. 기존 DevTools | retire-when-idle 등록 후 마지막 연결이 끝날 때만 종료 |

`browser_evaluate`는 Map, Set, Error를 명시적인 JSON 구조로 변환한다. 순환 참조는 `[Circular]`로 표시한다. 그 밖의 사용자 정의 객체는 일반 JSON으로 변환해서 반환해야 한다. 직렬화 예산은 문자열 이스케이프의 최악 크기를 포함해 보수적으로 계산한다. 평가 시간 초과는 페이지에서 이미 시작한 부수 효과의 취소를 보장하지 않는다.

클릭 후 별도 API나 화면 변경을 기다려야 하면 `browser_wait_for`, 명시적 await 또는 `waitForSettled=true`를 사용한다. 큰 스냅샷은 `target`과 `depth`로 좁힌다. 페이지 JavaScript는 `browser_evaluate`로 실행하며, 공유 Node 프로세스 안에서 임의 코드를 실행하는 `browser_run_code_unsafe`는 제공하지 않는다.

파일 정리는 자동 산출물 디렉토리에만 60초 간격으로 적용하며, 최근 60초 파일과 사용자가 명시적으로 지정한 결과 파일은 지우지 않는다. 따라서 64 MiB는 순간적인 하드 디스크 상한이 아니다. 서버 로그는 launchd의 열린 파일을 유지하려고 같은 inode를 비우며 이전 로그는 보존하지 않는다. 단일 Node 이벤트 루프와 공식 확장의 세션별 리스너 비용 자체가 없어지는 것은 아니다.

런타임 보완은 고정된 `playwright-core` 소스의 SHA-256을 확인하고 메모리에서만 적용한다. 의존성을 올리면 검토 전까지 시작을 거부한다. 서명된 Chrome 확장 파일과 node_modules 원본은 수정하지 않는다.

검증: `node --test runtime.test.mjs`, `python3 verify-server.py verify.mjs performance-verify.mjs`, `python3 verify-server.py --lifecycle lifecycle-verify.mjs`. 시험 서버는 기존 서비스의 토큰을 프로세스 환경으로만 전달하고 시험 종료 후 자신이 만든 프로세스를 종료한다. lifecycle 검증에서만 연결 상한 2개와 유휴 2초를 사용한다.

공식 근거: [HTTP 공유 서버](https://github.com/microsoft/playwright-mcp#standalone-mcp-server), [확장 토큰과 탭 소유권](https://github.com/microsoft/playwright/blob/main/packages/extension/README.md).
