---
name: hygiene
description: 축적된 규칙/참조 문서의 위생 검사. 중복 합치기, 모순 탐지, 일반화. "위생 검사", "규칙 정리", "hygiene" 등으로 트리거. 5회 작업 완료 시 자동 제안.
---

# /hygiene — 규칙 위생 검사

축적된 규칙, 참조 문서, 스킬을 정리하여 품질을 유지한다.
**규칙을 삭제하지 않는다. 합치고 일반화할 뿐이다.**

## 트리거
- 명시적: "위생 검사", "규칙 정리", "hygiene"
- 자동 제안: session-review에서 self-improvement 3회+ 실행 시 제안

## 대상 파일

### Tier 1: 항상 검사
- `~/.claude/coding-rules.md`
- `~/.codex/skills/plan-review/references/*.md` (6개)

### Tier 2: 요청 시 검사
- `~/.codex/skills/*/SKILL.md` (모든 스킬)
- `~/.codex/AGENTS.md`

## Step 1: 전수 읽기 + 줄 수 기록

## Step 2: 중복/모순 탐지

### 중복: 같은 규칙이 다른 파일에 있는 경우
→ canonical 위치에 유지, 다른 쪽은 "X 참조"로 교체

Canonical 위치 우선순위:
1. coding-rules.md (범용 코딩 규칙)
2. references/*.md (차원별 리뷰 기준)
3. SKILL.md (워크플로우 로직)

### 모순: 파일 A "X 하라" + 파일 B "X 하지 마라"
→ 맥락 차이가 있으면 맥락 명시 추가. 진짜 모순이면 사용자에게 확인.

## Step 3: 일반화

3개 이상 구체적 규칙이 같은 원칙 → 상위 원칙 + 괄호 안 예시 목록으로 변환.

```
BEFORE (3 rules):
  - Pydantic Field(gt=0) 테스트 금지
  - Enum 검증 테스트 금지
  - Django ORM 기본 동작 테스트 금지

AFTER (1 principle):
  - 프레임워크 빌트인 테스트 금지 (Pydantic 검증, Enum, ORM 기본 동작 등)
```

- 구체적 사례를 괄호 안 예시로 남긴다 (정보 손실 방지)
- 포괄하지 못하는 예외는 별도 유지

## Step 4: 계층 정리

ref-*.md 내부 구조 확인:
- Core Principles: 5개 초과 시 체크리스트로 강등 후보
- User Preferences: coding-rules.md 중복이면 참조로 교체
- Examples: 3개 초과 시 대표적인 것만 유지

## Step 5: 크로스 레퍼런스 정리

파일 간 참조 관계를 정리한다. **같은 규칙의 canonical 위치는 1곳만, 나머지는 참조.**
- coding-rules.md의 규칙이 references/*.md에도 있으면 → ref에서 "coding-rules.md 참조"로 교체
- references/*.md 간에 같은 항목이 있으면 → 더 적절한 차원에 유지, 다른 쪽은 제거
- SKILL.md에 인라인으로 적힌 규칙이 ref에 있으면 → SKILL에서 "참조"로 교체

(canonical 우선순위는 Step 2 참조.)

## Step 6: 적용

```
HYGIENE REPORT
══════════════
Duplicates merged:     N개
Contradictions resolved: N개
Rules generalized:     N개 → M개
Cross-references:      N개 교체
BEFORE: XXX줄  →  AFTER: YYY줄 (Delta: -ZZ줄)
```

사용자 확인 후 승인된 항목만 적용.

## 판단 기준

### 합쳐야 하는 것
- 같은 의미를 다른 문장으로 적은 것 / 같은 안티패턴의 다른 사례 / 같은 파일 다른 섹션의 동일 규칙

### 합치면 안 되는 것
- 비슷해 보이지만 적용 맥락이 다른 것 ("None 반환 금지" vs "None 반환 허용" — find vs update 맥락)
- 같은 원칙이지만 언어별로 다른 표현 (Python vs Kotlin)
- 다른 차원에서 다른 관점으로 보는 것 (security 입력 검증 vs coding-standards 타입 안전성)

### 절대 하지 않는 것
- 규칙 삭제 (사용 빈도 낮다고 제거하지 않음)
- 의미 변경 (일반화 시 원래 의미 보존 필수)
- 사용자 확인 없이 적용
