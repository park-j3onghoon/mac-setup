---
name: review
version: 4.1.0
description: PR 랜딩 전 풀 워크플로우 코드 리뷰 — 3개 서브에이전트 병렬 + Codex(선택) + AUTO-FIX + 변경 설명 문서 + pr-size-check + push 안내까지. "리뷰해줘", "코드 리뷰", "풀 리뷰" 등으로 트리거. PR 단어가 들어간 "PR 리뷰"는 /pr-review-report(보고만)를 사용.
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
역할: review-team.md의 리뷰어 카탈로그(R1~R24 매핑표)별 관점. diff 도메인에 해당하는 리뷰어 위주로 점검(매핑표 도메인 컬럼 활용).

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

`--background`(Codex 자체 배경 모드)와 Bash tool `run_in_background: true`로 두 층 비동기 처리하고, BashOutput으로 stdout을 polling하며 완료까지 대기한다. Codex stdout은 **원본 그대로 보존**하여 Step 4 결과 통합에 합친다. 요약·paraphrase 금지.

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

### 5d: ASK 항목 일괄 질문
ASK 항목을 하나의 AskUserQuestion으로 묶어서 질문.

### 5e: 승인된 수정 적용

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

이 PR이 왜 필요하고 어떻게 동작하는지 설명하는 문서를 생성한다. 시작 전 `~/.claude/skills/review/references/change-doc.md`를 Read한다 — 호출 체인(수정 함수 `← 수정` 표시) + 파일별 5항목(경로/역할/왜/변경/설계결정) 양식이 거기 있다. 생성 후 사용자에게 보여주고 저장 여부를 묻는다.

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

`/pr-size-check` 스킬을 실행하고, 통과 후 **push 명령어를 절대 경로 포함하여 출력**한다:

```
/review + /pr-size-check 완료. 아래 명령어로 push해주세요:

! cd {현재 작업 디렉토리 절대 경로} && git push
```

**주의**: `git push`와 `gh pr create`는 PreToolUse hook으로 차단된다. 사용자가 `!` 접두사로 직접 실행해야 한다. Claude가 직접 `git push`를 실행하지 않는다.

## Step 9: 스킬 자가 개선

리뷰에서 내린 결정/발견한 패턴 중 스킬 파일에 없는 내용을 반영한다. 시작 전 `~/.claude/skills/review/references/self-improve.md`를 Read한다 — 신규 지식 추출(9a) + 양방향 반영(9b: 리뷰 체크리스트/coding-rules/CLAUDE↔AGENTS 페어, 분류 게이트) + coding-rules 분할 관리(9c)가 거기 있다. 신규 지식 없으면 "스킬 업데이트 없음" 출력 후 건너뛴다.
