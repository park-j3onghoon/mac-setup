---
name: ai-review
description: 다른 사람의 PR에 리뷰를 달아 달라고 할 때, PR을 위험도에 맞춘 리뷰어로 리뷰하고 코드는 고치지 않은 채 결과를 GitHub 리뷰 한 건으로 단다. CRITICAL이 없으면 승인하며 나머지 코멘트를 달고, 있으면 CRITICAL 코멘트만 달아 수정을 요청한다. 올리기 전에 초안을 승인받는다. 내 PR을 고치는 리뷰와 GitHub에 올리지 않는 읽기 전용 리뷰에는 쓰지 않는다.
argument-hint: "[PR URL] [--draft] [--since 커밋]"
---

## 1. 리뷰 준비

코드는 읽기만 하고, PR에는 3단계에서 승인받은 리뷰 한 건만 올린다. 스코프 체크·보안 레벨·이슈 리포트는 3단계 초안으로만 보여 준다.

`~/.claude/lib/review/prepare.md`를 Read하고 수행한다. 인자에 `--since {커밋}`이 있으면 그 커밋을 직전 리뷰의 끝 커밋으로 넘긴다. 단 fetch 뒤 `git -C {클론} merge-base --is-ancestor {커밋} {대상 커밋}`이 0이 아니면(강제 push, 클론에 없는 커밋) 넘기지 않고 전체를 리뷰한다.

→ 완료: 그 문서의 완료 기준을 만족했다.

## 2. 문제 지점 찾기

`~/.claude/lib/review/find-issues.md`를 Read하고 그대로 수행한다. diff는 1단계의 diff 파일, 의도는 PR 제목·본문, 대상은 1단계의 작업 디렉토리다.

→ 완료: 그 문서의 완료 기준을 만족했다.

## 3. GitHub 리뷰 올리기

2단계 이슈 리포트에서 남김을 뺀 발견으로 리뷰 한 건을 만들고, 승인받은 뒤 올린다. 인자에 `--draft`가 있으면 초안만 만드는 리뷰 봇 실행이다. 4번은 올릴 초안(event, 리뷰 본문, 줄 코멘트마다 `file:line`과 본문)을 보여 주기만 하고 묻지 않는다. 5번은 건너뛰고, 6번은 리뷰를 `{스크래치}/review.json`으로 쓰기만 한다(올리지도, URL을 더하지도 않는다).

`--draft`로 만든 세션을 사람이 이어 받아 올리라고 하면 4번 승인부터 이어 간다. 5번에서 headRefOid가 review.json의 `commit_id`와 다르면 그 `commit_id`를 `--since`로 삼아 1단계부터 새 커밋만 리뷰하고, 고친 초안으로 4번 승인을 다시 받는다.

1. event와 달 발견을 정한다.
   - CRITICAL 발견이 있으면 event는 `COMMENT`이고 CRITICAL 발견만 단다.
   - CRITICAL 발견이 없으면 event는 `APPROVE`이고 INFO 발견을 모두 단다.
   - 1단계에서 읽은 PR author의 login이 `gh api user --jq .login`과 같으면 event만 `COMMENT`로 바꾼다.
   - PR 제목·본문이나 문서가 코드와 다르다는 발견은 머지 판단을 바꾸는 것만 단다.
2. 자리를 정한다. 발견의 `file:line`이 가리키는 새 파일 줄이 1단계 diff 파일 hunk의 `+` 줄이나 문맥 줄이면 줄 코멘트로 단다. 줄 범위면 두 끝이 같은 hunk에 들 때 여러 줄 코멘트로 단다. 나머지 발견은 리뷰 본문에 단다.
3. `~/.claude/lib/comment-tone.md`를 Read하고 그 말투로 줄 코멘트와 리뷰 본문을 쓴다. 줄 코멘트마다 문제, 틀어지는 경우(실제 값이 든 입력과 결과, 또는 근거 file:line), 고칠 방법을 담고, INFO 발견은 그 문서의 사소한 지적으로 쓴다. 발견 원문의 압축 용어(불변식, 필드명만 쓴 표현)는 풀어 쓰고, 근거는 리뷰어·도구 이름 대신 코드·데이터 사실로 쓴다.

   리뷰 본문의 첫 줄은 PR author가 나면 `셀프 리뷰했습니다.`, 아니면 CRITICAL 발견을 달 때 그 문서의 승인하지 않는 본문 줄, 달지 않을 때 승인 본문 줄이다.

   ```
   {첫 줄}
   <!-- (선택) CRITICAL 발견을 달고 달지 않은 INFO 발견이 있을 때 -->
   {사소한 것은 수정 뒤 다시 볼 때 남기겠다는 한 문장}
   <!-- (선택) 리뷰 본문에 다는 발견마다 -->

   {줄 코멘트 꼴, 첫 문장에 file:line}
   ```
4. 초안(event, 리뷰 본문, 줄 코멘트마다 `file:line`과 본문)을 보여 주고 AskUserQuestion으로 올릴지 묻는다. 고칠 곳을 답하면 고친 초안으로 다시 묻고, 보류하면 4단계로 건너뛴다.
5. 올리기 직전에 `gh pr view {number} -R {owner}/{repo} --json state,headRefOid`를 읽는다.
   - state가 `OPEN`이 아니면 4단계로 건너뛴다.
   - headRefOid가 1단계의 대상 커밋과 다르면 새 커밋이 올라왔다고 한 줄로 알리고 1단계부터 다시 한다.
6. 리뷰를 `{스크래치}/review.json`으로 쓰고 올린 뒤, 리뷰 URL을 `~/pr_reviews/ai-review-urls.txt` 끝에 한 줄로 더한다. 줄 코멘트는 `path`·`line`·`side: "RIGHT"`·`body`로 쓰고, 여러 줄 코멘트는 `start_line`·`start_side: "RIGHT"`를 더한다.

   ```bash
   # review.json = {"commit_id": "{대상 커밋}", "event": "{event}", "body": "{리뷰 본문}", "comments": [...]}
   gh api -X POST repos/{owner}/{repo}/pulls/{number}/reviews --input {스크래치}/review.json > {스크래치}/posted.json \
     && jq -r .html_url {스크래치}/posted.json | tee -a ~/pr_reviews/ai-review-urls.txt
   ```

   422로 거절되면 `{스크래치}/posted.json`의 메시지를 읽고 고쳐 다시 올린다. 줄을 찾지 못했다는 줄 코멘트는 리뷰 본문으로 옮긴다. event를 거절하면 event를 `COMMENT`로 바꾸고 거절 이유를 4단계 출력 끝에 붙인다. 그 밖의 거절이면 멈추고 응답을 알린다.

→ 완료: 승인받은 리뷰 한 건이 올라가 그 URL이 `~/pr_reviews/ai-review-urls.txt` 끝 줄에 있고, 달 발견이 모두 줄 코멘트나 리뷰 본문에 들었다. 또는 사용자가 보류했거나 state가 `OPEN`이 아니어서 4단계로 건너뛰었다. `--draft`면 달 발견이 모두 든 `{스크래치}/review.json`을 썼다.

## 4. 마무리

`git -C {클론} worktree remove {작업 디렉토리}`로 리뷰 worktree를 지운 뒤, 마지막 출력으로 `{event} · CRITICAL {x} · INFO {y} · {리뷰 URL}` 한 줄만 낸다. x·y는 이슈 리포트에서 남김을 뺀 CRITICAL·INFO 발견 수다. 3단계에서 건너뛰었으면 `올리지 않음 · {사용자 보류 | PR {state}}` 한 줄을 낸다. `--draft`면 `초안 · {event} · CRITICAL {x} · INFO {y}` 한 줄을 낸다.

→ 완료: 리뷰 worktree가 지워졌고 결과 한 줄을 냈다.
