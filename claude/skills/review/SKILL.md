---
name: review
version: 4.1.0
description: PR 랜딩 전 코드 리뷰. 3개 서브에이전트를 병렬 실행하고 선택적으로 Codex CLI(이종 LLM)를 추가 투입해 빠짐없이 검증한다. "리뷰해줘", "PR 리뷰", "코드 리뷰" 등으로 트리거.
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
---

# /review — Pre-Landing PR 리뷰 (v4.1)

3개 서브에이전트를 병렬 실행하여 빠짐없이 검증한다.
사용자 선택 시 Codex CLI(GPT 계열)를 이종 LLM 관점의 추가 리뷰어로 투입해 Opus가 놓칠 수 있는 이슈를 보완한다.

## Step 0: 리뷰 대상 레포 확인

인자로 GitHub PR URL이 전달된 경우 (`https://github.com/{owner}/{repo}/pull/{number}`):
1. URL에서 owner/repo와 PR 번호를 파싱한다.
2. `~/buzzvil/{repo}` 등 로컬 클론 경로를 찾아 `cd`한다. 없으면 사용자에게 경로를 묻는다.
3. PR 브랜치를 checkout한다: `git fetch origin {branch} && git checkout {branch}`

로컬 브랜치에서 직접 실행하는 경우 이 단계를 건너뛴다.

## Step 1: Diff 수집

```bash
BASE=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo main)
BRANCH=$(git branch --show-current)
git fetch origin $BASE --quiet
git diff origin/$BASE --stat
git log origin/$BASE..HEAD --oneline
```

base branch이거나 diff 없으면: "리뷰할 변경이 없습니다." → 종료.

### 스코프 드리프트 감지

```
Scope Check: [CLEAN / DRIFT / MISSING]
의도: <요청된 작업 1줄>
실제: <diff가 실제로 하는 것 1줄>
```

## Step 2: 전체 diff 가져오기

```bash
git diff origin/$BASE
```

## Step 3: 3개 서브에이전트 병렬 실행

diff 전문을 각 서브에이전트에 전달한다. **반드시 3개를 동시에 Agent tool로 병렬 호출한다.**

각 서브에이전트 프롬프트에 아래를 포함한다:
1. diff 전문 (또는 diff가 길면 파일별 요약 + 핵심 변경부)
2. 해당 기준 파일 내용 (review-code.md / review-language.md / review-team.md)
3. "각 항목을 빠짐없이 체크하고, 해당 여부를 명시적으로 판단하라. PASS면 PASS라고 써라."
4. "발견 사항은 [CRITICAL/INFO] file:line — 설명 형식으로 출력하라."
5. "코드베이스에서 확인이 필요한 것은 Grep/Read로 직접 검증하라. 추측 금지."

### 서브에이전트 1: 코드 공통 리뷰
기준 파일: `~/.claude/skills/review/review-code.md`
역할: 보안, 정확성, 계약 일관성, 클린코드, YAGNI, 아키텍처, 에러핸들링, 관측성, 성능, 테스팅, 운영 안전성

### 서브에이전트 2: 언어별 공통 리뷰
기준 파일: `~/.claude/skills/review/review-language.md`
역할: diff에 포함된 언어(Python/Go/Java/Frontend)의 관용구, 타입 안전성, 플랫폼 특화 이슈

### 서브에이전트 3: 팀 리뷰어 시뮬레이션
기준 파일: `~/.claude/skills/review/review-team.md`
역할: 팀 리뷰어(Frank, Zune, Wynn, BK, Lucas, Edan, David, Scott, Brice, Thomas, isac322, Miles)별 관점 + 언어별 리뷰어(Bale-do, dc7303, jzakka, glenn4105, KangBK0120)

## Step 3.5: Codex 추가 리뷰 (선택)

3개 서브에이전트 실행 후, 이종 LLM(GPT 계열) 관점을 추가할지 AskUserQuestion으로 1회 선택한다. Codex는 Opus/Sonnet이 놓친 엣지케이스·계약 불일치·설계 가정 오류를 잘 잡는다.

**옵션 3지선다:**
- A) 건너뛰기 — 3 서브에이전트 결과만 사용
- B) Codex 리뷰 추가 — `codex review` 실행
- C) Codex 리뷰 + Adversarial — `codex review` + `codex adversarial-review` 둘 다 실행

**선택 기준 제시 (질문에 포함):**
- 변경 200줄 미만 + 루틴 수정 → A 권장
- 변경 200줄+ 또는 도메인·애플리케이션 레이어 변경 → B 권장
- 새 추상화/레이어 도입, 마이그레이션 동반, 아키텍처 결정 → C 권장

권장 옵션 라벨에 `(Recommended)` 접미사를 붙여 제시한다.

**실행 방식 (B/C 선택 시):**
Codex 플러그인 스크립트를 Bash tool의 `run_in_background: true`로 실행해 시간 제한 없이 돌린다. 완료까지 `BashOutput`으로 polling.

```bash
CODEX_SCRIPT=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1)

# B/C 공통 — 기본 리뷰
node "$CODEX_SCRIPT" review --background

# C만 — Adversarial 리뷰 추가
node "$CODEX_SCRIPT" adversarial-review --background
```

`--background`는 Codex 플러그인의 자체 배경 모드이며, Claude Code Bash tool도 `run_in_background: true`로 띄워 두 층으로 비동기 처리한다. BashOutput으로 stdout을 수신하면서 완료 상태가 될 때까지 대기한다.

Codex stdout은 **원본 그대로 보존**하여 Step 4 결과 통합에 합친다. 요약하거나 paraphrase 하지 않는다.

## Step 4: 결과 통합

3개 서브에이전트 결과(+ 선택 시 Codex 결과)를 수집하여:

1. **중복 제거**: 같은 이슈를 여러 리뷰어(서브에이전트 또는 Codex)가 발견한 경우 하나로 합치고 "(코드+팀+codex)" 등 출처 표시
2. **심각도 정렬**: CRITICAL 먼저, INFO 다음
3. **통합 리포트 생성** — Codex가 실행된 경우 Codex 섹션을 별도 블록으로 **원본 그대로** 덧붙인다 (paraphrase 금지)

## Step 5: Fix-First 리뷰

**모든 발견 사항에 조치를 취한다.**

### 5a: 기존 코드베이스 패턴 확인 (필수)
수정을 적용하기 전에, 해당 패턴이 다른 모듈에서 어떻게 사용되는지 **Grep으로 먼저 확인**한다.
예: id 필드 패턴 변경 → `grep "Field.*default.*description.*auto"` 로 다른 엔티티 확인.
기존 패턴과 다른 방향이면 AUTO-FIX가 아닌 ASK로 분류한다.

**방어 코드 추가 주의**: 리뷰 에이전트가 제안한 방어 코드(assert, 중복 존재 체크, 수동 timestamp 세팅 등)가 기존 코드에 없는 패턴이면 AUTO-FIX가 아닌 **ASK**로 분류한다. 기존 코드가 이미 다른 메커니즘(MySQL DDL, 프레임워크 빌트인 등)으로 처리하고 있을 수 있다.

### 5b: 분류
- **AUTO-FIX**: 기계적 수정 (import 정리, 오타, 누락된 필드). 기존 패턴과 일치하는 것만.
- **ASK**: 판단 필요 (아키텍처 결정, 트레이드오프, 기존 패턴과 다른 방향)

### 5c: AUTO-FIX 적용
각 수정마다 1줄 요약: `[AUTO-FIXED] [file:line] 문제 → 조치`

### 5c: ASK 항목 일괄 질문
ASK 항목을 하나의 AskUserQuestion으로 묶어서 질문.

### 5d: 승인된 수정 적용

## Step 6: 문서 확인

diff가 변경한 기능을 설명하는 문서가 있으나 업데이트 안 됐으면:
`[INFO] 문서가 오래됐을 수 있음: [파일]이 [기능]을 설명하지만 코드가 변경됨.`

### 페어 sync 점검 (CLAUDE.md/AGENTS.md)

PR이 CLAUDE.md 또는 AGENTS.md를 변경했다면 페어 파일이 같이 변경되었는지 확인한다. 페어 위치: `~/.claude/CLAUDE.md` ↔ `~/.codex/AGENTS.md`, `~/buzzvil/CLAUDE.md` ↔ `~/buzzvil/AGENTS.md`, `~/buzzvil_analysis/CLAUDE.md` ↔ `~/buzzvil_analysis/AGENTS.md`.

```bash
diff -q ~/.claude/CLAUDE.md ~/.codex/AGENTS.md
diff -q ~/buzzvil/CLAUDE.md ~/buzzvil/AGENTS.md
diff -q ~/buzzvil_analysis/CLAUDE.md ~/buzzvil_analysis/AGENTS.md
```

도구별 분기 섹션(assignee 등) 외에 차이가 있으면 `[CRITICAL] 페어 sync 누락: {파일}` 이슈로 잡고 다른 쪽도 동일 변경을 적용한다.

## Step 7: 변경 설명 문서 생성

리뷰 완료 후, **이 PR이 왜 필요하고 어떻게 동작하는지** 설명하는 문서를 생성한다.

### 7a: 엔드유저 시나리오 → 함수 호출 체인

엔드유저(또는 외부 시스템)가 이 코드를 트리거하는 시점부터 최종 결과까지, **함수 호출을 하나하나 빠짐없이** 보여준다. 수정된 함수는 `← 수정` 표시.

```
예시:
1. 캠페인 매니저가 Dash 리포트 페이지를 연다
2. GET /api/ba/ads/{id}/reports
3. ServiceLineitemReportDetail.get()
   → get_full_lineitem_report()
     → get_lineitem_report()
       → StatsProvider.list_unit_creative()
         → statssvc gRPC ListUnitCreatives
           → views.list_unit_creative()  ← 수정
             → DjangoJobRepository.list_unit_creative()
               → _list_unit_creative_query_new2()  ← 수정: Sum(alternative_conversion) 추가
```

### 7b: 파일별 수정 이유

diff의 각 파일에 대해:
1. **상대 경로** (레포 루트 기준, 전체 표기)
2. **이 파일의 역할** 1줄
3. **왜 수정했는가**: 이 변경이 없으면 어떤 문제가 생기는지
4. **구체적 변경 내용**: 어떤 라인에서 무엇을 추가/변경했는지
5. **설계 결정**: 비자명한 결정이 있으면 설명 (default 값, nullable 등)

### 7c: 문서 저장

생성한 문서를 사용자에게 보여주고, 저장 여부를 묻는다.

## 주장 검증 규칙
- "이 패턴은 안전" → 안전을 증명하는 구체적 라인 인용
- "다른 곳에서 처리됨" → 해당 코드를 읽고 인용
- "테스트가 커버함" → 테스트 파일과 메서드 이름 지정
- "아마 처리됐을 것" 금지 — 검증하거나 미확인 표시

## 완료
```
Pre-Landing Review: N 이슈 (X critical, Y informational)
Auto-fixed: Z
User-approved fixes: W
Remaining: V

리뷰어 결과:
- 코드 공통: A건
- 언어별: B건
- 팀 리뷰어: C건
- (선택 시) Codex: D건
- (선택 시) Codex adversarial: E건
```

## Step 8: /pr-size-check + push 안내

모든 리뷰와 수정이 완료된 후:

1. `/pr-size-check` 스킬을 실행한다.
2. size check 통과 후, **push 명령어를 절대 경로 포함하여 출력**한다:

```
/review + /pr-size-check 완료. 아래 명령어로 push해주세요:

! cd {현재 작업 디렉토리 절대 경로} && git push
```

**주의**: `git push`와 `gh pr create`는 PreToolUse hook으로 차단된다. 사용자가 `!` 접두사로 직접 실행해야 한다. Claude가 직접 `git push`를 실행하지 않는다.

## Step 9: 스킬 자가 개선

리뷰 완료 후, 이번 리뷰에서 내린 결정/발견한 패턴 중 스킬 파일에 없는 내용을 반영한다.

### 9a: 신규 지식 추출
이번 리뷰에서 아래 중 새로운 것을 식별한다:
- ASK 항목에 대한 사용자의 결정
- 반복 발견된 코드 패턴/안티패턴
- 새로 적용된 리뷰 기준

### 9b: 양방향 반영 — 리뷰 스킬 + 코딩 규칙

발견한 신규 지식을 **두 곳에** 반영한다:

**① 리뷰 체크리스트** (다음 리뷰에서 더 잘 잡기 위해):
`review-code.md`, `review-language.md`, `review-team.md`를 읽어 이미 포함된 내용인지 확인.
없는 내용만 적절한 파일에 추가:
- 코드 공통 규칙 → `review-code.md`
- 언어 특화 규칙 → `review-language.md`
- 팀 리뷰어 관점 → `review-team.md`

**② 코딩 규칙** (다음 코드 생성에서 처음부터 잘 쓰기 위해):
리뷰에서 발견한 이슈를 **"이렇게 써라" 형태의 규칙**으로 변환한다.

**③ CLAUDE.md/AGENTS.md 페어 (CRITICAL)**:
글로벌 또는 Buzzvil scope에서 한쪽 파일을 수정했다면 페어 파일도 같이 업데이트한다. 도구별 차이(assignee 등)만 분기 섹션으로 유지.
- `~/.claude/CLAUDE.md` ↔ `~/.codex/AGENTS.md`
- `~/buzzvil/CLAUDE.md` ↔ `~/buzzvil/AGENTS.md`
- `~/buzzvil_analysis/CLAUDE.md` ↔ `~/buzzvil_analysis/AGENTS.md`

**분류 게이트 (순서대로 적용)**:

1. **범용성 체크** — 2개 이상 언어/프로젝트에서 재발 가능한가?
   - YES → `~/.claude/coding-rules.md` 코어
   - NO → 2번으로
2. **언어/도메인 특화**:
   - Python/Django/Pydantic → `~/.claude/coding-rules-python.md`
   - Vue + Buzzvil 메인 프로젝트(ads-center, dash 등) → `~/.claude/coding-rules-vue.md`
   - React/Vue 공통 프론트 → `~/.claude/coding-rules-frontend.md`
   - 해당 서브 파일이 없으면 신규 생성 가능
3. **니치 도구/프로젝트 전용** (Playwright/BootstrapVue/Testcontainers 등 특정 도구에 국한된 노하우, 또는 특정 프로젝트 구조/컨벤션에만 해당되는 것):
   - 단일 프로젝트에서만 반복 → `project_{name}.md` 메모리
   - 여러 프로젝트에서 그 도구를 공유 → `reference_tool_{tool}.md` 메모리
   - 둘 다 해당 → 둘 다 저장
   - **코어(coding-rules.md)나 언어 서브 파일에 넣지 않는다** — 모든 세션에 로드되어 노이즈가 된다

**예시 언어 중립화**: 원칙이 범용이면 코어의 서술을 언어 중립적으로 다듬는다. 구체 예시(`list[str] | None`, `npm run build` 등)는 해당 서브 파일에 둔다.

**반영 전 확인**: 대상 파일을 먼저 읽어 이미 포함된 내용인지 확인. 중복 금지.

**예시**:
- "함수 내부 import 발견" → `coding-rules.md` 코어 ("import는 파일 최상단에 배치")
- "Pydantic Field validator 테스트 발견" → `coding-rules-python.md` ("프레임워크 빌트인 검증 테스트 금지"의 Python 예시)
- "Playwright strict mode 위반" → `reference_tool_playwright.md` (도구 전용)

각 반영: `[SKILL-UPDATE] {파일}: {추가 내용 1줄 요약}`
신규 지식 없으면 "스킬 업데이트 없음" 출력 후 건너뛴다.

### 9c: coding-rules.md 분할 관리

반영 후 `~/.claude/coding-rules.md`의 줄 수를 `wc -l`로 확인한다.

**200줄 이상**: 가장 큰 섹션을 서브 파일로 분리한다. **내용은 하나도 삭제하지 않는다.**

1. 가장 줄 수가 많은 섹션(예: `## 테스팅`)을 식별
2. 해당 섹션 내용을 `~/.claude/coding-rules-{섹션명}.md`로 이동
3. coding-rules.md에는 1줄 참조로 교체:
   ```
   ## 테스팅 → `~/.claude/coding-rules-testing.md` 참조
   ```
4. 보고: `[SPLIT] 테스팅 섹션({N}줄) → coding-rules-testing.md로 분리`

**코드 작성 시 로드 규칙** (CLAUDE.md에 이미 명시):
- `coding-rules.md` (코어)는 항상 읽는다
- 서브 파일은 현재 작업 언어/도메인에 해당하는 것만 읽는다

review-*.md는 전용 서브에이전트에 로드되므로 줄 수 제한을 적용하지 않는다.
