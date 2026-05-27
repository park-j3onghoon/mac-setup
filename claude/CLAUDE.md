# Extended Thinking

모든 세션에서 **ultrathink** 수준의 확장 사고를 사용한다.
- Claude Code 사용 시: ultrathink 활성화 (Option+T로 토글 가능).
- Codex 사용 시: `~/.codex/config.toml`의 `model_reasoning_effort = "xhigh"` 설정으로 동등한 효과.
- 모든 질문과 작업에 대해 최대한 깊이 있고 체계적으로 사고한다.
- 복잡한 문제는 단계별로 분해하여 분석한다.
- 코드 분석 시 전체 흐름을 추적하고 엣지 케이스를 고려한다.

# 개인 글로벌 설정

- **코드 작성/수정 전에 `~/.claude/coding-rules.md`를 읽고 적용한다.** 서브 파일(`coding-rules-*.md`) 참조가 있으면 현재 작업 언어/도메인에 해당하는 것도 읽는다.
- **계획을 세운 후 구현 전에 반드시 `/plan-review` 스킬을 실행한다.** Plan Mode 여부와 무관하게 적용.
- **PR 생성 전, 그리고 기존 PR에 push 전에** 반드시 `/review` 스킬을 **먼저** 실행한다. `/review` 완료 후 `/pr-size-check`를 실행한다. **이 순서를 절대 건너뛰거나 뒤바꾸지 않는다.**
- 보안 관련 코드를 변경할 때 (인증, 권한, 시크릿 처리, API 엔드포인트 추가, 결제/민감 데이터) `/cso` 스킬을 `--diff` 모드로 실행한다.
- 세션 시작 시 코드 구현/수정 작업이 예상되면, 작업 대상 디렉토리를 사용자에게 확인한 후 `/guard` 스킬을 실행하여 해당 디렉토리 외부 편집을 제한한다. 조사/분석만 하는 세션에서는 guard를 걸지 않는다.
- 개발 착수 시 작업 분할이 안 된 상태에서 바로 구현하려 하면, `/dev-plan` 스킬을 먼저 실행하여 작업을 PR 단위로 분할하고 일정을 산정한다. 단일 파일 수준의 작은 변경은 예외.
- **규모 있는 작업(구현/리팩토링/조사 등 여러 단계에 걸쳐 플랜·컨텍스트가 쌓인 작업) 마무리 시**, 사용자 요청이 없어도 다음 세션 시작용 프롬프트를 선제적으로 정리해서 제시한다. 포함 항목: ① 작업 대상 repo/디렉토리 ② 현재 상태(완료/대기) ③ 계획·분석 파일 경로 ④ 남은 단계 ⑤ 다음 액션 힌트. 형식은 사용자가 복사-붙여넣기 가능한 코드 블록으로. 단순 1회성 질문·답변에는 적용하지 않는다.

## Plan 파일 저장 경로 (CRITICAL)

- Plan·분석·change-summary 등 **작업 설계 문서는 repo 내부 `docs/`가 아닌 `~/plans/{repo이름}/{작업명}/` 하위**에 저장한다.
  - 예: `~/plans/adserver/ads-168-create-view-connect/plan.md`
  - 예: `~/plans/{repo}/{task}/change-summary.md`
- 이유: plan 문서가 PR diff를 부풀려 PR 크기 규칙(400줄 상한)을 초과시키고, 리뷰어가 코드와 같이 리뷰해야 하는 부담이 생긴다. 로컬에서 참고용으로만 유지.
- Plan Mode의 `/Users/teddy.park/.claude/plans/*.md`는 스킬 기본 경로이므로 그대로 사용. `~/plans/{repo}/{task}/plan.md`는 저장(저장용 사본)·공유용 위치.
- `docs/` 아래에 이미 plan을 만들어 커밋한 경우: 파일을 `~/plans/{repo}/{task}/`로 옮기고, 해당 커밋은 soft reset 후 재작성하여 diff에서 제외한다 (push 전에만 가능; push 후에는 force push 필요하므로 사용자에게 안내).

## 브랜치 명명 규칙 (CRITICAL)

- 새 브랜치 생성 시 **반드시 `teddy/` prefix로 시작**한다.
  - 예: `teddy/plb-530-recalculate-payout`, `teddy/fix-billing-cron`
- 기존 브랜치를 checkout하는 경우는 예외.

## PR 생성 규칙 (CRITICAL)

- PR 생성 시 **assignee 는 GitHub username `park-j3onghoon`** 으로 지정한다 (Claude Code / Codex 공통).
  - 주의: displayName 은 `teddy.park` 이지만 GitHub username (gh CLI `--assignee`) 은 `park-j3onghoon`. `teddy.park` 시도 시 "user not found" 에러 발생.
- **reviewer는 추가하지 않는다.** 사용자가 직접 수동으로 지정한다.
- 커밋 메시지, PR 제목/본문은 한글로 작성한다.
- **PR 제목은 Conventional Commits prefix** 로 시작한다 (`feat:`, `refactor:`, `fix:`, `docs:`, `chore:`, `test:`, `perf:`, `build:`, `ci:`, `style:`). 괄호 scope 는 붙이지 않는다.
- **PR 본문 구조**: 상단에 As-Is / To-Be 간단 요약 → 하단에 추가 설명.
  - `## As-Is`: 변경 전 상태 (1~3 줄, 핵심만)
  - `## To-Be`: 변경 후 상태 (1~3 줄, 핵심만)
  - 그 아래에 Background (Linear/RFC/PRD 링크), 디자인 결정, 호환성, 후속 작업, Test plan 등 상세 작성
  - 이유: 리뷰어가 변경 본질을 한눈에 파악 가능. 상세는 필요한 사람만 읽음.

## Hook 존중 (CRITICAL)

- `settings.json` 또는 `hooks.json`에 `ask` 모드로 설정된 hook이 있으면, **반드시 사용자 확인을 받은 후** 해당 명령을 실행한다.
- `git push`/`gh pr create` 실행 전에 "push 진행할까요?" 등으로 사용자에게 먼저 확인한다.
- hook이 자동으로 물어보더라도, 사용자 동의 없이 진행하지 않는다.

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

## 자가 개선 (Self-improvement)

- 각 스킬(dev-plan, plan-review, review)은 완료 시 자가 개선 단계를 실행한다.
- **개인 참조 문서**(`~/.claude/skills/{스킬}/ref-*.md`, `~/.codex/skills/{스킬}/references/*.md`, `~/.claude/coding-rules.md`, `~/.claude/projects/*/memory/`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`)를 자동 업데이트한다.
- **CLAUDE.md/AGENTS.md 페어 업데이트 (CRITICAL)**: 둘 중 하나를 수정할 때는 **양쪽 파일을 동시에 같은 내용으로 업데이트**한다. 도구별 차이(assignee 등)만 분기 섹션으로 다르게 유지한다. 페어 위치:
  - `~/.claude/CLAUDE.md` ↔ `~/.codex/AGENTS.md`
  - `~/buzzvil/CLAUDE.md` ↔ `~/buzzvil/AGENTS.md`
  - `~/buzzvil_analysis/CLAUDE.md` ↔ `~/buzzvil_analysis/AGENTS.md`
- 2회+ 반복된 패턴, 사용자 명시 교정, 참조 문서에 없는 새 체크리스트만 반영.
- 일시적 판단, 이미 있는 내용, "이번만" 예외는 스킵.

## 코드 스타일 규칙

- `__init__.py`에 불필요한 모듈 설명 주석(docstring)을 넣지 않는다. 빈 파일로 둔다.
- `**kwargs` spread와 명시적 파라미터를 함께 쓸 때, 명시적 파라미터를 `**` 뒤에 배치하여 override를 보장한다.
- 인라인 가능하면 인라인을 선호한다. 단, 100~110자를 초과하면 변수로 분리한다.
- 함수 내부 import 금지, 파일 최상단에 배치한다.

## 주석 규칙

- 기본은 주석 없음. 식별자·시그니처로 파악되는 것은 적지 않는다. "무엇"이 아니라 "왜"만 적는다.
- 남길 맥락:
  - 외부 표준 참조 (AIP-XXX, RFC NNNN, 회사 RFC 링크)
  - 보안 근거 (enumeration 방지, capability 토큰, XSS 벡터 차단 등)
  - 아키텍처 결정 근거·검토 후 채택하지 않은 대안
  - 비명시적 알고리즘 트릭 (limit+1 hasNext, microsecond precision cursor, base64url 형식 등)
  - 혼동되는 코드/타입 간 disambiguation (vs 비교)
  - 숨어 있는 제약·invariant (DB 컬럼 타입 정합, 외부 API 응답 nullability 가정 등)
- 지워야 할 주석:
  - 시그니처로 자명한 함수/클래스 동작 설명
  - 데이터 클래스의 "X용 VO/DTO" 라벨
  - 변경 이력·과거 구현 ("이전에는 Map이었으나...") — git log·PR 본문이 담당
  - 호출자 정보 ("X 화면이 이걸 쓴다") — 코드 변경에 따라 거짓이 된다
  - 한 줄 식별자를 풀어 쓴 설명 (`"X 토큰을 생성한다"` / `fun generate(): String`)
- 지웠을 때 미래 독자가 헷갈리면 남기고, 그렇지 않으면 지운다.

## 테스트 규칙

- git push 전에 반드시 관련 테스트를 실행한다.
- 테스트 메서드명은 영어, docstring만 한글.
- 프레임워크 빌트인은 테스트하지 않고, 커스텀 로직만 테스트한다.
- 데이터 객체 단독 테스트 불필요, 스냅샷 테스트 금지, 무효 케이스 전수 검증 불필요.
- update/delete 미존재 시 None 대신 도메인 예외, find는 None OK.
- 중복 테스트 통합, 헬퍼는 conftest에 집중.
- **개인 프로젝트(linkcart 등 회사 외부 repo)는 MC/DC 커버리지(Modified Condition/Decision Coverage)를 만족시킨다.** 복합 조건 `A && (B || C)` 같은 식에서 각 sub-condition이 다른 condition을 고정한 채로 단독으로 decision을 뒤집은 적이 있어야 한다. branch coverage 100%로 만족하지 못한다. n+1개 케이스로 보통 충분 (n=condition 수). JaCoCo 등은 native 지원이 없으므로 테스트 작성 시 입력 조합표를 직접 설계해서 만족 여부를 확인한다. 회사 프로젝트(buzzvil 등)에는 적용하지 않는다.

## 코드 변경 원칙

- 코드 변경 제안 전 다른 모듈의 기존 패턴을 먼저 확인한다.
- 파일 이동/import 변경 후 반드시 빌드 검증한다.
- 리뷰 에이전트 제안을 맹목적으로 적용하지 않고, 기존 패턴을 확인한다.
- 파일 있다/없다/삭제됐다 단정 전 실제로 확인한다.

## 추상화 도입 주의

- 팀 관행에 없는 추상화(공용 헬퍼, orchestrator, 새 레이어 등) 도입은 **리뷰어 저항 가능성이 높다**. Rule of Three를 넘어도 신중히.
- 도입 전 유사 모듈(livecommerce, collaborative 등)의 패턴을 확인하고, 없다면:
  1. 해당 프로젝트에서 인라인/중복이 선택된 이유를 추정한다
  2. 도입의 이득이 팀 저항/러닝커브를 명확히 상회하는지 검증한다
  3. 동일 모듈 내 적용부터 시작하고 확산은 나중에 제안
- 리뷰어가 "과한 유틸화" 지적 시 즉시 역전할 준비를 한다 (인라인 복귀 비용은 작음)

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

# 사용자 프로필 / 설명 스타일

## 설명/학습 자료 작성 선호

- 사용자가 개념 설명, 입문서, 비교 문서, 스터디 자료를 요청하면 **정의만 나열하지 말고 "왜 이런 구조/관례가 생겼는지"까지 먼저 설명**한다.
- 표준/관례/프레임워크 제약/팀 커스텀을 구분해서 쓴다.
  예: `src/main/kotlin`은 "기술적으로 변경 가능하지만 표준 구조", 역도메인 패키지는 "충돌 방지 관례"처럼 설명
- Python/Django 비교를 할 때는 **대충 비슷하다**로 끝내지 말고, 정확히 어디까지 같고 어디서 어긋나는지 같이 쓴다.
  예: Django `View`와 Spring `Controller`, Python `ABC`/`Protocol`과 Kotlin `interface`
- 초보자 문서에는 **의미 있는 예시만 사용**한다.
  예시가 왜 필요한지 드러나지 않는 trivial example은 피하고, 옵션 필드/외부 응답/캐시/DI 선택처럼 실제 맥락이 보이는 예시를 사용
- 개념 설명 시 아래 질문들을 선반영한다.
  - 왜 나뉘어 있나?
  - 항상 같이 쓰는가, 아닌 경우는?
  - 기술적으로 가능한 것과 실무 관례는 어떻게 다른가?
  - 한 개만 되는가, 여러 방식이 가능한가?
  - 내가 원하는 구현/동작을 프레임워크가 정확히 어떻게 고르는가?
- `init` vs `constructor`, `val` vs 가변 컬렉션, `@RestController` vs `@RequestMapping`, `@Primary`/`@Qualifier`/`List<T>`처럼 **혼동하기 쉬운 쌍/세트는 표와 코드로 같이 설명**한다.
- 어노테이션/설정/패턴을 언급하면 가능하면 **짧은 예제 코드도 함께 넣는다**.
  예: `@JsonValue`, `@Bean`, `@Configuration`, `@Entity`, `@field:NotBlank`
- 시각화 가능한 개념은 적극적으로 도식화한다.
  예: MVC vs MTV, 빌드 흐름, DI 연결, 레이어/의존성 방향, 요청 처리 흐름
- 보안/웹 플랫폼 개념은 **문제 발생 배경 → 막기 위해 생긴 규칙 → 그 규칙이 만든 불편 → 그 불편을 완화한 다음 규칙** 순서로 설명한다.
  예: Hotlink/외부 리소스 남용 문제, SOP가 막는 범위, SOP 때문에 합법적인 프론트-백엔드 분리가 막히는 문제, CORS가 서버 명시 허용으로 이를 완화하는 방식
- 설명 중 새 개념이 나오면 그 개념도 같은 방식으로 다시 푼다.
  즉, A를 설명하다가 B가 나오면 `B의 풀네임 → B 이전 문제 → B가 막는 것 → B의 한계 → 다음 개념` 순서로 재귀적으로 이어간다.
- 약어는 첫 등장 시 항상 풀네임을 먼저 적고, 그 뒤에 약어를 병기한다.
  예: `Same-Origin Policy (SOP)`, `Cross-Site Request Forgery (CSRF)`, `JSON Web Token (JWT)`
- "대부분 그렇다"와 "항상 그렇다"를 구분한다.
  예: `@RestController`와 `@RequestMapping`은 자주 같이 쓰지만 항상 그런 것은 아님
- 설명의 목표는 사용자가 추가 질문을 덜 하게 만드는 것이다.
  따라서 처음부터 **예상되는 후속 질문까지 흡수한 설명**을 우선 제공한다.

## 이 사용자의 후속 질문 경향

- 사용자는 설명을 들으면 곧바로 `왜 그렇게 나뉘는가`, `왜 이런 관례가 생겼는가`, `불필요하게 복잡한 것 아닌가`를 묻는 경향이 있다.
- 사용자는 `이게 정말 필수인가`, `기술적으로는 다른 방식도 되는가`, `실무에서는 왜 보통 이렇게 하는가`를 구분해서 알고 싶어 한다.
- 사용자는 비유가 부정확하면 바로 짚는다.
  따라서 Python/Django 비교는 대응 관계와 차이점을 함께 써야 한다.
- 사용자는 `항상 같이 쓰는가`, `예외 케이스가 있는가`, `한 줄만 가능한가`, `여러 줄/여러 방식도 가능한가`처럼 경계 조건을 자주 확인한다.
- 사용자는 프레임워크가 내부적으로 `정확히 어떻게 동작하는가`를 궁금해한다.
  예: DI에서 구현체 선택, Wrapper가 Gradle을 어떻게 가져오는지, Tomcat과 Spring의 역할 분리
- 사용자는 `코드 예시가 없는 설명`을 불충분하게 느낀다.
  개념 설명 뒤에는 가능한 한 바로 짧은 예시 코드를 붙인다.
- 사용자는 `시각화 가능한 개념`은 도식으로 보는 편이 빠르다.
  MVC/MTV, 빌드 흐름, DI 연결, 레이어/의존성 방향, 요청 흐름은 우선적으로 시각화한다.
- 사용자는 보안/브라우저 규칙도 "지금 정의"보다 "왜 그런 제약이 생겼는지"를 알고 싶어 한다.
  SOP, CORS, 쿠키, 세션, CSRF, 핫링크, 캐시 같은 개념은 배경 문제와 트레이드오프를 같이 설명하는 편이 맞다.
- 사용자는 새 개념이 설명 도중 등장하면 그 개념도 바로 이어서 풀어주길 기대한다.
  따라서 "이건 나중에 설명"으로 끊기기보다, 짧게라도 재귀적으로 연결해서 설명하는 편이 좋다.
- 사용자는 `의미 없는 예시`를 싫어한다.
  예시는 nullable 외부 응답, 옵션 필드, 구현체 여러 개, 캐시 TTL, 파일 기반 DB처럼 실제 질문이 생길 만한 맥락을 써야 한다.
- 사용자는 용어 자체도 자주 확인한다.
  약어 풀네임, 발음, 정석 표현인지 대체 표현인지도 선제적으로 적는 편이 좋다.
- 사용자는 패턴 간 관계를 자주 재정의한다.
  예: 레이어드 vs 클린 vs 헥사고날 vs DDD.
  따라서 패턴을 설명할 때는 `같은 점 / 다른 점 / 함께 쓰일 때 각자가 담당하는 역할`까지 같이 정리한다.
- 사용자는 모바일/데스크탑 문서가 다르면 빠진 내용이 없는지 확인한다.
  문서를 분할할 때는 내용 동일 여부를 명시한다.

## 문서 분할 규칙

- 같은 문서를 데스크탑용 전체판과 모바일용 분할본으로 나눌 때, 사용자가 요약본을 명시적으로 원하지 않는 한 **내용은 동일하게 유지**한다.
- 분할본은 보기 방식만 다르고 정보는 빠지지 않게 유지한다.
- 입구 페이지나 목차에는 전체판/분할본의 관계를 명확히 적는다.
