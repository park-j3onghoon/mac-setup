---
name: plan-review
description: 구현 계획을 코드 작성 전에 스코프 챌린지·6차원 리뷰·다른 AI 교차 검증으로 통과시킨다.
disable-model-invocation: true
argument-hint: "[계획 파일 경로]"
---

이 스킬이 쓰는 파일은 `plan.md` 하나다.

인자가 경로면 그 파일을, 없으면 대화에 마지막으로 나온 계획을 리뷰한다. 둘 다 없으면 계획 파일 경로를 묻는다.

## 1. 스코프 챌린지

프레임워크·라이브러리 빌트인으로 이미 되는 부분을 코드에서 먼저 찾는다: 저장소 코드와 설치된 의존성 코드를 Grep해 지금 설치된 버전에 있는 기능만 인정한다. 워크트리에 설치본이 없으면 메인 체크아웃의 설치본을 본다. 있으면 그만큼 스코프에서 뺀다. 브랜치가 의존성 선언을 바꿨거나 설치본이 로컬에 없으면 그 후보는 미확인으로 이슈에 적는다. `git log`에 리버트·재작업 흔적이 있는 파일을 이번 계획이 다시 건드리면, 그 자리를 이슈로 낸다.

스코프 질문
1. 기존 코드로 이미 해결되는 부분은?
2. 목표를 달성하려면 바꿔야 하는 최소 파일·함수는 무엇인가?
3. 8+ 파일 수정 또는 2+ 새 클래스/서비스면 scope creep 경고를 낸다.
4. 계획에 임시 우회·TODO 잔존이 있으면 완전판과의 차이·나중에 메우는 비용을 적는다.

미결 갈림길 점검: 계획이 사용자가 골라야 할 결정을 조용히 가정하고 넘어간 자리를 찾는다. 신호는 셋이다. 근거 없이 단정한 방식 선택, 대안이 한 번도 언급되지 않은 분기점, "추후 결정"·"TBD"로 미룬 채 그 위에 후속 단계가 쌓인 곳.

하나라도 있으면 아래 형식으로 보고한다.

```
[미결] {결정 항목}: 계획은 {가정한 것}으로 전제하는데 근거가 없다. {이것이 정해져야 결정되는 후속}
```

미결 갈림길을 보고한 뒤 AskUserQuestion 1회로 처리를 받는다.
- A) 닫고 이어간다 (Recommended): `~/.claude/lib/grill.md`를 Read하고 그 절차로 미결 갈림길을 닫은 뒤, 답을 계획에 반영하고 스코프를 고른다
- B) 계속한다: 미결 갈림길을 `plan.md`의 미결정 항목에 그대로 적고 리뷰를 이어간다

미결 갈림길이 없으면 바로 스코프를 고른다.

스코프는 AskUserQuestion 1회, 3옵션:
- SCOPE REDUCTION: 최소 버전을 제안하고 승인받은 뒤 BIG CHANGE 또는 SMALL CHANGE로 재진입
- BIG CHANGE (Recommended): 차원별 Agent 병렬 리뷰, 차원당 이슈 4개까지 자세히, 나머지는 한 줄씩
- SMALL CHANGE: 인라인 압축 리뷰, 차원당 이슈 1개만 자세히, 나머지는 한 줄씩

SMALL CHANGE는 3줄 이하 수정에만 권한다. 이후 모든 이슈는 그 스코프 안에서 낸다.

→ 완료: 미결 갈림길이 없거나, 모두 닫혀 계획에 반영됐거나, 사용자가 계속을 골랐고, 스코프 셋 중 하나가 정해졌다.

## 2. 차원 고르기

계획의 파일 경로·키워드·변경 유형으로 켤 차원을 고른다. 차원 뒤는 참고 파일(`~/.claude/skills/plan-review/` 아래)과 이슈 번호 머리글자다.

- 항상: Architecture `ref-architecture.md` A · Coding Standards `ref-coding-standards.md` C · Test Coverage `ref-test.md` T · Performance `ref-performance.md` P
- 모델·마이그레이션·쿼리·스키마를 바꾸면: Data/Database `ref-data-database.md` D
- 인증·인가·API 엔드포인트 추가·사용자 입력 처리가 있으면: Security `ref-security.md` S

이슈 번호는 머리글자 뒤에 1부터 매긴다.

→ 완료: 한 줄 출력. `DIMENSION RELEVANCE: 5/6 active (Security skipped: no auth/API changes)`

## 3. 리뷰 실행

### 추천 기준

이슈마다 선택지를 비교해 추천안을 아래 순서로 고르고, 이유에 갈린 기준을 쓴다. 위에 있는 기준이 먼저다.

1. Prefer the option whose worst-case failure reaches the fewest users, rows or services, and name that reach in the reason.
2. A plan step that needs a person to run, watch or repair something by hand in production is itself an issue; prefer the option that handles it automatically (an idempotent rerun, a retry, an alert).
3. Prefer a library or service the repository already uses; recommend a new one only when none of them does the job, and name the ones checked.
4. When options still tie, prefer the one that changes fewer files.

### BIG CHANGE: 차원별 Agent 병렬

ACTIVE 차원마다 Agent를 하나의 메시지에서 동시에 스폰한다. 이슈를 사용자에게 제시할 때는 `~/.claude/lib/answer-style.md`를 Read해 그 규칙대로 쓴다. 각 프롬프트에 넣을 것:
1. 계획 전문
2. "`~/.claude/skills/plan-review/{그 차원의 참고 파일}`을 Read하고 그 기준으로 계획을 훑어라". 경로는 2단계 목록에서 골라 그대로 적는다
3. "`~/.claude/lib/coding/index.md`를 Read하고 그 목록에서 계획이 닿는 모듈을 Read해 그 규칙으로 판단하라"
4. "이슈 번호를 {머리글자}1부터 매겨라". 머리글자는 2단계 목록에서 그 차원 것을 골라 그대로 적는다
5. "이슈 4개까지 응답 형식으로 쓰고, 넘는 이슈는 `[Issue {번호}] {한 줄 요약}`으로 모두 덧붙여라. 없으면 `No issues found.` 반환"
6. 추천 기준 절의 항목

응답 형식:
```
[Issue {번호}] {문제 요약}
  - Option A: {내용} (노력: 낮음, 리스크: 낮음)
  - Option B: {내용} (노력: 중간, 리스크: 낮음)
  → B 추천. 이유: {추천 기준 연결}
```

### SMALL CHANGE: 인라인

Agent 없이 ACTIVE 차원의 참고 파일과, `~/.claude/lib/coding/index.md` 목록에서 계획이 닿는 모듈을 직접 Read하고, 추천안은 추천 기준 절로 고른다. 차원마다 이슈 1개는 응답 형식으로, 나머지는 `[Issue {번호}] {한 줄 요약}`으로 쓰고, 번호는 2단계의 머리글자로 매겨 한 번에 제시한다.

→ 완료: 통합 결과를 제시하고 AskUserQuestion 1회로 "어느 이슈를 계획에 반영할지"를 받았다.

## 4. 종합 산출물

- NOT in scope: 고려했으나 제외한 작업, 항목당 1줄 근거
- What already exists: 하위 문제를 이미 부분적으로 푸는 기존 코드·흐름
- Failure modes: 새 코드 경로마다 테스트, 에러 처리, 실패를 드러내는 수단(로그·에러 응답)이 있는지 적고, 셋 다 없는 경로는 critical gap으로 적는다
- 미결정: 1단계에서 계속을 골라 남긴 미결 갈림길. 항목당 계획이 가정한 것과 언제 정해야 하는지. 없으면 생략
- Completion summary

```
- 스코프 챌린지 (사용자 선택: ___)
- Dimensions: ___/6 active
- Architecture: ___ 이슈
- Data/Database: ___ 이슈 (or skipped)
- Security: ___ 이슈 (or skipped)
- Performance: ___ 이슈 (or skipped)
- Coding Standards: ___ 이슈
- Test Coverage: ___ 이슈
- Critical gaps: ___
```

→ 완료: 해당되는 블록을 모두 채웠다.

## 5. 계획 쓰기

리뷰를 반영한 계획을 `plan.md`에 쓴다. 저장 경로는 `~/.claude/lib/plans-path.md`를 Read하고 그 규칙을 따른다.

→ 완료: 그 경로에 파일이 있다.

## 6. 교차 검증

SMALL CHANGE면 건너뛰고 7단계로 간다. BIG CHANGE면 `~/.claude/lib/cross-check.md`를 Read하고, 지금 에이전트에 맞는 절의 diff가 없는 파일 적대 검증 행을 5단계에서 쓴 `plan.md`의 절대경로로 실행한다. 작업 지시 끝에 "이 계획이 실제 운영에서 어떻게 깨질 수 있는지, 필요한 전제가 성립하지 않을 때 어떤 위험이 있는지 짚어라"를 더한다. 계획에 대응하는 git diff가 이미 있으면 그 diff가 체크아웃된 경로를 대상 경로로, 같은 문장을 리뷰 초점으로 넣은 diff 적대 검증 행을 쓴다. 실행·회수, 멈추거나 실패한 실행의 대체, 결과 취급도 그 문서를 따른다.

발견을 3단계의 응답 형식으로 옮겨 `[Issue X1] ({검증한 AI}) {문제 요약}`부터 번호를 매긴다. 선택지와 추천은 내가 붙이고, 3단계에서 이미 다룬 이슈와 같으면 그 번호를 적는다. 그 목록을 보여 준 뒤 AskUserQuestion 1회:
- A) 제기된 이슈를 전부 Edit로 `plan.md`에 반영 → 7단계
- B) 사용자가 지정한 일부만 반영 → 7단계
- C) 원안대로 진행 → 7단계
- D) 설계 재검토 → 1단계나 3단계로 되돌림

→ 완료: SMALL CHANGE라 건너뛰었거나, 발견이 빠짐없이 이슈 목록으로 제시됐고, 멈추거나 실패한 실행을 자체 적대 점검으로 대체했다면 그 사실을 알렸고, A~D 중 하나를 받았다.

## 7. 마감

`plan.md`의 절대경로를 알리고 멈춘다.

→ 완료: 채팅에 `plan.md`의 절대경로가 남았다.
