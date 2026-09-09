# 설계 결정 분류

세션에서 오간 **SW 설계 논의·결정**을 셋으로 나누고, 사용자와 합의한 문구만 규칙 파일에 남긴다. 과거에 프로젝트·프레임워크 특화 내용이 일반 원칙에 섞여 들어간 적이 있어 이 분류가 게이트다.

## 1. 추출

설계 차원의 논의만 모은다 — 상태머신, 레이어·의존 방향, 추상화 도입, command/query 분리, 도메인 모델, 테스트 전략, 배치·동시성, 에러 처리. 단순 구현·버그 수정·진행 보고는 제외한다.

## 2. 분류 (CRITICAL)

- **(A) 일반 원칙** — 프로젝트·프레임워크·라이브러리·언어·회사 이름을 빼도 성립하고, `~/.claude/coding-rules.md` §0이 나열한 패러다임(Clean Architecture · Hexagonal · DDD · CQRS/CQS · TDD · Simple Design) 중 하나에 부합한다 → `coding-rules.md` 후보.
- **(B) 특화 항목** — 특정 프로젝트(payments-api 에러 표준)·프레임워크(pydantic 함정)·언어·회사 컨벤션 → 메모리(프로젝트 사실)·`coding-rules-<스택>.md`(스택 규칙)·플랜으로 보낸다.
- **(C) 이미 있음** — CLAUDE.md·coding-rules·메모리에 이미 있으면 스킵한다.

각 (A) 후보에 자문한다: "프로젝트/프레임워크/언어/회사 이름을 빼도 성립하나?" 아니오면 (B). "어느 패러다임에 부합하나?" 못 대면 재분류.

## 3. 문구 제안과 합의

(A)마다 들어갈 자리와 문구를 만들어 사용자에게 보인다.

- **자리**: `~/.claude/coding-rules.md`의 한 섹션 — §1 Architecture · §2 Module · §3 Class/Object · §4 Function · §5 Naming · §6 Errors · §7 Comments · §8 Tests · §9 Simple Design · §10 Change discipline.
- **문구**: 그 파일의 형식대로 영어 한 줄 불릿 — `**Leading term**: 규칙 — 근거나 실패 사례`.
- AskUserQuestion으로 확정하고, 합의된 문구만 반영한다. 사용자가 "특화다 / 중복이다" 하면 (B)·(C)로 되돌린다.

## 4. 반영

(A)는 해당 섹션에 append하거나 뜻이 겹치는 기존 불릿에 통합한다(같은 규칙을 두 줄로 늘리지 않는다). (B)는 2에서 배정한 위치에 반영하거나 사용자에게 위임한다.
