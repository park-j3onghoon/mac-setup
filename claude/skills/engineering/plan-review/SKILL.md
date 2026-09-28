---
name: plan-review
description: 구현 계획을 코드 작성 전에 스코프 챌린지·6차원 리뷰·Codex 적대 검증으로 통과시킨다.
disable-model-invocation: true
---

이 스킬이 쓰는 파일은 `plan.md` 하나이고, 나머지 코드·문서는 읽기만 한다.

## Step 0: 스코프 챌린지

프레임워크·라이브러리 빌트인으로 이미 되는 부분을 먼저 찾는다. 있으면 그만큼 스코프에서 뺀다. `git log`에 리버트·재작업 흔적이 있는 파일을 이번 계획이 다시 건드리면, 그 자리를 이슈로 낸다.

스코프 질문
1. 기존 코드로 이미 해결되는 부분은?
2. 목표를 달성하려면 꼭 바꿔야 하는 파일·함수는 무엇인가?
3. 8+ 파일 수정 또는 2+ 새 클래스/서비스면 scope creep 경고를 낸다.
4. 계획에 임시 우회·TODO 잔존(숏컷)이 있으면 완전판과의 차이·나중에 메우는 비용을 적는다.

미결 갈림길 점검: 계획이 사용자가 골라야 할 결정을 조용히 가정하고 넘어간 자리를 찾는다. 신호는 셋이다. 근거 없이 단정한 방식 선택(왜 그것인지가 없음), 대안이 한 번도 언급되지 않은 분기점, "추후 결정"·"TBD"로 미룬 채 그 위에 후속 단계가 쌓인 곳.

하나라도 있으면 아래 형식으로 보고한다.

```
[미결] {결정 항목}: 계획은 {가정한 것}으로 전제하는데 근거가 없다. {이것이 정해져야 결정되는 후속}
```

미결을 보고한 뒤 AskUserQuestion 1회로 처리를 받는다.
- A) 멈춘다 (Recommended): 사용자가 `/grill`로 결정을 닫고 다시 온다
- B) 계속한다: 미결을 `plan.md` 「미결정」에 그대로 적고 리뷰를 이어간다

미결이 없으면 바로 스코프를 고른다.

스코프는 AskUserQuestion 1회, 3옵션:
- A) SCOPE REDUCTION: 최소 버전을 제안하고 승인받은 뒤 B 또는 C로 재진입
- B) BIG CHANGE (Recommended): 차원별 Agent 병렬 리뷰, 차원당 최대 4개 이슈
- C) SMALL CHANGE: 인라인 압축 리뷰, 차원당 1개 이슈

기본은 B다. C는 오타 수준(3줄 안팎) 수정에만 권한다. 여기서 고른 스코프는 settled다. 이후 모든 이슈는 그 스코프 안에서 낸다.

완료 기준: 미결 갈림길이 없거나 사용자가 계속을 골랐고, 스코프 A/B/C 중 하나가 정해졌다.

## Step 0.5: 차원 triage

계획의 파일 경로·키워드·변경 유형으로 6차원의 ACTIVE/SKIP을 정한다.

| 차원 | 활성 조건 |
|---|---|
| Architecture | 항상 ACTIVE |
| Coding Standards | 항상 ACTIVE |
| Test Coverage | 항상 ACTIVE |
| Data/Database | 모델, 마이그레이션, 쿼리, 스키마 변경 |
| Security | 인증, 인가, API 엔드포인트 추가, 사용자 입력 처리 |
| Performance | 쿼리, 루프, 대량 데이터, 외부 API, 동시성 |

완료 기준: 한 줄 출력. `DIMENSION RELEVANCE: 5/6 active (Security skipped: no auth/API changes)`

## Step 1: 리뷰 실행

차원 → 참고 파일(모두 `~/.claude/skills/plan-review/` 아래): Architecture `ref-architecture.md` · Coding Standards `ref-coding-standards.md` · Test Coverage `ref-test.md` · Data/Database `ref-data-database.md` · Security `ref-security.md` · Performance `ref-performance.md`.

### B) BIG CHANGE: 차원별 Agent 병렬

ACTIVE 차원마다 Agent를 하나의 메시지에서 동시에 스폰한다. 이슈를 사용자에게 제시할 때는 `~/.claude/lib/answer-style.md`를 Read해 그 규칙대로 쓴다. 각 프롬프트에 넣을 것:
1. 계획 전문
2. "`~/.claude/skills/plan-review/{그 차원의 참고 파일}`을 Read하고 그 체크리스트로 계획을 훑어라". 경로는 위 매핑에서 골라 그대로 적는다
3. "`~/.claude/lib/coding-rules.md`와 계획이 건드리는 스택의 서브파일(`coding-rules-python.md`·`coding-rules-frontend.md`·`coding-rules-db.md`)을 Read하고 그 규칙으로 판단하라"
4. "이슈 번호를 {N}부터 시작하라"
5. "최대 4개 이슈. 없으면 `No issues found.` 반환"
6. 아래 「리뷰 관점」의 엔지니어링 선호와 인지 패턴

응답 형식:
```
[Issue {N}] {문제 요약}
  - Option A: {내용} (노력: 낮음, 리스크: 낮음)
  - Option B: {내용} (노력: 중간, 리스크: 낮음)
  → B 추천. 이유: {인지 패턴 또는 엔지니어링 선호 연결}
```

이슈 번호: Architecture 1~4 · Data/Database 5~8 · Security 9~12 · Performance 13~16 · Coding Standards 17~20 · Test Coverage 21~24.

### C) SMALL CHANGE: 인라인

Agent 없이 ACTIVE 차원의 참고 파일과 `~/.claude/lib/coding-rules.md`를 직접 Read하고, 차원당 핵심 1개 이슈만 같은 번호 범위로 매겨 한 번에 제시한다.

완료 기준: 통합 결과를 제시하고 AskUserQuestion 1회로 "어느 이슈를 계획에 반영할지"를 받았다.

## Step 2: 종합 산출물

- NOT in scope: 고려했으나 제외한 작업, 항목당 1줄 근거
- What already exists: 하위 문제를 이미 부분적으로 푸는 기존 코드·흐름
- Failure modes: 새 코드패스마다 테스트 커버? 에러 핸들링? 무음 실패? 3개 모두 없으면 critical gap
- 미결정: Step 0에서 계속을 골라 남긴 갈림길. 항목당 계획이 가정한 것과 언제 정해야 하는지. 없으면 생략
- Completion summary

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

완료 기준: 해당되는 블록을 모두 채웠다.

## Step 3: 계획 저장

리뷰를 반영한 최종 계획을 `plan.md`에 쓴다. 저장 경로는 `~/.claude/lib/plans-path.md`를 Read하고 그 규칙을 따른다.

완료 기준: 그 경로에 파일이 있다.

## Step 3.5: Codex 적대 검증 (모든 실행에서 필수)

이종 LLM(Codex/GPT 계열)에게 계획을 red-team 시킨다. `~/.claude/lib/codex-adversarial.md`를 Read하고 「diff가 없는 파일(계획서 등) 적대 검증」 행을 Step 3에서 저장한 `plan.md`의 절대경로로 실행한다. focus 문구에는 "이 계획이 실제 운영에서 어떻게 깨질 수 있는지, 필요한 전제가 성립하지 않을 때 어떤 위험이 있는지 짚어라"를 더한다. 계획에 대응하는 git diff가 이미 있으면 같은 focus로 「diff 적대 검증」 행을 쓴다. 비동기 실행·대기·회수, 대상 브랜치 워크트리 기준, stall 시 대체, stdout verbatim 규칙도 그 문서를 따른다.

Codex stdout을 원본 그대로 붙인 뒤 AskUserQuestion 1회:
- A) 제기된 이슈를 전부 Edit 로 plan.md 에 반영 → Step 4
- B) 사용자가 지정한 일부만 반영 → Step 4
- C) 원안대로 진행 → Step 4
- D) 설계 재검토 → Step 0 또는 Step 1로 되돌림

완료 기준: Codex 리포트(stall로 판단해 cancel 후 자체 적대 점검으로 대체했다면 그 고지)를 제시하고 A~D 중 하나를 받았다.

## Step 4: 구현 시작 확인

AskUserQuestion:
```
계획이 {저장한 절대경로}에 저장되었습니다.
- A) 구현 시작
- B) 계획 수정 필요
- C) 지금은 구현하지 않음
```

완료 기준: 구현은 A) 구현 시작을 받은 뒤에만 착수한다.

## 리뷰 관점

Agent 프롬프트와 인라인 리뷰가 공통으로 쓰는 판단 기준.

엔지니어링 선호: 지식의 중복은 한 출처로 모으되 우연한 중복은 Rule of Three까지 둔다(`~/.claude/lib/coding-rules.md` §2 Module "Abstraction discipline" · §9 Simple Design) · 테스트와 엣지 케이스는 많은 쪽 · 명시적 > 영리한 코드 · 최소 diff.

인지 패턴
1. Blast radius: 최악의 경우 영향 범위
2. Boring by default: 검증된 기술 우선
3. Incremental > revolutionary: 되돌릴 수 있는 작은 단계로 쪼갠다
4. Systems over heroes: 새벽 3시에도 안전하게 도는가
5. Reversibility: 실패 비용을 낮게
6. Essential vs accidental complexity: 진짜 문제를 푸는가
7. Make the change easy, then make the easy change
8. Two-week smell test: 2주 안에 기능을 못 붙이면 아키텍처 문제
