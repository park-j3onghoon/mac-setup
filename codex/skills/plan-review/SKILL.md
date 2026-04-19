---
name: plan-review
description: 계획 완성 후 구현 전에 6개 서브에이전트로 체계적 리뷰. Step 0 스코프 챌린지 후 6개 agent 동시 병렬 실행. 리뷰 완료 후 계획 저장 + 구현 여부 확인.
---

# Plan Review v3 — 6-Agent Parallel Orchestrator

계획을 구현 전에 리뷰한다. 코드 변경 절대 금지.

## 엔지니어링 선호
- DRY 중요, 반복 공격적 지적
- 테스트 많은 쪽, 엣지 케이스 더 많이
- 명시적 > 영리한 코드, 최소 diff
- 과잉도 부족도 안 됨

## 인지 패턴
1. **Blast radius** — 최악의 경우 영향 범위
2. **Boring by default** — 검증된 기술 우선
3. **Incremental > revolutionary** — 빅뱅 금지
4. **Systems over heroes** — 새벽 3시 안전 운영
5. **Reversibility** — 실패 비용 낮게
6. **Essential vs accidental complexity**
7. **Make the change easy, then make the easy change**
8. **Two-week smell test** — 2주 안에 기능 못 붙이면 아키텍처 문제

## Step 0: 스코프 챌린지

### 사전 검색
- 프레임워크 빌트인 있는지?
- 커스텀 솔루션 대신 빌트인 가능하면 스코프 축소 기회.

### 스코프 질문
1. 기존 코드로 이미 해결되는 부분은?
2. 목표 달성을 위한 최소 변경 세트는?
3. 8+ 파일 수정 또는 2+ 새 클래스/서비스 → 경고
4. 완전한 버전인가 숏컷인가? AI 보조라면 완전한 구현 권장.

3가지 옵션:
- **A) SCOPE REDUCTION** — 최소 버전 제안 후 리뷰
- **B) BIG CHANGE** — 6개 agent 동시 병렬 리뷰 (차원당 최대 4개 이슈)
- **C) SMALL CHANGE** — 인라인 압축 리뷰 (차원당 1개 이슈)

## Step 0.5: 차원 관련성 판단

| 차원 | 참조 문서 | 활성 조건 |
|------|----------|----------|
| Architecture | references/architecture.md | **항상 ACTIVE** |
| Coding Standards | references/coding-standards.md | **항상 ACTIVE** |
| Test Coverage | references/test.md | **항상 ACTIVE** |
| Data/Database | references/data-database.md | 모델, 마이그레이션, 쿼리, 스키마 변경 |
| Security | references/security.md | 인증, 인가, API, 사용자 입력 |
| Performance | references/performance.md | 쿼리, 루프, 대량 데이터, 동시성 |

## Step 1: 리뷰 실행

### BIG CHANGE — 6 agent 동시 병렬

ACTIVE인 차원마다 sub-agent를 동시에 스폰한다 (`agents.max_threads = 6`).

각 agent에 전달:
1. 계획 전문
2. 해당 차원의 참조 문서 내용
3. 이슈 번호 시작점 (Architecture: 1, Data: 5, Security: 9, Performance: 13, Coding: 17, Test: 21)
4. "최대 4개 이슈. 없으면 'No issues found.' 반환"
5. 엔지니어링 선호와 인지 패턴

이슈 형식:
```
[Issue {N}] {문제 요약}
  - Option A: {내용} — 노력: 낮음, 리스크: 낮음
  - Option B: {내용} — 노력: 중간, 리스크: 낮음
  → B 추천. 이유: {인지 패턴 연결}
```

6 agent 결과 통합 후 사용자에게 제시. 확인 1회.

### SMALL CHANGE — 인라인

agent 스폰 없이 직접 references/ 읽고, ACTIVE 차원당 핵심 1개 이슈만 번호 매긴 리스트. 확인 1회.

## Step 2: 종합 산출물

### NOT in scope
고려했으나 제외한 작업 (항목당 1줄)

### What already exists
하위 문제를 이미 해결하는 기존 코드/흐름

### Failure modes
각 새 코드패스: 테스트? 에러 핸들링? 무음 실패?
3개 모두 없음 = **critical gap**

### Completion summary
```
- Step 0: 스코프 챌린지 (선택: ___)
- Dimensions: ___/6 active
- Architecture: ___ 이슈
- Data/Database: ___ (or skipped)
- Security: ___ (or skipped)
- Performance: ___ (or skipped)
- Coding Standards: ___ 이슈
- Test Coverage: ___ 이슈
- Critical gaps: ___
```

## Step 3: 계획 저장

`docs/{작업명}/plan.md`에 리뷰 반영 최종 계획 저장.

## Step 4: 구현 시작 확인

바로 구현 시작 금지. 사용자에게 확인:
- A) 구현 시작
- B) 계획 수정 필요
- C) 지금은 구현하지 않음

## Step 5: 자가 개선 (Self-improvement)

다음 단계로 넘어가기 전에 학습 내용을 반영한다.

### 업데이트 대상
1. **references/*.md** — 새로운 패턴/위반이 참조 문서에 없으면 추가
2. **coding-rules.md** (`~/.claude/coding-rules.md`) — 확정된 새 코딩 규칙
3. **이 스킬 자체** — 워크플로우 개선점 (드물게, 명확한 경우만)

### 판단 기준
- 반영: 2회+ 반복 이슈 패턴, 사용자 명시적 교정, 참조 문서에 없는 체크리스트
- 스킵: 일시적 판단, 이미 있는 내용, "이번만" 예외

업데이트할 내용이 있으면 1줄씩 나열 후 자동 반영. 없으면 스킵.

## 브랜치 이력 확인
git log에서 이전 리뷰 기반 리팩토링/리버트 흔적 → 해당 영역 더 공격적 리뷰.
