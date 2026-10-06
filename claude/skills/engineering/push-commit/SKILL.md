---
name: push-commit
description: 변경을 커밋하고 브랜치를 push한 뒤, PR이 있으면 제목·본문을 코드에 맞춘다. 사람 리뷰를 받기 전이면 Claude가 push하고, 받은 뒤면 사용자가 push한다.
disable-model-invocation: true
---

## 1. 대상 확정

현재 작업 디렉토리의 브랜치를 올린다. 그 절대경로를 적어 두고 git 명령은 `git -C {작업 디렉토리}`로 부른다. `~/.claude/lib/pr-rules.md`를 Read한다. 커밋·push 전 확인·본문 규칙은 그 문서를 따른다.

```bash
git -C {작업 디렉토리} branch --show-current
git -C {작업 디렉토리} status --short --branch
gh repo view --json nameWithOwner -q .nameWithOwner
gh pr list --head {브랜치} --json number,url,author
```

→ 완료: 작업 디렉토리 절대경로, 브랜치, `{owner}/{repo}`, PR 번호와 작성자(PR이 없으면 없음)가 정해졌다.

## 2. 커밋

미커밋 변경이 있으면 `~/.claude/lib/pr-rules.md`의 커밋 규칙대로 커밋한다.

→ 완료: 미커밋 변경은 커밋됐거나 사용자가 빼기로 했다.

## 3. push

`~/.claude/lib/pr-rules.md`의 push 전 확인(테스트·빌드)을 먼저 한다. 그다음 사람 리뷰를 받은 PR인지 본다. 사람 리뷰는 PR 리뷰 가운데 계정 `type`이 `User`이고 PR 작성자가 아닌 리뷰다.

```bash
gh api repos/{owner}/{repo}/pulls/{번호}/reviews --paginate \
  --jq '.[] | select(.user.type == "User" and .user.login != "{작성자}") | .user.login' | sort -u
```

- PR이 없거나 사람 리뷰가 없으면 직접 push한다. origin에 없는 브랜치면 `push -u origin {브랜치}`로 올린다.

  ```bash
  git -C {작업 디렉토리} push
  ```

- 사람 리뷰가 있으면 리뷰어 이름과 명령을 보여 주고, 사용자가 `!` 접두사로 실행하기를 기다린다.

  ```
  ! git -C {작업 디렉토리 절대경로} push
  ```

push한 브랜치를 base로 쓰는 열린 PR이 있으면(`gh pr list --base {브랜치} --json number,headRefName`) 그 목록을 보여 주고, `~/.claude/lib/pr-rules.md`의 stacked PR 절을 따라 전파할지 묻는다. 전파한 브랜치도 이 단계 규칙대로 push한다.

→ 완료: push 출력이 대화에 들어왔고 실패가 없으며, base로 쓰는 열린 PR이 있었으면 사용자가 전파 여부를 답했고 전파한 브랜치도 push됐다.

## 4. PR 갱신

PR이 없으면 이 단계를 건너뛰고 PR이 없다고 알린다.

PR이 있으면 `gh pr view {번호} --json title,body`로 지금 제목·본문을 읽고, 코드와 어긋난 곳(파일 추가·삭제·이동, 바뀐 동작)을 고친 안을 보여 준 뒤 승인받아 `gh pr edit`로 바꾼다.

→ 완료: push한 커밋 범위와 PR URL(PR이 없으면 없다는 사실)을 사용자에게 전달했다.
