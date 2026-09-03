# Extended Thinking (사고 강도)

사고(확장 추론) 강도는 **작업 난이도에 비례**해서 쓴다. 단순 읽기·기계적 편집·짧은 질의는 깊이 사고하지 않고 빠르게 처리하고, 설계·디버깅·리팩토링·리뷰처럼 실제 추론이 필요한 작업에만 깊게 사고한다. 사소한 모든 스텝까지 최대 강도로 사고하지 않는다(이게 응답 지연의 주범이었다).
- Codex: `~/.codex/config.toml`의 `model_reasoning_effort = "xhigh"`는 리뷰·근본원인 진단 위임 품질을 위해 유지한다. 속도가 급한 일상 작업은 일시적으로 `high`로 낮춰도 된다.
- Claude Code: 기본 `effortLevel`은 `medium`(settings.json). 특정 작업에 더 깊은 사고가 필요하면 그 요청에 **`ultrathink`**를 붙여 해당 턴만 최대로 올린다.
- 깊게 사고할 때의 방식: 복잡한 문제는 단계별로 분해하고, 코드 분석 시 전체 흐름과 엣지 케이스를 추적한다.

# 개인 글로벌 설정

- **코드 작성/수정 전에 `~/.claude/coding-rules.md`를 읽고 적용한다.** 서브 파일(`coding-rules-*.md`) 참조가 있으면 현재 작업 언어/도메인에 해당하는 것도 읽는다.
- **billingsvc 레포 작업 시 `~/.claude/billingsvc-rules.md`를 읽고 적용한다** (날짜 타입: 신규 코드 LocalDate 금지·date 사용 등).
- **API를 작성·수정할 때 `api-design-aip` 스킬을 적용한다.** 신규 API는 Google AIP(API Improvement Proposals)를 따르고, 기존 API는 수정 시 해당 엔드포인트를 하나씩 마이그레이션한다. proto(gRPC)·REST(OpenAPI) 두 트랙 모두 적용. 팀 컨벤션과 충돌하는 항목(응답 엔벨로프·offset 페이지네이션)은 보류하고 충돌 없는 항목부터 적용한다.
- **계획을 세운 후 구현 전에 반드시 `/plan-review` 스킬을 실행한다.** Plan Mode 여부와 무관하게 적용.
- **PR 생성 전, 그리고 기존 PR에 push 전에** 반드시 `/review` 스킬을 **먼저** 실행한다. `/review` 완료 후 `/pr-size-check`를 실행한다. **이 순서를 절대 건너뛰거나 뒤바꾸지 않는다.**
- 보안 관련 코드를 변경할 때 (인증, 권한, 시크릿 처리, API 엔드포인트 추가, 결제/민감 데이터) `/cso` 스킬을 `--diff` 모드로 실행한다.
- 세션 시작 시 코드 구현/수정 작업이 예상되면, 작업 대상 디렉토리를 사용자에게 확인한 후 `/guard` 스킬을 실행하여 해당 디렉토리 외부 편집을 제한한다. 조사/분석만 하는 세션에서는 guard를 걸지 않는다.
- **규모 있는 작업(구현/리팩토링/조사 등 여러 단계에 걸쳐 플랜·컨텍스트가 쌓인 작업) 마무리 시**, 사용자 요청이 없어도 다음 세션 시작용 프롬프트를 선제적으로 정리해서 제시한다. 포함 항목: ① 작업 대상 repo/디렉토리 ② 현재 상태(완료/대기) ③ 계획·분석 파일 경로 ④ 남은 단계 ⑤ 다음 액션 힌트. 형식은 사용자가 복사-붙여넣기 가능한 코드 블록으로. 단순 1회성 질문·답변에는 적용하지 않는다.

## 탭 이름·세션 이름 자동 설정

- 작업 컨텍스트가 생기면 `bash ~/.claude/set-tab-title.sh "<제목>"` 로 **터미널 탭 제목과 Claude Code 세션 이름을 같은 값으로** 바꾼다. 스크립트가 둘 다 처리하므로 사용자에게 `/rename` 을 따로 요청하지 않는다.
  - 탭 제목: cmux 안에서는 `cmux rename-tab`(sticky 제목), 그 외 Ghostty 에서는 PTY 에 OSC 2 직접 쓰기. Bash 도구 stdout 은 파이프라 OSC 가 터미널에 안 닿아 스크립트가 부모 프로세스 체인에서 PTY 를 찾는다.
  - 세션 이름: `/rename` 은 인터랙티브 명령이라 에이전트가 못 부르므로, 스크립트가 트랜스크립트에 `custom-title` 엔트리를 append 한다. Codex 에서 호출하면 `CLAUDE_CODE_SESSION_ID` 가 없어 탭 제목만 바뀐다.
- 트리거별 제목:
  - 사용자가 PR URL 을 주면(예: `.../pull/1698`) → 마지막 숫자로 `1698 review`.
  - 구현 중 PR 을 새로 만들면 → 탭 이름을 그 PR 번호로 교체(예: `1698`).
  - PR 번호가 없으면 → 작업을 공백 포함 10글자 이내로 요약해 제목으로.
- 사용자가 매번 명시 요청하지 않아도 위 트리거에서 자동 적용한다.

## Plan 파일 저장 경로 (CRITICAL)

- Plan·분석·change-summary 등 **작업 설계 문서는 repo 내부 `docs/`가 아닌 `~/plans/{repo이름}/{작업명}/` 하위**에 저장한다.
  - 예: `~/plans/adserver/ads-168-create-view-connect/plan.md`
  - 예: `~/plans/{repo}/{task}/change-summary.md`
- 이유: plan 문서가 PR diff를 부풀려 PR 크기 규칙(400줄 상한)을 초과시키고, 리뷰어가 코드와 같이 리뷰해야 하는 부담이 생긴다. 로컬에서 참고용으로만 유지.
- Plan Mode의 `/Users/teddy.park/.claude/plans/*.md`는 스킬 기본 경로이므로 그대로 사용. `~/plans/{repo}/{task}/plan.md`는 저장(저장용 사본)·공유용 위치.
- `docs/` 아래에 이미 plan을 만들어 커밋한 경우: 파일을 `~/plans/{repo}/{task}/`로 옮기고, 해당 커밋은 soft reset 후 재작성하여 diff에서 제외한다 (push 전에만 가능; push 후에는 force push 필요하므로 사용자에게 안내).

## 개인 repo vs 회사 repo 워크플로우 (CRITICAL)

- **개인 repo**(mac-setup, linkcart 등 본인 GitHub 계정 repo): PR 없이 main에 직접 commit·push. 위 `/review`·아래 `teddy/` 브랜치 prefix·PR 생성 규칙 면제. 큰 변경은 백업 브랜치/커밋으로 안전장치만 둔다.
- **회사 repo**(buzzvil 등 팀/조직 repo): `/review` → `/pr-size-check`, `teddy/` 브랜치, PR 생성 규칙(assignee 등) 전부 유지.
- 판단 기준: push 대상이 본인 개인 계정 repo면 개인, 팀/조직 repo면 회사.

## 브랜치 명명 규칙 (CRITICAL, 회사 repo)

- 새 브랜치 생성 시 **반드시 `teddy/` prefix로 시작**한다.
  - 예: `teddy/plb-530-recalculate-payout`, `teddy/fix-billing-cron`
- 기존 브랜치를 checkout하는 경우는 예외.

## PR 생성 규칙 (CRITICAL)

- PR 생성 시 **assignee 는 GitHub username `park-j3onghoon`** 으로 지정한다 (Claude Code / Codex 공통).
  - 주의: displayName 은 `teddy.park` 이지만 GitHub username (gh CLI `--assignee`) 은 `park-j3onghoon`. `teddy.park` 시도 시 "user not found" 에러 발생.
- **reviewer는 추가하지 않는다.** 사용자가 직접 수동으로 지정한다.
- 커밋 메시지, PR 제목/본문은 한글로 작성한다.
- **PR 제목 = `<prefix>: [<Linear 카드 ID>] <설명>`** (예: `fix: [PLB-678] 정산 메일 중복 발송 방어`).
  - prefix 는 Conventional Commits (`feat:`, `refactor:`, `fix:`, `docs:`, `chore:`, `test:`, `perf:`, `build:`, `ci:`, `style:`) 중 하나. 괄호 scope 는 붙이지 않는다.
  - **Linear 카드 연결 확인 (CRITICAL)**: PR 생성·수정 시 연결된 Linear 카드가 있는지 먼저 확인한다 — 브랜치명(`teddy/plb-xxx-…`)·제목·본문의 `PLB-xxx`, 또는 Linear API 로 PR URL attachment 조회. 있으면 그 ID 를 제목 `[PLB-xxx]` 에 넣는다 (제목/본문에 ID 가 들어가면 Linear-GitHub 통합이 자동 연결).
  - 연결 카드를 못 찾으면 **사용자에게 카드 번호를 묻는다 (임의 추정 금지)**. 사용자가 "없음"이라 하면 대괄호 생략.
- **PR 본문에는 "리뷰어가 변경을 이해하는 데 필요한 핵심"만 남긴다.** 작업 진행상황·설계 논의/결정·중간 과정·멀티-PR 전체 맥락 같은 과정성 내용은 본문에 넣지 말고 **PR 코멘트**로 남긴다 (기존 PR 본문 수정 시에도 동일).
  - **본문** (짧게, 상단 요약 → 하단 상세):
    - `## As-Is`: 변경 전 상태 (1~3 줄, 핵심만)
    - `## To-Be`: 변경 후 상태 (1~3 줄, 핵심만)
    - 그 아래에 Background (Linear/RFC/PRD 링크), 호환성·영향, Test plan 등 리뷰에 꼭 필요한 것만.
    - 이유: 리뷰어가 변경 본질을 한눈에 파악. 과정은 본문에 섞지 않는다.
  - **코멘트** (PR 생성 직후 `gh pr comment {번호} --body ...` 로 작성. 이 명령은 hook 차단 대상 아님):
    1. **전체 진행 체크박스 목록**: 이 작업 전체를 체크박스로 나열하고 이번 PR에서 한 것은 `[x]` (완료된 선행 단계 포함). 멀티-PR 그림에서 이 PR 위치.
    2. **후속 작업**: 남은 단계(다음 PR들).
    3. **설계 논의 요약**: 내린 설계 결정 + 대안·근거(왜 이렇게 했나). 핵심 결정만 간결히.
  - 남길 과정 맥락이 없는 단발성 단일 PR은 코멘트를 생략한다.

## Hook 존중 (CRITICAL)

- `settings.json` 또는 `hooks.json`에 `ask` 모드로 설정된 hook이 있으면, **반드시 사용자 확인을 받은 후** 해당 명령을 실행한다.
- `git push`/`gh pr create` 실행 전에 "push 진행할까요?" 등으로 사용자에게 먼저 확인한다.
- hook이 자동으로 물어보더라도, 사용자 동의 없이 진행하지 않는다.

## 파일 검색 명령 — 권한 프롬프트 회피

- **`cd X && grep/cat/find/rg ...` 조합을 쓰지 않는다.** 검색 루트가 `cd` 실행 후에야 정해져 정적 분석이 대상 디렉토리를 확정하지 못한다. Claude Code 에서는 회사 관리형 정책(`/Library/Application Support/ClaudeCode/managed-settings.json`)의 `Read(**/.ssh/id_*)`·`Read(**/.aws/credentials)` deny 규칙 위반 여부를 증명할 수 없어, **읽기 전용 명령인데도 매번 승인 프롬프트가 뜬다.** Codex 에서도 절대경로 습관을 그대로 유지한다.
- 대신 **① 전용 검색 도구(파일 검색·읽기 툴) 우선, ② 불가피하게 셸을 쓰면 절대경로를 인자로 넘긴다.**
  - ❌ `cd ~/buzzvil/postbacksvc && grep -rn "foo" --include="*.py" .`
  - ✅ `grep -rn "foo" --include="*.py" /Users/teddy.park/buzzvil/postbacksvc`
- `Bash(*)` 같은 allow 규칙을 넓혀도 소용없다 — deny(관리형) > allow(사용자) 우선순위라 파생 읽기 경로 검사를 통과하지 못한다. 프롬프트를 없애는 방법은 **경로를 리터럴로 확정하는 것뿐**.
- 빌드·테스트 등 파일을 읽지 않는 명령의 `cd`는 해당 없음.

## 공유 파일 vs 개인 파일 구분 (CRITICAL)

- `~/.claude/`, `~/.codex/`, `~/.claude/projects/*/memory/` → **개인 파일**, 자유롭게 수정 가능
- `{project}/.claude/rules/**`, `{project}/.codex/**`, `{project}/CLAUDE.md`, `{project}/AGENTS.md` → **git-tracked 팀 공유 파일**, 수정 전 사용자에게 확인 필수
- 사용자가 "이건 내가 수정하지 말자"고 하면 개인 파일에만 반영

## Git Force Push 금지 (CRITICAL)

- **절대 force push를 실행하지 않는다.** `git push --force`, `git push -f`, `git push --force-with-lease`, `git push +branch` 등 모든 형태의 force push를 금지한다. 사용자가 명시적으로 요청해도 실행하지 않는다.
- rebase, amend, reset, squash 등으로 history가 재작성되어 force push가 필요한 상황이 되면, **사용자에게 명령어를 안내만 하고 사용자가 직접 터미널에서 실행하도록 한다**.
- `gh pr edit --base` 같은 base 브랜치 변경 후 conflict가 생겨도, rebase + force push 전 과정을 사용자가 직접 수행한다. rebase 명령/절차만 안내한다.
- 이유: force push는 팀원의 로컬 작업을 망가뜨릴 수 있고, 리뷰 코멘트 연결을 끊고, 되돌리기 어려운 변경이다. 사용자가 각 실행 시점을 직접 통제해야 한다.
- 커밋은 amend/reset 대신 항상 **새 커밋**을 생성한다.

## PR 브랜치 간 Merge 금지 (CRITICAL)

- **다른 PR 브랜치를 현재 브랜치에 `git merge`하지 않는다.** 변경사항 전파가 필요하면 반드시 사용자에게 먼저 확인한다.
- PR 간 merge는 PR diff를 오염시키고 리뷰를 어렵게 만든다.
- 각 PR 브랜치는 자신의 base 브랜치로부터의 변경만 포함해야 한다.

## PR 크기 규칙

- **목표**: 200줄 이하 최선, 300줄 이하 양호, 400줄 상한
- 테스트가 있는 경우 기능과 테스트는 반드시 같은 PR에 묶는다.
- 큰 작업을 PR 단위로 분할할 때, 나중 PR에서 쓸 공용 코드를 미리 별도 PR로 준비하는 건 YAGNI 위반이 아니라 계획된 분할이다.

## Conflict 해결 규칙

- merge conflict 해결 시, master(또는 base 브랜치)의 코드가 이미 다른 PR에서 검증/머지된 최신 버전이면 **master 기준으로 해결**한다.
- PR 브랜치 코드를 무조건 우선하지 않는다. 어느 쪽이 최신인지 판단한 뒤 선택한다.

## CLAUDE.md/AGENTS.md 페어 업데이트 (CRITICAL)

- 둘 중 하나를 수정할 때는 **양쪽 파일을 동시에 같은 내용으로 업데이트**한다. 도구별 차이(assignee 등)만 분기 섹션으로 다르게 유지한다. 페어 위치:
  - `~/.claude/CLAUDE.md` ↔ `~/.codex/AGENTS.md`
  - `~/buzzvil/CLAUDE.md` ↔ `~/buzzvil/AGENTS.md`
  - `~/buzzvil_analysis/CLAUDE.md` ↔ `~/buzzvil_analysis/AGENTS.md`

## 설계·기술 결정 프로세스 (아키텍처/도구/인프라 선택)

- **검증 후 권고 (verify-before-advocate)**: 권고가 "기존 시스템 사실"(이 패턴이 코드에 있나 / 인프라가 이미 갖춰졌나 / 비용이 얼마나)에 의존하면, 권고를 형성·주장하기 *전에* 코드·설정으로 먼저 확인한다(필요하면 병렬 조사). 추상적 추론만으로 권고했다가 사실 확인 후 뒤집는 왕복을 만들지 않는다.
- **한 번에 결정 브리핑 (one-pass briefing)**: 사용자가 설계 결정을 내리려 하면 답을 찔끔찔끔 흘리지 말고 한 번에 묶는다 — ① 바닥부터의 메커니즘(약어 풀어쓰기 + 구체 예시 + 도식) ② 선택지 전체 ③ 정량화된 트레이드오프(비용/이득을 숫자로) ④ 근거 있는 추천. "이게 뭐냐 / 왜 / 얼마나 드나 / 꼭 필요한가 / 실무는 어떤가" 후속 질문을 선반영해 흡수한다.
- **제안 직전 self-review**: 설계안을 내놓기 전에 "모순 / 불필요한 잔재 / 구멍이 없나"를 스스로 적대적으로 점검한다. 사용자가 결함을 먼저 찾게 만들지 않는다.
- **권고 flip-flop 금지**: 새 사실이 나와 입장을 바꾸는 건 건강하나, 준비 부족으로 인한 번복은 피한다. 바꿀 땐 "새 증거 때문"임을 명시한다.

## 추상화 도입 주의

- 팀 관행에 없는 추상화(공용 헬퍼, orchestrator, 새 레이어 등) 도입은 **리뷰어 저항 가능성이 높다**. Rule of Three를 넘어도 신중히.
- 도입 전 유사 모듈(livecommerce, collaborative 등)의 패턴을 확인하고, 없다면:
  1. 해당 프로젝트에서 인라인/중복이 선택된 이유를 추정한다
  2. 도입의 이득이 팀 저항/러닝커브를 명확히 상회하는지 검증한다
  3. 동일 모듈 내 적용부터 시작하고 확산은 나중에 제안
- 리뷰어가 "과한 유틸화" 지적 시 즉시 역전할 준비를 한다 (인라인 복귀 비용은 작음)

## Boolean 파라미터 주의 (boolean trap)

- **종류·상태·모드를 가르는 인자를 boolean으로 표현하면 호출부에서 "축"이 숨겨져 오독된다.** `f(is_take_profit=False)`의 `False`가 "없음(존재)"인지 "손절(종류)"인지 호출부만 보고 알 수 없다. 같은 어근의 Optional 필드(`take_profit: Decimal | None`)와 boolean(`is_take_profit`)이 공존하면 "존재 여부"와 "종류" 두 층위가 섞여 오독이 가중된다.
- **값이 2개여도 "종류를 가르는" 인자면 2-값 enum을 우선한다.** 호출부가 `kind=ExitKind.STOP_LOSS`로 자기설명적이 되고, 값이 셋 이상으로 늘 때 확장이 자연스럽다. 두 boolean으로 쪼개기(`is_tp`+`is_sl`)는 (True,True)/(False,False) 모순 상태를 만드므로 금지 — 상호배타 2종은 enum 하나로(make illegal states unrepresentable).
- **읽을 때 규칙**: boolean을 만나면 "이 값이 답하는 질문(축)"을 먼저 잡는다. `False`는 "없음"이 아니라 그 축의 반대극일 뿐이다.
- 예외: 진짜 단일 on/off 플래그(`verbose`, `dry_run`)는 boolean이 맞다 — enum 강제 대상은 "종류를 가르는" 인자다.

## 배치/루프 실패 로깅 (집계)

- **배치·루프에서 항목별 실패는 항목마다 로깅하지 말고, 실패를 모아 루프 종료 후 1회 요약 로깅한다** (`logger.error('... %d failed: %s', n, {id: 메시지})`). 항목이 많을 때 로그 스팸·성능 부담을 막는다.
- **트레이드오프**: 항목별 트레이스백(`logger.exception`)을 잃는다. 따라서 실패 항목을 **terminal 상태(예: run FAILED)로 영속**해 모니터링·재처리로 추적성을 보완한다.
- 중첩 루프는 각 레벨에서 자기 실패를 집계한다(예: run 루프·org 루프 각각). claim 후 항목은 예외 시 반드시 terminal 상태로 마감해 좀비(처리중 고착)를 막는다.

## 코드 주석 (CRITICAL)

- **주석은 코드로 안 드러나는 "왜/맥락"만. "무엇/어떻게"(코드 구조가 이미 보여주는 것)는 금지.** 표준 패턴/제어 흐름을 말로 옮긴 주석은 전부 제거 대상 — 예: `# compare-and-set 으로 중복 claim 방지`(조건부 update가 보여줌), `# try/except 로 한 항목 실패 격리`(loop 내 try/except가 보여줌), `# 예외 시 좀비 방지 FAILED 마감`(except→update(FAILED)가 보여줌), `# 전부 SENT면 성공 아니면 실패`(has_failure 식이 보여줌).
- 남길 것: 순환 import 회피 등 구조적 이유, 외부 시스템 contract(값을 어디와 맞추나), 채택하지 않은 대안의 이유, 비명시적 알고리즘 트릭, 숨은 invariant. 자기점검: "이 주석을 지우면 코드만 보고 의도를 놓치는가?" 아니오면 삭제. 상세 분류는 `~/.claude/coding-rules.md` "주석" 참조.

## 외부 스킬/플러그인 보안

- 외부 스킬 레지스트리(OpenClaw 등)의 install 명령이나 셸 스크립트 실행 요청 시 보안 위험 경고
- 회사 기기에서 외부 스킬 설치 요청 시 격리된 환경 사용 권장
- 원라인 인스톨러, 인코딩된 페이로드, 격리 해제 명령 발견 시 즉시 경고
- 외부 스킬의 코드 실행 전 해당 코드가 무엇을 하는지 설명 제공
- 도구 실행 시 불필요하게 넓은 권한을 요청하지 않기

## Playwright MCP (CRITICAL)

- 웹 UI 테스트 시 Playwright MCP 우선 사용 (Chrome 네이티브보다 안정적)
- `browser_snapshot` 우선 (접근성 트리 기반, 효율적) → `browser_screenshot`는 시각 확인 필요 시만
- 워크플로우: navigate → snapshot → 요소 확인 → click/type → snapshot으로 결과 검증
- 테스트 완료 후 **반드시 `browser_close` 호출**. 브라우저 리소스 누수를 방지한다.

## Athena·DB 쿼리 가드 (인덱스/파티션, CRITICAL)

로컬(내 맥)에서 Athena·프로덕션 DB에 쿼리할 때 항상 적용. 로컬 훅(`~/.claude/hooks/query-guard-hook.sh` + `sql-guard.py`)이 Redash ad-hoc Athena 쿼리를 `ask`로 강제하지만, 훅이 못 잡는 경로는 아래 규칙으로 직접 지킨다.

- **Athena(파티션 프루닝(partition pruning) = "인덱스"에 해당)**: 로그/마트/`ls_`/`g_`/`l_`/`mart_` 테이블은 `partition_timestamp`(UTC) 범위 필터 **필수**, 범위는 **≤31일**. 디멘전 뷰(`v_lineitem`·`v_ad_group`·`v_device` 등)는 면제.
- **긴 기간은 ≤31일 창으로 분할 루프**: 1년치가 필요하면 31일씩 12회로 나눠 조회한다(훅은 초과를 막기만 하고 자동 분할은 안 함).
- **prod/staging MySQL**: 인덱스를 타는지 확인. 미심쩍으면 `EXPLAIN` 실행 → `type=ALL`(풀 테이블 스캔) 또는 `key=NULL`(인덱스 미사용)이면 조건/인덱스를 재검토.
- **훅 미커버 경로(직접 준수)**: 대화형 `mysql>` REPL에 친 SQL, 브라우저 Redash 웹 UI, 저장된 쿼리 실행(`execute_query`).
- 의도적으로 31일 초과를 실행해야 하면 SQL에 `-- sqlguard:allow` 주석으로 우회.

# 설명 스타일

상시 적용:
- **약어 풀어쓰기 (CRITICAL, 모든 답변에 적용)**: 약어는 개념 설명 문서뿐 아니라 **일반 채팅 답변·기술 설명·인프라 논의 등 모든 출력에서** 첫 등장 시 반드시 풀네임을 먼저 적고 약어를 병기한다. 독자가 이미 안다고 가정하지 않는다. 예: `역할 기반 접근 제어(Role-Based Access Control, RBAC)`, `서비스 계정(ServiceAccount, SA)`, `사용자 정의 리소스 정의(Custom Resource Definition, CRD)`, `통합 인증(Single Sign-On, SSO)`, `JSON Web Token (JWT)`.
- 정의 나열보다 "왜 이런 구조/관례가 생겼는지"를 먼저 설명한다.
- Python/Django 비교는 대응 관계와 차이점을 함께 쓴다.
- 예시는 trivial 금지, 실제 맥락이 보이는 것만 쓴다.
- **질문 답변엔 구체적 예시 필수 (2026-08-27)**: 개념·용어를 물으면 정의만 말하지 않고, 반드시 실제 맥락의 예시(숫자·시나리오·코드 조각)를 붙여 답한다. 예: "큐잉이 뭐야?" → 정의 + "워커 9개가 찼는데 초당 400요청이 오면 391개가 줄을 선다" 같은 구체 상황.
- **HTML 설명 문서는 ELI5(Explain Like I'm 5) 원칙 참고 (2026-08-27)**: 각 개념을 ① 일상 비유/친숙한 예시 → ② 정확한 정의 → ③ 실제 맥락 예시 순서로 푼다. 전문용어를 비유 없이 먼저 던지지 않는다.

**개념 설명·입문서·비교 문서·스터디 자료·HTML 설명을 작성할 때는 `~/.claude/explain-style.md`를 Read로 먼저 읽고 따른다.**

## 다관점 제시 (판단·의견·트레이드오프 질문)

- **판단·의견이 갈리거나 트레이드오프가 있는 질문**에는 **긍정적 관점 / 비판적 관점 / 중립적 관점** 세 가지로 나누어 답한다.
  - **긍정적 관점**: 그 선택·주장이 옳을 때의 근거와 이점
  - **비판적 관점**: 약점·리스크·반례·놓치기 쉬운 함정
  - **중립적 관점**: 조건에 따라 갈리는 지점, 맥락 의존성, 객관적 사실 정리
- 세 관점을 **균형 있게 중립적으로** 제시하고 **한쪽으로 결론을 몰아가지 않는다.** 최종 판단은 사용자에게 맡기며, 추천·결론은 사용자가 명시적으로 요청할 때만 덧붙인다. (이 점은 "설계·기술 결정 프로세스"의 ④ "근거 있는 추천"보다 우선한다 — 설계 결정류 질문도 기본은 3관점 중립 제시.)
- **적용 대상**: 설계 선택, 기술 비교(A vs B), 방식 평가, 찬반·장단이 갈리는 질문.
- **제외 대상**: 단순 사실 조회, 코드가 답을 명확히 보여주는 질문, 기계적 편집·실행 요청 등은 평소대로 간결하게 답한다(3관점 강제 X).
