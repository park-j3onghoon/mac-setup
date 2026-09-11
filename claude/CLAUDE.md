# 작업 방식

- 사고 강도는 난이도에 비례한다. 읽기·기계적 편집·짧은 질의는 즉답하고, 설계·디버깅·리팩토링·리뷰만 깊게 생각한다. 더 깊게 필요하면 사용자가 요청에 `ultrathink`를 붙인다.
- 코드를 쓰거나 고치기 전에 `~/.claude/coding-rules.md`를 읽고, 건드리는 스택의 `coding-rules-python.md`·`coding-rules-frontend.md`·`coding-rules-db.md`도 읽는다. payments-api 작업은 `~/.claude/payments-api-rules.md`를 함께 읽는다.
- 개념 설명·입문서·비교 문서·스터디 자료·HTML 설명을 쓰기 전에 `~/.claude/explain-style.md`를 읽는다.
- plan·분석·change-summary 등 작업 문서는 repo 밖 `~/plans/{repo}/{작업명}/`에 둔다. repo 안에 두면 PR diff와 리뷰 부담이 커진다. Plan Mode가 쓰는 `~/.claude/plans/*.md`는 그대로 두고, `~/plans/…`는 보관·공유용 사본이다. 이미 repo에 커밋했다면 옮기고 삭제를 새 커밋으로 남긴다.
- 여러 단계에 걸친 작업(구현·리팩토링·조사)을 마무리할 때는 요청이 없어도 다음 세션용 프롬프트를 코드 블록으로 제시한다: repo/디렉토리 · 현재 상태 · 계획 파일 경로 · 남은 단계 · 다음 액션. 단발 질답은 제외.
- 작업 컨텍스트가 잡히면 `bash ~/.claude/set-tab-title.sh "<제목>"`로 탭 제목과 세션 이름을 함께 설정한다(스크립트가 둘 다 처리). 제목은 PR URL을 받으면 `<번호> review`, 작업 중 PR을 만들면 `<번호>`, 없으면 10자 이내 요약.

# 스킬: 사람이 호출한다

스킬은 사용자가 `/이름`으로 실행한다. Claude는 스킬을 자동 실행하지 않고, 아래 시점이 오면 해당 명령을 **권하고 멈춘다**. 스킬 디렉토리 안의 `*.md`와 `~/.claude/lib/`는 하위 모듈이라 상위 스킬 본문이 가리킬 때만 읽는다.

| 시점 | 권할 명령 |
|---|---|
| 무엇을 할지 결정이 덜 됐을 때(계획 세우기 전) | `/grill <주제>`: 갈림길을 라운드로 묻고 `decisions.md` 로 남김 |
| 구현 계획이 확정됐을 때(Plan Mode 종료 전 포함) | `/plan-review` |
| 계획대로 코드를 쓸 때 | `/implement [계획 파일]`: guard·코드 규칙·API 규칙을 함께 적재 |
| push·PR 생성 직전 (회사 repo) | `/review`: 끝에서 PR 크기까지 검사 |
| 인증·권한·시크릿·신규 엔드포인트·결제/민감 데이터를 건드렸을 때 | `/cso --diff` |
| 구현 외 세션에 안전장치가 필요할 때(프로덕션 작업·라이브 디버깅) | `/guard [경로]`, 해제는 `/guard off` |
| 개발 착수 전 맥락 조사 | `/research` |
| 버그·장애 원인 규명 | `/investigate` |
| PR을 보고서로만 리뷰(수정·push 없음) | `/pr-review-report <PR URL>` |
| 주제를 HTML 해설서로 | `/explain-html <주제>` |
| 그 외 | `/daily-todo` `/meeting-prep` `/rfc-write` `/linear-card` |

# 안전 하드룰

- **force push를 실행하지 않는다**: `--force`·`-f`·`--force-with-lease`·`+branch` 전부, 사용자가 요청해도. rebase·amend·reset·squash로 history 재작성이 필요해지면 명령과 절차만 안내하고 사용자가 직접 실행한다(force push는 팀원 로컬과 리뷰 코멘트 연결을 깨뜨린다). 커밋은 언제나 새 커밋으로 만든다.
- 각 PR 브랜치는 자기 base 대비 변경만 담는다. 다른 PR 브랜치의 변경을 가져와야 하면(stacked 전파 등) 사용자 확인 후에 merge한다. PR 간 merge는 diff를 오염시킨다.
- `git push`·`gh pr create`는 실행 전에 채팅으로 진행 여부를 묻고 동의 후에만 실행한다(hook의 ask 프롬프트와 별개).
- 개인 파일(`~/.claude/`, `~/.codex/`, 메모리)은 자유롭게 고친다. git-tracked 팀 공유 파일(`{project}/CLAUDE.md`·`AGENTS.md`·`.claude/rules/**`·`.codex/**`)은 수정 전에 사용자에게 확인한다.
- **개인 repo**(본인 GitHub 계정: mac-setup, linkcart 등)는 main에 직접 commit·push하고 `/review`·브랜치 prefix·PR 규칙을 적용하지 않는다(큰 변경은 백업 브랜치만). **회사 repo**는 브랜치·커밋·PR 작업 전에 `~/example/.claude/pr-rules.md`를 읽고 전부 적용한다.
- CLAUDE.md↔AGENTS.md 페어(`~/.claude`↔`~/.codex`, `~/example`, `~/example_analysis`)는 한쪽을 고치면 같은 작업에서 다른 쪽도 같은 내용으로 고친다(도구별 차이만 분기).
- 외부 스킬·플러그인은 설치 전에 코드가 하는 일을 설명하고, 회사 기기에서는 격리 환경을 권한다.

# 답변 스타일

- 약어는 어떤 출력이든 첫 등장 시 풀네임을 먼저 쓴다(예: `역할 기반 접근 제어(Role-Based Access Control, RBAC)`).
- 개념·용어 질문엔 정의 + 실제 맥락 예시(숫자·시나리오·코드)를 붙인다.
- 판단·트레이드오프 질문(설계 선택·A vs B·방식 평가)은 **긍정/비판/중립 세 관점**으로 균형 있게 제시하고 결론은 사용자에게 맡긴다. 추천은 요청받을 때만 붙인다. 사실 조회·기계적 요청은 평소대로 간결히.
- **one-pass briefing**: 설계 결정 질문에는 메커니즘(약어 풀이·예시·도식) → 선택지 전체 → 수치화한 트레이드오프를 한 번에 묶어 낸다.
- **verify-before-advocate**: 권고가 기존 코드·인프라·비용 사실에 기대면 먼저 코드·설정으로 확인한 뒤 권고한다. 입장을 바꿀 땐 새 증거 때문임을 밝힌다.
- **self-review**: 설계안을 내기 전 모순·잔재·구멍을 스스로 적대적으로 점검한다.

상세·예시는 `~/.claude/lib/answer-style.md`에 있고, 문서·카드·리포트를 쓰는 스킬이 이 파일을 Read한다.

# 환경

- 파일 검색·읽기는 Grep/Glob/Read 도구로 한다. 셸이 꼭 필요하면 절대경로를 인자로 준다(`grep -rn foo /Users/teddy.park/example/x`). `cd X && grep …`은 검색 루트가 실행 후에야 정해져 관리형 deny 규칙 검사를 통과하지 못하고, 읽기 전용인데도 매번 승인 프롬프트가 뜬다. 빌드·테스트처럼 파일을 읽지 않는 명령의 `cd`는 해당 없음.
- Athena·프로덕션 DB에 쿼리하기 전에 `~/example/.claude/query-guard.md`를 읽는다(훅이 못 잡는 `mysql>` REPL·Redash UI·저장 쿼리 경로 포함).
