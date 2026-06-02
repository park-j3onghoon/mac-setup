---
name: hygiene
description: 축적된 규칙/참조 문서의 위생 검사. 중복 합치기, 모순 탐지, 일반화. "위생 검사", "규칙 정리", "hygiene" 등으로 트리거. 5회 작업 완료 시 자동 제안.
allowed-tools:
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - AskUserQuestion
---

# /hygiene — 규칙 위생 검사

축적된 규칙, 참조 문서, 스킬을 정리하여 품질을 유지한다.
**규칙을 삭제하지 않는다. 합치고 일반화할 뿐이다.**

## 트리거

### 명시적
- "위생 검사", "규칙 정리", "hygiene"

### 자동 제안 (session-review에서)
- 직전 5회 작업 동안 self-improvement가 3회 이상 실행됐으면 session-review Step 2에서 hygiene 실행을 제안

## 대상 파일

### Tier 1: 항상 검사
- `~/.claude/coding-rules.md`
- `~/.claude/skills/plan-review/ref-*.md` (6개)
- `~/.claude/skills/review/review-*.md` (3개)

### Tier 2: 요청 시 검사
- `~/.claude/skills/*/SKILL.md` (모든 스킬)
- `~/.claude/CLAUDE.md`

기본은 Tier 1만. 사용자가 "전체" 또는 "스킬도" 라고 하면 Tier 2 포함.

`review/references/*.md`(self-improve.md/change-doc.md 등 스킬 본문 분리분)는 누적 규칙이 아니라 SKILL 절차 외부화본이므로 위생 대상이 아니다.

## Step 1: 전수 읽기

대상 파일(위 Tier 1, 요청 시 Tier 2)을 모두 Read하고 각 파일의 줄 수를 `FILE SIZES` 블록에 파일명별로 기록 + `Total` 합계:
```
FILE SIZES
══════════
{파일명}: {N}줄
─────────────────────────
Total:    {합계}줄
```

## Step 2: 중복/모순 탐지

### 중복 탐지
**같은 규칙이 다른 파일에 있는 경우:**
- 같은 원칙을 다른 표현으로 적은 것 탐지
- 예: coding-rules.md "import는 최상단" + ref-coding-standards.md "import 최상단 배치" → 중복

**같은 파일 내 중복:**
- 체크리스트 항목이 다른 섹션에서 반복

### 모순 탐지
- 파일 A에서 "X 하라" + 파일 B에서 "X 하지 마라"
- 예외 조건이 명시되지 않은 상충 규칙

### 출력
```
DUPLICATES FOUND: N개
═══════════════════
[D1] "import 최상단" — coding-rules.md:18 ↔ ref-coding-standards.md:22
     → 합치기: coding-rules.md에 유지, ref-coding-standards.md에서 "coding-rules.md 참조"로 교체

[D2] "N+1 쿼리 금지" — ref-performance.md:15 ↔ ref-data-database.md:28
     → 합치기: ref-performance.md에 유지 (쿼리 최적화는 performance 차원), ref-data-database.md에서 제거

CONTRADICTIONS FOUND: N개
════════════════════════
[C1] coding-rules.md:26 "update 미존재 시 예외" ↔ ref-security.md:XX "에러 메시지 노출 금지"
     → 모순 아님: 도메인 예외는 내부용, 에러 노출 금지는 클라이언트 응답용. 맥락 차이 명시 추가.
```

## Step 3: 일반화

**3개 이상의 구체적 규칙이 같은 원칙을 말하는 경우**, 상위 원칙으로 일반화한다.

### 일반화 탐지
같은 파일 내에서:
- "A 하지 마라", "B 하지 마라", "C 하지 마라" → "X 원칙: A, B, C 모두 이 원칙의 사례"
- 3개 이상 구체적 규칙을 하나의 원칙 + 사례 목록으로 변환

### 일반화 형식
```
BEFORE (3 rules, 9 lines):
  - Pydantic Field(gt=0) 테스트 금지
  - Enum 검증 테스트 금지
  - Django ORM 기본 동작 테스트 금지

AFTER (1 principle + examples, 4 lines):
  - 프레임워크 빌트인 테스트 금지 (Pydantic 검증, Enum, ORM 기본 동작 등)
    "이 테스트가 검증하는 건 우리 코드인가, 프레임워크인가?" 자문
```

### 일반화 규칙
- 구체적 사례를 **괄호 안 예시**로 남긴다 (정보 손실 방지)
- 일반화된 원칙이 모든 사례를 포괄하는지 확인
- 포괄하지 못하는 예외 사례는 별도로 남긴다

## Step 4: 계층 정리

각 ref-*.md의 내부 구조가 계층적인지 확인:

```
## Core Principles     ← 3~5개, 항상 읽히는 핵심 (축소/변경 드묾)
## Checklist           ← 구체적 검증 항목 (자가 개선으로 성장)
## Examples            ← 잘된/위반 예시 (가장 먼저 정리 대상)
## User Preferences    ← coding-rules.md 참조 (중복 시 참조로 교체)
```

- Core Principles가 5개를 초과하면: 정말 "원칙"인지, 체크리스트로 내려야 하는지 판단
- User Preferences가 coding-rules.md와 중복이면: "coding-rules.md 참조"로 교체
- Examples가 3개를 초과하면: 가장 대표적인 것만 남기고 나머지 제거

## Step 5: 크로스 레퍼런스 정리

파일 간 참조 관계를 정리한다:
- coding-rules.md의 규칙이 ref-*.md에도 있으면 → ref에서 "coding-rules.md 참조"로 교체
- ref-*.md 간에 같은 항목이 있으면 → 더 적절한 차원에 유지, 다른 쪽은 제거
- SKILL.md에 인라인으로 적힌 규칙이 ref에 있으면 → SKILL에서 "ref-*.md 참조"로 교체

**원칙: 같은 규칙의 canonical 위치는 1곳만. 나머지는 참조.**

Canonical 위치 우선순위:
1. coding-rules.md (범용 코딩 규칙)
2. ref-*.md (차원별 리뷰 기준)
3. SKILL.md (워크플로우 로직)

## Step 6: 적용

발견한 개선사항을 나열:
```
HYGIENE REPORT
══════════════
Duplicates merged:    N개
Contradictions resolved: N개
Rules generalized:    N개 → M개 (줄 수: -XX줄)
Cross-references:     N개 교체

BEFORE: XXX줄 (Tier 1 합계)
AFTER:  YYY줄 (Tier 1 합계)
Delta:  -ZZ줄 (XX% 축소)
```

AskUserQuestion:
> "위 변경사항을 적용할까요? (전부 / 번호 선택 / 건너뛰기)"

승인된 항목만 파일에 반영한다.

## 판단 기준

### 합쳐야 하는 것
- 같은 의미를 다른 문장으로 적은 것
- 같은 안티패턴의 다른 사례
- 같은 파일의 다른 섹션에 있는 동일 규칙

### 합치면 안 되는 것
- 비슷해 보이지만 적용 맥락이 다른 것 (예: "None 반환 금지" vs "None 반환 허용" — find vs update 맥락 차이)
- 같은 원칙이지만 언어별로 다른 표현 (Python vs Kotlin)
- 다른 차원에서 다른 관점으로 보는 것 (security의 입력 검증 vs coding-standards의 타입 안전성)

### 절대 하지 않는 것
- 규칙 삭제 (사용 빈도 낮다고 제거하지 않음)
- 의미 변경 (일반화 시 원래 의미 보존 필수)
- 사용자 확인 없이 적용
