---
name: review
description: PR 랜딩 전 코드 리뷰. 3개 서브에이전트를 병렬 실행하여 코드 공통/언어별/전문 관점으로 빠짐없이 검증한다. "리뷰해줘", "PR 리뷰", "코드 리뷰" 등으로 트리거.
---

# /review — Pre-Landing PR 리뷰

3개 서브에이전트를 병렬 실행하여 빠짐없이 검증한다.

## Step 1: Diff 수집

```bash
BASE=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || echo main)
BRANCH=$(git branch --show-current)
git fetch origin $BASE --quiet
git diff origin/$BASE --stat
git log origin/$BASE..HEAD --oneline
```

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

diff 전문을 각 서브에이전트에 전달. **반드시 3개를 동시에 병렬 실행.**

각 서브에이전트에 포함:
1. diff 전문
2. 해당 기준 파일 내용
3. "PASS면 PASS라고 써라. 추측 금지, 코드에서 직접 검증."

### 서브에이전트 1: 코드 공통 리뷰
기준: `references/review-code.md`
보안, 정확성, 계약 일관성, 클린코드, YAGNI, 아키텍처, 에러핸들링, 관측성, 성능, 테스팅, 운영

### 서브에이전트 2: 언어별 리뷰
기준: `references/review-language.md`
Python/Go/Java/Kotlin/Frontend 관용구, 타입 안전성, 플랫폼 특화

### 서브에이전트 3: 전문 분야별 관점
기준: `references/review-team.md`
인프라/대규모설계, 백엔드, 동시성, 데이터/쿼리, 도메인/비즈니스

## Step 4: 결과 통합

1. 중복 제거 (같은 이슈 → 합치고 출처 표시)
2. 심각도 정렬 (CRITICAL 먼저)
3. 통합 리포트 생성

## Step 5: Fix-First 리뷰

### 5a: 기존 패턴 확인 (필수)
수정 전 해당 패턴이 다른 모듈에서 어떻게 사용되는지 확인.
기존 패턴과 다른 방향이면 AUTO-FIX가 아닌 ASK.

### 5b: 분류
- **AUTO-FIX**: 기계적 수정, 기존 패턴과 일치
- **ASK**: 판단 필요, 아키텍처 결정, 기존 패턴과 다른 방향

### 5c: AUTO-FIX 적용 → ASK 일괄 질문 → 승인된 수정 적용

## Step 6: 문서 확인

변경된 기능의 문서가 업데이트 안 됐으면 INFO 이슈.

## Step 7: 주장 검증 규칙
- "이 패턴은 안전" → 구체적 라인 인용
- "다른 곳에서 처리됨" → 해당 코드 읽고 인용
- "테스트가 커버함" → 테스트 파일과 메서드 이름
- "아마 처리됐을 것" 금지

## 완료
```
Pre-Landing Review: N 이슈 (X critical, Y informational)
Auto-fixed: Z
User-approved: W
Remaining: V
```

## Step 8: 자가 개선

리뷰에서 발견한 새 패턴이 참조 문서에 없으면 추가.
coding-rules.md에 "이렇게 써라" 형태로 변환하여 추가.
신규 지식 없으면 스킵.
