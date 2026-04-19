---
name: plan-review
version: 3.1.0
description: 계획 완성 후 구현 전에 6개 서브에이전트로 체계적 리뷰 후 Codex CLI로 설계 재검증. Plan Mode 여부 무관. Step 0 스코프 챌린지 → 6 Agent 병렬 → 계획 저장 → Codex adversarial 검증 → 구현 여부 확인.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
  - Bash
---

# Plan Review v3.1 — 6-Agent Parallel + Codex Adversarial

계획을 구현 전에 리뷰한다. **Plan Mode 여부와 무관하게 발동.** 코드 변경 절대 금지.

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
6. **Essential vs accidental complexity** — 진짜 문제를 푸는가
7. **Make the change easy, then make the easy change**
8. **Two-week smell test** — 2주 안에 기능 못 붙이면 아키텍처 문제

## Step 0: 스코프 챌린지

### 사전 검색 (Search Before Building)
- 프레임워크 빌트인 있는지?
- 현재 best practice인지?
- 커스텀 솔루션 대신 빌트인 가능하면 스코프 축소 기회.

### 스코프 질문
1. 기존 코드로 이미 해결되는 부분은?
2. 목표 달성을 위한 최소 변경 세트는?
3. 8+ 파일 수정 또는 2+ 새 클래스/서비스 → 경고
4. 완전한 버전인가 숏컷인가? AI 보조라면 완전한 구현 권장.

AskUserQuestion으로 3가지 옵션:
- **A) SCOPE REDUCTION** — 최소 버전 제안 후 리뷰
- **B) BIG CHANGE** — 6개 Agent 동시 병렬 리뷰 (차원당 최대 4개 이슈)
- **C) SMALL CHANGE** — 인라인 압축 리뷰 (차원당 1개 이슈)

사용자가 SCOPE REDUCTION을 선택하지 않으면, 이후 스코프 축소 재주장 금지.

## Step 0.5: 차원 관련성 판단

계획의 파일 경로, 키워드, 변경 유형으로 6개 차원의 ACTIVE/SKIP 결정:

| 차원 | 활성 조건 |
|------|----------|
| Architecture | **항상 ACTIVE** |
| Coding Standards | **항상 ACTIVE** |
| Test Coverage | **항상 ACTIVE** |
| Data/Database | 모델, 마이그레이션, 쿼리, 스키마 변경 |
| Security | 인증, 인가, API 엔드포인트 추가, 사용자 입력 처리 |
| Performance | 쿼리, 루프, 대량 데이터, 외부 API, 동시성 |

출력:
```
DIMENSION RELEVANCE: 5/6 active (Security skipped — no auth/API changes)
```

## Step 1: 리뷰 실행

### BIG CHANGE — 6 Agent 동시 병렬

ACTIVE인 차원마다 Agent를 **하나의 메시지에서 동시에** 스폰한다.

각 Agent 프롬프트에 포함할 내용:
1. **계획 전문**
2. **참조 문서 내용** — 해당 차원의 `ref-{dimension}.md`를 Read한 뒤 프롬프트에 포함
3. **이슈 번호 시작점** — "이슈 번호를 {N}부터 시작하라"
4. **제한** — "최대 4개 이슈. 없으면 'No issues found.' 반환"
5. **엔지니어링 선호와 인지 패턴** — 위 목록 포함

각 Agent는 아래 형식으로 응답:
```
[Issue {N}] {문제 요약}
  - Option A: {내용} — 노력: 낮음, 리스크: 낮음
  - Option B: {내용} — 노력: 중간, 리스크: 낮음
  → B 추천. 이유: {인지 패턴 또는 엔지니어링 선호 연결}
```

**이슈 번호 할당:**
- Architecture: 1~4
- Data/Database: 5~8
- Security: 9~12
- Performance: 13~16
- Coding Standards: 17~20
- Test Coverage: 21~24

SKIP된 차원의 번호 범위는 건너뛴다.

6 Agent 결과 수집 후 통합하여 사용자에게 제시. AskUserQuestion 1회.

### SMALL CHANGE — 인라인

Agent 스폰 없이 직접 ref-*.md를 읽고, ACTIVE 차원당 핵심 1개 이슈만 뽑아서 번호 매긴 리스트로 한 번에 제시. AskUserQuestion 1회.

### SCOPE REDUCTION

최소 버전 제안 → 승인 → BIG/SMALL 선택.

## Step 2: 종합 산출물

### NOT in scope
고려했으나 명시적으로 제외한 작업 (항목당 1줄 근거)

### What already exists
하위 문제를 이미 부분적으로 해결하는 기존 코드/흐름

### Failure modes
각 새 코드패스: 테스트 커버? 에러 핸들링? 무음 실패?
3개 모두 없음 = **critical gap**

### Completion summary
```
- Step 0: 스코프 챌린지 (사용자 선택: ___)
- Dimensions: ___/6 active
- Architecture: ___ 이슈
- Data/Database: ___ 이슈 (or skipped)
- Security: ___ 이슈 (or skipped)
- Performance: ___ 이슈 (or skipped)
- Coding Standards: ___ 이슈
- Test Coverage: ___ 이슈
- Critical gaps: ___
```

## Step 3: 계획 저장

리뷰 반영 최종 계획을 `docs/{작업명}/plan.md`에 저장.

## Step 3.5: Codex Adversarial 검증 (필수)

계획 저장 직후, 이종 LLM(Codex/GPT 계열)에게 설계 자체의 타당성을 공격적으로 검증받는다. Opus가 놓쳤을 가정·트레이드오프·실패 모드를 짚는 단계이므로 **모든 plan-review 실행에서 필수**.

### 실행

```bash
CODEX_SCRIPT=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1)

# plan.md만 staged 상태로 만들어 다른 변경과 섞이지 않게 한다
git add docs/{작업명}/plan.md

# Adversarial review — Bash tool의 run_in_background: true 로 실행
node "$CODEX_SCRIPT" adversarial-review --background "docs/{작업명}/plan.md 의 설계 선택, 가정, 트레이드오프, 실패 모드를 공격적으로 검증하라. 이 계획이 실제 운영에서 어떻게 깨질 수 있는지, 필요한 전제가 성립하지 않을 때 어떤 위험이 있는지 짚어라."
```

- `--background`는 Codex 플러그인 자체 배경 모드이고, Claude Code Bash tool도 `run_in_background: true`로 띄워 두 층으로 비동기 처리한다.
- `BashOutput`으로 stdout을 polling하면서 완료까지 대기. **timeout은 명시하지 않는다** (Codex가 충분히 깊게 돌 수 있도록).
- Codex stdout은 **원본 그대로** 사용자에게 제시. 요약/paraphrase 금지.

### 결과 반영

Codex 리포트를 제시한 뒤 AskUserQuestion 1회:
- A) Codex가 제기한 이슈를 plan.md에 반영 → Edit으로 plan.md 업데이트 → Step 4
- B) Codex 제안을 일부만 반영 (사용자가 항목 지정) → 반영 후 Step 4
- C) Codex 제안 없이 원안대로 진행 → Step 4
- D) 설계 재검토 필요 → Step 0 또는 Step 1로 되돌림

## Step 4: 구현 시작 확인

절대 바로 구현 시작 금지. AskUserQuestion:
```
계획이 docs/{작업명}/plan.md에 저장되었습니다.
- A) 구현 시작
- B) 계획 수정 필요
- C) 지금은 구현하지 않음
```

## Step 5: 자가 개선 (Self-improvement)

구현 시작 확인 후, 다음 단계로 넘어가기 전에 이번 리뷰에서 학습한 내용을 반영한다.

### 업데이트 대상

1. **ref-*.md 참조 문서** — 이번 리뷰에서 발견한 새로운 패턴/위반이 기존 참조 문서에 없으면 추가
   - 예: 새로운 N+1 패턴 → ref-performance.md Checklist에 추가
   - 예: 새로운 보안 위반 패턴 → ref-security.md에 추가
2. **coding-rules.md** — 이번 리뷰에서 확정된 새 코딩 규칙이 있으면 추가
3. **메모리** — 프로젝트 맥락, 사용자 피드백 중 다음 세션에도 유효한 것
4. **이 스킬 자체** — 워크플로우 개선점 (드물게, 명확한 경우만)

### 판단 기준

반영할 것:
- 이번 리뷰에서 **2회 이상 반복**된 이슈 패턴
- 사용자가 **명시적으로 교정**한 리뷰 기준
- 참조 문서에 **없는** 새 체크리스트 항목

반영하지 않을 것:
- 이번 작업에서만 유효한 일시적 판단
- 이미 참조 문서/coding-rules.md에 있는 내용
- 사용자가 "이번만" 이라고 한 예외

### 실행

업데이트할 내용이 있으면 1줄씩 나열 후 자동 반영. 없으면 스킵.
```
[Self-improvement] ref-performance.md에 "Django async view에서 sync ORM 호출" 패턴 추가
[Self-improvement] coding-rules.md에 "select_for_update 사용 시 트랜잭션 범위 최소화" 규칙 추가
```

## 브랜치 이력 확인
git log에서 이전 리뷰 기반 리팩토링/리버트 흔적이 있으면 해당 영역을 더 공격적으로 리뷰.
