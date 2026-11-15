---
name: rules-refresh
description: AI 규칙(진입 파일·lib·instructions·스킬·검사 스크립트)을 개발 방법론과 Simple Design 기준에 맞춰 다시 짜고, 매주 바뀐 것만 갱신하며, 매달 지난달 머지 PR로 리뷰 규칙을 리뷰봇·사람 리뷰와 대조한다.
disable-model-invocation: true
argument-hint: "[전체 [스킬 이름 | 경로] | 주기 | PR [YYYY-MM]]"
---

인자가 전체면 대상 전부(스킬 이름이나 경로가 붙으면 그것만)를, 주기면 마지막 성공 실행 뒤 바뀐 것을 본다. PR이면 PR 대조 절만 한다. 인자가 없으면 전체다. 전체는 사용자가 띄운 대화형 세션에서만 하고, 헤드리스 실행에서는 주기만 한다.

## 기준과 경로

- 기준은 `~/Downloads/Obsidian Vault/개발 방법론.md`와 `~/Downloads/Obsidian Vault/Simple Design.md` 두 파일이다. 수정과 제안은 모두 이 두 파일 안에서 한다. 코드 레벨은 회사 컨벤션이 방법론보다 먼저이고, 시스템·데이터 레벨은 사용자에게 묻는다.
- 기록 폴더 `~/plans/ai-rules-refresh/notes/`에 대조표 `mapping.md`, 상태 `state.json`, 리포트 `reports/`, 백업 `backups/`, PR 대조 `pr/`를 둔다.
- 대상의 원본 경로:
  - 진입 파일 `~/git/mac-setup/claude/CLAUDE.md`(`~/git/mac-setup/codex/AGENTS.md`는 이 파일의 심링크)
  - lib `~/git/mac-setup/claude/lib/`, `~/git/mac-setup/private/claude/lib/`
  - instructions `~/git/mac-setup/private/claude/instructions/`
  - 스킬 `~/git/mac-setup/claude/skills/`, `~/git/mac-setup/private/claude/skills/`(각 스킬의 agents/openai.yaml 포함)
  - 검사 스크립트 `~/git/mac-setup/scripts/`
- 고치지 않고 제안만 하는 것: 이 스킬 디렉터리, 기준 두 파일, settings.json, 훅(`claude/hooks/`, `private/claude/hooks/`, `codex/hooks/`, `codex/hooks.json`, `codex/config.toml`), 승인·권한·보안 규칙(승인을 받게 하거나 면제하는 문장, 권한·접근을 정하는 문장, `private/claude/lib/security/`, `claude/lib/review/security-gate.md`, `claude/lib/owasp.md`, cso·sec-review 스킬).
- 업무 레포의 CLAUDE.md·AGENTS.md·스킬은 보지 않는다. 키·토큰·자격증명 파일(`~/.claude/.credentials.json`, `~/.codex/auth.json`, 이름에 token·api_key가 든 파일)과 `.env`는 읽지 않는다.

## 1. 준비

1. `~/plans/ai-rules-refresh/notes/state.json`을 Read한다. `last_run`이 없으면 첫 실행이다.
2. 기준 시각은 `last_success.at`이다. 그것이 없으면 `last_run.at`, 그것도 없으면 7일 전이다.
3. `python3 ~/.claude/skills/rules-refresh/refresh.py inputs '{기준 시각}'`을 실행한다. 출력의 기준 sha256이 state의 `last_run.criteria_sha256`과 다르거나 첫 실행이면 대조표 전체를 다시 보고, 작업 중 경로(git status)는 건너뛸 파일이다.
4. 주기인데 state에 `last_success`가 없으면 리포트만 남기는 실행이다. 리포트만 남기는 실행은 4절과 6절을 건너뛴다.
5. `python3 ~/.claude/skills/rules-refresh/refresh.py metrics`의 출력을 전 수치로 남긴다.

→ 완료: 반영할지 리포트만 남길지, 대조표 전체를 다시 볼지, 건너뛸 파일, 전 수치가 정해졌다.

## 2. 입력

- 전체: 대상 파일 전부(인자 범위가 있으면 그 범위)와 대조표 전체 행.
- 주기: 1절 `inputs` 출력의 다른 세션이 고친 규칙, git 밖 private 변경, 바뀐 피드백 메모리, Codex 사용자 메시지. 1절에서 대조표 전체를 다시 보기로 했으면 대조표 전체 행도 넣는다.

→ 완료: 볼 파일과 지적이 출처(파일·커밋·시각)와 함께 모였다.

## 3. 판정

후보는 아래로 찾는다.

- 대조표 `~/plans/ai-rules-refresh/notes/mapping.md`의 기준 항목마다 적힌 규칙 위치가 지금도 같은 뜻으로 있는지 본다. 위치가 없으면 빠진 항목, 뜻이 기준과 반대면 부딪히는 규칙이다.
- Simple Design의 두 기준을 규칙 파일에도 쓴다: 같은 규칙이 두 곳 이상이면 한 곳에 두고 나머지는 포인터로 바꾸며, 지워도 행동이 안 바뀌는 파일·절·규칙은 지운다.
- `~/.claude/lib/skill-writing.md`를 Read하고 대상 줄을 그 규칙에 댄다. 스킬마다 최상위 README.md 표와 버킷 README.md 줄이 그 SKILL.md를 가리키고 설명이 description과 같은지도 본다.
- 지적마다 같은 뜻의 규칙을 Grep으로 찾는다. 없으면 규칙으로 옮긴다. 있는데 같은 지적이 다시 나왔으면 문장을 세게 쓰는 대신 그 규칙이 왜 안 읽혔는지(로드 경로·위치)를 고친다.

후보마다 아래에서 처음 맞는 분류 하나와 근거(file:line, 기준 문장)를 붙인다.

1. 부딪힘: 기준의 어느 문장과 부딪힌다. 출처가 사용자 지적·리뷰봇 대조·다른 AI 제안이어도 하지 않는다.
2. 제안: 고치지 않고 제안만 하는 것에 닿는다.
3. 건너뜀: 건너뛸 파일에 닿는다.
4. 바로: 구조만 바뀐다(중복 합치기·포인터·죽은 문장·위치). 또는 사용자가 이미 한 지적을 규칙으로 옮긴다.
5. 질문: 행동이 바뀐다(새 규칙·뜻 변경·규칙 삭제·서로 부딪히는 지시·새 기준 숫자).

→ 완료: 후보마다 분류와 근거가 붙었다.

## 4. 반영

1. 전체면 질문을 AskUserQuestion으로 하나씩 묻고 답대로 반영한다. 대조표 상태가 `도구 없음`인 기준 항목은 첫 전체 실행에서 적용 방식을 한 번 묻고 대조표 메모 칸에 적는다. 주기면 질문을 리포트에 모은다.
2. git 밖인 `~/git/mac-setup/private/`와 메모리 파일은 고치기 전에 `~/plans/ai-rules-refresh/notes/backups/{YYYY-MM-DD}/` 아래로 원래 경로를 살려 `/bin/cp -p`로 백업한다.
3. 바로 분류를 Edit로 반영한다. 규칙으로 옮긴 피드백 메모리는 지우거나 정본 포인터 한 줄로 줄이고, 같은 디렉터리 MEMORY.md의 그 줄도 고친다.
4. 모듈·절·스킬을 옮기거나 이름을 바꾸면 skill-writing.md 규칙 24대로 포인터와 README를 같은 커밋에서 고치고, `python3 ~/git/mac-setup/scripts/sync-codex-skills.py`로 Codex 연결과 호출 정책을 맞춘다.

→ 완료: 바로 분류가 모두 반영됐고, 고친 private·메모리 파일마다 백업이 있다.

## 5. 검증

1. 아래 셋이 모두 PASS다. 실패하면 고치고 다시 돌린다.

   ```bash
   bash ~/git/mac-setup/scripts/check-layers.sh
   bash ~/git/mac-setup/scripts/verify.sh
   bash ~/git/mac-setup/scripts/check-pair.sh
   ```

2. 대조표의 기준 항목마다 규칙 위치가 있고, 부딪히는 규칙이 0개거나 모두 질문에 있다. 이번 변경에 제안만 하는 경로가 없고, 바뀐 줄에 승인·권한 문장이 없다.
3. `python3 ~/.claude/skills/rules-refresh/refresh.py metrics`의 출력을 후 수치로 남긴다. 전체는 파일·절·규칙 수와 중복이 모두 전보다 줄어야 끝난다. 주기는 늘지 않아야 하고, 지적을 옮겨 늘었으면 같은 실행에서 합치거나 지울 곳을 찾고, 못 찾으면 늘어난 곳마다 질문에 올린다.
4. 다른 AI 적대 검증: `python3 ~/.claude/skills/rules-refresh/refresh.py diff ~/plans/ai-rules-refresh/notes/reports/{YYYY-MM-DD}-{모드}.diff {YYYY-MM-DD} {이번에 고친 mac-setup 경로}`로 diff 파일을 쓴다. 리포트만 남기는 실행이면 대상은 리포트 초안이다. `~/.claude/lib/cross-check.md`를 Read하고 지금 에이전트에 맞는 절대로 부르되, Claude에서는 `node "$CODEX_SCRIPT"` 자리에 `python3 ~/.claude/skills/rules-refresh/refresh.py codex`를 쓰고 `status --wait`는 `run_in_background` 없이 Bash timeout 600000으로 돌린다. 작업 지시에 기준 두 파일 경로와 아래 두 줄을 넣는다.
   - 리뷰 초점: 변경과 제안마다 기준의 어느 문장과 부딪히는지, 구조로 분류한 변경 가운데 행동이 바뀌는 것이 있는지, 빠진 기준 항목이 있는지.
   - 키·토큰·자격증명 파일(`~/.claude/.credentials.json`, `~/.codex/auth.json`, 이름에 token·api_key가 든 파일)과 레포의 `.env`는 읽지 않는다.
5. 발견마다 반영하거나, 반영하지 않으면 두 판단을 리포트에 같이 적는다.

→ 완료: 검사 셋이 PASS이고, 대조표 대조를 통과했고, 다른 AI 발견마다 처리가 적혔다.

## 6. 커밋

`git -C ~/git/mac-setup add -- {이번에 고친 경로}`로 경로를 지정해 커밋한다. 메시지는 `~/.claude/lib/pr-rules.md` 브랜치·커밋 절과 skill-writing.md 규칙 23을 따르고, 끝에 `Rules-Refresh: {모드} {YYYY-MM-DD}` 줄을 붙인다. push는 하지 않는다.

→ 완료: 이번 변경만 담은 커밋이 있고 해시를 적었다.

## 7. 리포트와 상태

1. 리포트를 `~/plans/ai-rules-refresh/notes/reports/{YYYY-MM-DD}-{전체 | 주기}.md`에 한 페이지로 쓴다. 첫 줄은 알림 문구로 쓰인다.

   ```
   # 규칙 갱신 {YYYY-MM-DD} {모드} · 부딪힘 {n} · 바꾼 것 {n} · 질문 {n}
   ## 기준과 부딪힌 것
   - {후보} · 출처 {사용자 지적 | 리뷰봇 대조 | 다른 AI 제안 | 규칙 파일} · 부딪힌 기준 문장 "{인용}" ({기준 파일} {절})
   ## 전후
   파일 {전}→{후} · 절 {전}→{후} · 규칙 {전}→{후} · 줄 {전}→{후} · 중복 {전}→{후}
   ## 바꾼 것
   - {file} {절}: {무엇} ({구조 | 지적 옮김})
   ## 질문
   1. {질문} · 추천 {안} · 근거 {file:line | 기준 문장}
   ## 제안
   - {고칠 곳} · {안}
   ## 건너뛴 파일
   - {경로}
   ## 다른 AI 검증
   - {발견} → {반영 | 두 판단}
   ```

2. state.json의 `last_run`(`at`, `mode`, `criteria_sha256`, `report`)은 항상 고친다. `last_success`(`at`, `commit`)는 반영하는 실행이 5·6절까지 마쳤을 때만 쓴다.

→ 완료: 리포트가 있고 state.json의 `last_run.report`가 그 리포트를 가리킨다.

## PR 대조

인자가 PR이거나, 주기인데 state.json의 `pr_eval.month`가 지난달보다 앞서거나 없으면 `~/.claude/skills/rules-refresh/pr-eval.md`를 Read하고 수행한다. PR 대조는 규칙 파일을 고치지 않으므로 리포트만 남기는 실행에서도 한다. 주기 실행이면 그 리포트 경로를 7절 리포트의 질문 절 끝에 적는다.
