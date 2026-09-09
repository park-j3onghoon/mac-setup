---
name: hygiene
description: 누적된 규칙 파일의 위생 검사 — 중복·모순·일반화 후보·스테일을 찾아 승인받은 것만 반영한다.
disable-model-invocation: true
argument-hint: "[전체]"
---

# /hygiene — 규칙 파일 위생 검사

**불변 조건** (매 실행)
- **Lossless**: 규칙의 의미를 보존한다. 쓰는 조작은 합치기·일반화·참조 교체 셋뿐이고, 사용 빈도가 낮은 규칙도 지우지 않는다.
- **Approval gate**: 대상 파일 쓰기는 Step 3의 승인 이후, 승인된 항목에만 한다. 그전까지는 읽기만 한다.

## 대상 (allowlist)

**Tier 1 — 기본**
- `~/.claude/coding-rules.md`, `~/.claude/coding-rules-*.md`
- `~/example/.claude/pr-rules.md`
- `~/.claude/skills/plan-review/ref-*.md`
- `~/.claude/lib/review/*.md`

**Tier 2 — 인자로 `전체`를 받았을 때 추가**
- `~/.claude/skills/*/SKILL.md` 전부
- `~/.claude/CLAUDE.md`

## Step 1: 대상 읽기

allowlist를 펼쳐 나온 파일을 전부 Read하고, 줄 수는 `wc -l`로 센다.

```
FILE SIZES
══════════
{파일명}: {N}줄
─────────────────────────
Total:    {합계}줄
```

완료 기준: allowlist의 모든 경로가 표에 있고(파일이 없는 경로는 `(없음)`으로 적는다) Total이 계산돼 있다.

## Step 2: 탐지 — 한 패스, 네 종류

- **[D] 중복(DRY)** — 다른 파일에 같은 원칙이 다른 표현으로 있거나, 같은 파일의 다른 섹션에 같은 규칙이 반복된다.
  → canonical 1곳만 남기고 나머지는 포인터(`"{파일} §{섹션} 참조"` — 줄번호 대신 섹션 앵커)로 교체한다. canonical 우선순위는 ① `coding-rules*.md`(범용 코딩 규칙) ② `ref-*.md`·`lib/review/*.md`(차원별 리뷰 기준) ③ `SKILL.md`(워크플로우 절차). 같은 순위끼리 겹치면 더 적절한 차원 쪽에 둔다.
- **[C] 모순** — "X 하라" ↔ "X 하지 마라", 또는 예외 조건이 명시되지 않은 채 상충하는 규칙.
  → 적용 맥락이 갈리는 것이면 모순이 아니므로 양쪽에 **scope qualifier**(맥락 한정 문구)를 붙인다. 맥락으로 설명되지 않으면 어느 쪽을 남길지 사용자에게 묻는다.
- **[G] 일반화(Rule of Three)** — 같은 원칙을 말하는 구체 규칙이 3개 이상 모여 있다.
  → 상위 원칙 1개 + 괄호 안 예시로 합친다. 원칙이 포괄하지 못하는 사례는 별도 규칙으로 남긴다.
- **[S] 스테일** — 가리키는 경로·스킬·단계·줄번호가 지금 존재하지 않거나, 특정 프로젝트에서 한 번 쓰고 굳은 서브섹션이다.
  → 현행 사실로 고쳐 쓰고, 프로젝트 특화 내용은 메모리(`~/.claude/projects/*/memory/`)로 옮길 것을 제안한다.

**False duplicate — 합치지 않고 그대로 둔다**
- 적용 맥락이 다른 것: "None 반환 금지"(update·delete) vs "None 반환 허용"(find)
- 같은 원칙의 언어별 표현(Python vs Kotlin)
- 다른 차원의 다른 관점(security의 입력 검증 vs coding-standards의 타입 안전성)

**`ref-*.md` 계층** — 파일이 실제로 쓰는 섹션에 임계값을 건다. `## Core Principles`가 5개를 넘으면 `## Checklist`로 내릴지 판단하고([G]), `## Examples`가 3개를 넘으면 가장 대표적인 것만 남긴다(예시는 규칙이 아니라 lossless의 예외). `## Checklist`만 있고 Core Principles가 없는 파일은 그대로 둔다.

발견을 종류별 블록으로 출력한다.

```
DUPLICATES FOUND: N개
═══════════════════
[D1] "{규칙}" — {파일A}:{줄} ↔ {파일B}:{줄}
     → 합치기: {파일A}에 유지, {파일B}에서 "{파일A} §{섹션} 참조"로 교체

CONTRADICTIONS FOUND: N개
════════════════════════
[C1] coding-rules.md:108 "에러 메시지는 리소스명+id" ↔ ref-security.md:32 "에러 메시지에 내부 정보 노출 금지"
     → 모순 아님: 도메인 예외 메시지는 서버 로그용, 노출 금지는 클라이언트 응답용. 양쪽에 맥락 한정 문구 추가

GENERALIZATIONS FOUND: N개
═════════════════════════
[G1] {파일}:{줄 범위}
     BEFORE (3 rules, 9 lines): Pydantic Field(gt=0) 테스트 금지 / Enum 검증 테스트 금지 / Django ORM 기본 동작 테스트 금지
     AFTER (1 principle + examples, 4 lines): 프레임워크 빌트인 테스트 금지 (Pydantic 검증, Enum, ORM 기본 동작 등)
           + "이 테스트가 검증하는 건 우리 코드인가, 프레임워크인가?" 자문

STALE FOUND: N개
════════════════
[S1] ref-architecture.md:38 "FE money-path async trigger" — 특정 프로젝트에서만 쓰인 퇴적물
     → 메모리로 이관 제안
```

완료 기준: Step 1 표의 모든 파일 쌍을 대조했고, 네 종류마다 항목 목록 또는 `0개`가 적혀 있다.

## Step 3: 보고와 승인

```
HYGIENE REPORT (제안 — 아직 반영 전)
══════════════
Duplicates to merge:         N개
  그중 참조 교체:            N개
Contradictions to resolve:   N개
Rules to generalize:         N개 → M개 (줄 수: -XX줄)
Stale to refresh:            N개

BEFORE: XXX줄 (대상 합계)
AFTER:  YYY줄 (제안 전부 반영 시)
Delta:  -ZZ줄 (XX% 축소)
```

이어서 AskUserQuestion으로 묻는다: **"위 변경사항을 적용할까요? (전부 / 번호 선택 / 건너뛰기)"**

완료 기준: 리포트를 출력하고 사용자의 선택을 받았다.

## Step 4: 반영

- 승인된 번호의 항목만 Edit로 반영한다.
- `~/.claude/CLAUDE.md`를 고쳤으면 CLAUDE.md의 페어 규칙대로 `~/.codex/AGENTS.md`도 같은 내용으로 고친다.
- 항목 번호마다 `[적용]` / `[건너뜀]`을 한 줄씩 적고, 대상 파일 줄 수를 다시 세어 실제 AFTER·Delta를 보고한다.

완료 기준: 모든 항목 번호가 `[적용]` 또는 `[건너뜀]`으로 보고됐고, 재집계한 AFTER 줄 수가 Step 3 예상치와 나란히 적혀 있다.
