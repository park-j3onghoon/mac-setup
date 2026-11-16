---
name: pr-create
description: push된 브랜치로 PR을 만들어 달라고 할 때 Draft PR을 만든다. 받을 리뷰(CodeRabbit·사내 AI 리뷰 봇)를 추천과 함께 고르게 한 뒤, 제목·본문 초안을 승인받아 만들고 고른 리뷰를 CodeRabbit → 사내 AI 리뷰 봇 순서로 요청해 끝날 때까지 기다린 뒤 지적에 모두 대응한다. push 전인 변경과 이미 PR이 있는 브랜치에는 쓰지 않는다.
effort: xhigh
---

## 1. 대상 확정

`~/.claude/lib/push.md`를 Read하고 그 문서 첫머리대로 대상을 정하되, `status`를 보기 전에 `git -C {작업 디렉토리} fetch origin --quiet`로 원격을 받는다. base는 레포 기본 브랜치(`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`)로 하고, stacked PR이면 직전 스택 브랜치, 사용자가 지정했으면 그 값으로 한다. `~/.claude/lib/pr-rules.md`를 Read한다. 본문 구조와 제목·본문 언어는 그 문서를 따른다.

- 미커밋 변경이 있거나, 브랜치가 origin에 없거나 origin보다 앞서 있으면 `/push-commit`으로 먼저 올리라고 권하고 멈춘다.
- 이 브랜치의 PR이 이미 있으면 URL을 알리고, 제목·본문 갱신은 `/push-commit`으로 하라고 권하고 멈춘다.

→ 완료: 작업 디렉토리 절대경로, 브랜치, base, `{owner}/{repo}`가 정해졌고, 브랜치가 origin과 같으며, 이 브랜치의 PR이 없다.

## 2. 받을 리뷰 고르기

PR을 만들기 전에 CodeRabbit 리뷰와 사내 AI 리뷰 봇 리뷰를 받을지 고르게 한다.

- CodeRabbit: 레포의 최근 대화 코멘트 100개 가운데 `coderabbitai[bot]`이 단 것을 센다. 0이면 CodeRabbit 질문을 빼고 이 레포에는 CodeRabbit이 없다고 알린다. 1 이상이면 받기를 추천하고, `git -C {작업 디렉토리} diff origin/{base}...HEAD --shortstat`에 insertions가 없는 PR(삭제만 있는 PR)이면 안 받기를 추천한다.

  ```bash
  gh api "repos/{owner}/{repo}/issues/comments?sort=created&direction=desc&per_page=100" \
    --jq '[.[] | select(.user.login == "coderabbitai[bot]")] | length'
  ```

- 사내 AI 리뷰 봇: `~/.claude/lib/review-bots/index.md`가 있으면 Read하고 그 문서의 봇·추천 절로 선택지와 추천을 정한다. 파일이 없으면 사내 AI 리뷰 봇 질문을 뺀다.

AskUserQuestion 한 번에 묻는 리뷰마다 질문 하나를 넣는다. 질문에 `{owner}/{repo}`와 브랜치, 받으면 리뷰가 끝날 때까지 기다린 뒤 지적에 모두 대응한다는 것을 적고, 추천 선택지를 첫 옵션에 두어 라벨 끝에 `(추천)`을 붙이며, 옵션마다 설명에 근거를 이 PR의 사실(레포·diff·머지 규칙)로 한 줄 쓴다.

→ 완료: 질문에 넣은 리뷰마다 고른 답을 받았고, 뺀 질문은 그 이유를 알렸다.

## 3. PR 생성

제목은 `<type>: [<Linear ID>] <설명>`으로 쓴다. type은 Conventional Commits이고 scope는 생략한다(예: `fix: [ABC-123] 알림 메일 중복 발송 방어`). Linear ID는 브랜치명·커밋 메시지나 Linear API에서 찾고, 못 찾으면 사용자에게 묻는다. "없음"이면 대괄호를 뺀다.

제목·본문 초안을 보여 주며, 구분 줄 위에 넣을 글로 코드만으로 알기 어려운 작업 의도와 장기 설계 관점을 써 달라고 한다. 사용자가 글을 나중에 쓰기로 하면 본문을 구분 줄부터 쓴다. 승인받은 뒤 `gh pr create --draft --assignee @me --base {base}`로 만든다. `{base}`는 1단계에서 정한 base다. reviewer는 비워 두고 사용자가 직접 지정한다.

만든 직후 과정 맥락을 코멘트로 단다(`gh pr comment {번호} --body …`). 남길 맥락이 없는 단발성 PR이면 생략한다.

1. 전체 진행 체크박스 목록: 이번 PR 몫은 `[x]`, 멀티-PR 안에서 이 PR의 위치. 각 항목은 작업 이름으로 쓴다.
2. 후속 작업(다음 PR들).
3. 설계 결정과 대안·근거.

→ 완료: 구분 줄 위에 넣을 글을 받았거나 사용자가 나중에 쓰기로 했고, PR URL을 사용자에게 전달했다.

## 4. 리뷰 요청과 기다리기

2단계에서 받기로 고른 리뷰를 CodeRabbit → 사내 AI 리뷰 봇 순서로 요청하고, 아래대로 기다린다. 고른 리뷰가 없으면 4·5단계를 건너뛴다. Ready 전환은 사용자가 한다.

1. CodeRabbit: 아래 명령을 백그라운드로 실행하고, 끝나면 마지막 줄의 상태로 다음을 정한다. `wait`는 5분마다 확인하며 30분까지 기다린다. 명령 도구의 실행 시간 한도가 30분보다 짧으면 `wait`만 다시 부른다.

   ```bash
   bash ~/.claude/skills/pr-create/coderabbit-review.sh {owner}/{repo} {번호} request \
     && bash ~/.claude/skills/pr-create/coderabbit-review.sh {owner}/{repo} {번호} wait 30
   ```

   - `reviewed {지적 수}`: 사내 AI 리뷰 봇으로 간다.
   - `rate_limited {N}`: N이 30 이하면 N+1분 뒤 위 명령을 한 번 더 백그라운드로 실행한다. N이 `?`이거나 30보다 크거나 두 번째도 `rate_limited`면 다음 리뷰 가능 시각을 적고 사내 AI 리뷰 봇으로 간다.
   - `skipped`: 요약 코멘트의 Review skipped 이유를 적고 사내 AI 리뷰 봇으로 간다.
   - `in_progress`·`draft_skipped`·`paused`·`none`: 30분 안에 끝나지 않았다고 그 상태와 함께 적고 사내 AI 리뷰 봇으로 간다.
2. 사내 AI 리뷰 봇: `~/.claude/lib/review-bots/index.md`의 요청 절대로 2단계에서 고른 봇을 부르고 기다린다.
3. 리뷰마다 한 줄로 알린다: 리뷰어, 상태, 지적 수나 판정, PR이나 Slack 스레드 링크.

→ 완료: 고른 리뷰마다 요청했거나 요청하지 못한 이유를 알렸고, 리뷰마다 상태와 지적 수나 판정을 링크와 함께 알렸다.

## 5. 리뷰 대응

4단계에서 끝난 리뷰의 지적에 모두 대응한다. 끝난 리뷰가 없거나 지적이 0개면 이 단계를 건너뛴다. 편집과 명령은 1단계의 작업 디렉토리에서 한다.

1. 모으기: 끝난 리뷰마다 지적을 모아 번호 목록(리뷰어 · 파일:라인 · 요약 · 답할 곳)으로 보여 준다. 답할 곳은 줄 코멘트 id이고, 줄 코멘트가 아닌 지적은 PR 코멘트다.
   - CodeRabbit: `coderabbitai[bot]`의 줄 코멘트 가운데 답글이 아닌 것과, 리뷰 본문의 Nitpick comments·Outside diff range comments 항목이다.

     ```bash
     gh api repos/{owner}/{repo}/pulls/{번호}/comments --paginate \
       --jq '.[] | select(.user.login == "coderabbitai[bot]" and .in_reply_to_id == null) | {id, path, line: (.line // .original_line), body}'
     gh api repos/{owner}/{repo}/pulls/{번호}/reviews --paginate \
       --jq '.[] | select(.user.login == "coderabbitai[bot]") | .body'
     ```

   - 사내 AI 리뷰 봇: `~/.claude/lib/review-bots/index.md`의 지적 모으기 절대로 모은다.
2. 확인: 지적마다 지금 HEAD의 해당 코드를 읽어 지적이 맞는지와 이미 처리됐는지 본다. 틀렸거나 이미 처리된 지적은 남김으로 두고 근거 파일:라인을 적는다.
3. 반영: `~/.claude/lib/review/apply.md`를 Read하고 남김이 아닌 지적에 수행한다. 반영한 수정은 커밋 전 검증을 통과시킨 뒤 `~/.claude/lib/pr-rules.md`의 커밋 규칙대로 새 커밋으로 남긴다.
4. push: 새 커밋이 있으면 `~/.claude/lib/push.md`의 push 절과 PR 갱신 절을 수행한다. PR 작성자는 `gh pr view {번호} --json author --jq .author.login`으로 정한다. 사용자가 push하기로 했으면 push 출력이 대화에 들어온 뒤 다음으로 간다.
5. 답글: 지적마다 결과를 `~/.claude/lib/pr-rules.md` 리뷰 대응 절대로 답한다. 줄 코멘트는 그 스레드에 답하고, 줄 코멘트가 아닌 지적은 리뷰어마다 PR 코멘트 하나에 모아 답한다. 답글은 파일로 써서 넘긴다.

   ```bash
   gh api -X POST repos/{owner}/{repo}/pulls/{번호}/comments/{코멘트 id}/replies -F body=@{답글 파일}
   gh pr comment {번호} -R {owner}/{repo} --body-file {답글 파일}
   ```

6. 대응표를 알린다: 지적마다 리뷰어 · 파일:라인 · 결과(AUTO-FIXED · 승인 후 수정 · 보류 · 기각 · 남김) · 답글 링크.

→ 완료: 모은 지적마다 결과와 답글이 있고, 반영한 수정이 커밋돼 push됐으며, 대응표를 알렸다.
