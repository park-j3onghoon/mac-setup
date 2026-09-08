---
name: design-log
version: 1.0.0
description: 세션의 SW 설계 논의/결정을 추출해 일반 설계 원칙만 골라 design-decisions.md(review·plan-review 공통 참조)에 누적한다. 프로젝트·프레임워크·회사 특화는 제외하고 메모리/coding-rules로 라우팅. 반드시 사용자와 논의 후 반영. "설계 논의 정리", "설계 결정 정리", "design decision 정리", "design-log" 등으로 트리거.
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - AskUserQuestion
---

# Design Log — 설계 논의 정리

구현 중간/후 세션의 **SW 설계 논의·결정**을 추출해 `~/.claude/skills/design-decisions.md`(review·plan-review 서브에이전트가 자동 참조)에 누적한다.

**핵심: 자동으로 쓰지 않는다. 분류 → 사용자와 논의 → 합의 후 반영.**
(과거에 프로젝트/프레임워크/회사 특화 내용을 일반 SW 원칙에 잘못 섞어 넣은 적이 있어 이 게이트가 필수다.)

## 절차

### 1. 추출
이번 세션에서 오간 설계 논의·결정을 모은다 — 상태머신, 레이어/의존 방향, 추상화, command/query 분리, 도메인 모델, 테스트 전략 등 **설계 차원**. 단순 구현·버그수정·진행보고는 제외.

### 2. 분류 (CRITICAL)
각 항목을 셋 중 하나로 나눈다:
- **(A) 일반 SW 설계 원칙** — 패러다임(Clean Architecture · Hexagonal · CQRS · CQS · TDD · DDD)에 부합하고 **프로젝트·프레임워크·라이브러리·언어·회사와 무관** → `design-decisions.md` 후보.
- **(B) 특화 항목** — 특정 프로젝트(예: payments-api 에러 표준)·프레임워크(예: pydantic 함정)·라이브러리·언어·회사 컨벤션 → `design-decisions.md` **금지**. 메모리(프로젝트 사실)·`coding-rules.md`(언어/팀 규칙)·플랜으로 라우팅.
- **(C) 이미 있음/중복** — CLAUDE.md · coding-rules · design-decisions 에 이미 있음 → 스킵.

### 3. 분류 게이트 (이상 정리 방지) — 각 (A) 후보에 자문
- "프로젝트/프레임워크/라이브러리/언어/회사 이름을 빼도 성립하나?" 아니오 → (B).
- "Clean Arch / Hexagonal / CQRS / CQS / TDD / DDD 중 어디에 부합하나?" 못 대면 재분류.
- "CLAUDE.md / coding-rules / design-decisions 에 이미 있지 않나?" 있으면 (C).

### 4. 사용자 논의 (필수)
분류 결과 + `design-decisions.md`에 넣을 **제안 문구**를 사용자에게 제시하고 AskUserQuestion 으로 확정한다. 사용자가 "이상하다 / 특화다 / 중복이다" 하면 수정·제외한다. **합의 없이 design-decisions.md 에 쓰지 않는다.**

### 5. 반영
- 합의된 (A) → `design-decisions.md`에 append 하거나 기존 섹션과 통합(중복 합치기, 「따르는 패러다임」 아래 배치).
- (B) → 해당 위치(메모리/coding-rules/플랜)에 반영하거나 사용자에게 위임.
- design-decisions.md 는 review·plan-review 가 자동 로드하므로 추가 즉시 리뷰에 반영된다.

### 6. 자가 개선
이 스킬·분류 게이트에 개선점이 있으면 반영한다.
