---
name: pr-create
description: 브랜치를 PR로 올린다. 크기를 검사하고 push 명령을 낸 뒤, PR이 없으면 Draft로 만들고 있으면 제목·본문을 코드에 맞게 고친다.
disable-model-invocation: true
---

# /pr-create

## 1. 대상 확정

현재 작업 디렉토리의 브랜치를 올린다. 그 절대경로를 적어 두고 git 명령은 `git -C {작업 디렉토리}`로 부른다. `~/.claude/lib/pr-rules.md`가 있으면 Read한다. 커밋·제목·본문·코멘트 규칙은 그 문서를 따른다.

```bash
git -C {작업 디렉토리} branch --show-current
git -C {작업 디렉토리} status --short
gh pr list --head {브랜치} --json number,url,isDraft,baseRefName
```

미커밋 변경이 있으면 파일 목록과 커밋 메시지 안을 보여 주고, 승인받은 파일만 새 커밋으로 남긴다.

완료: 브랜치, 작업 디렉토리 절대경로, 기존 PR 유무가 정해졌고, 미커밋 변경은 커밋됐거나 사용자가 빼기로 했다.

## 2. 크기 검사

`~/.claude/skills/pr-create/size-check.md`를 Read하고 판정까지 수행한다.

완료: 판정이 나왔고, FAIL이면 분할 방법이 합의됐다.

## 3. push

push는 사용자가 `!` 접두사로 직접 실행한다. 명령을 내고 기다린다. origin에 없는 브랜치면 `push -u origin {브랜치}`로 낸다.

```
! git -C {작업 디렉토리 절대경로} push
```

완료: push 출력이 대화에 들어왔고 실패가 없다.

## 4. PR 생성 또는 갱신

본문에는 이 PR이 왜 필요하고 무엇이 어떻게 바뀌는지 쓴다. 레포에 PR 템플릿(`.github/pull_request_template.md`)이 있으면 그 절 구조를 쓰고, pr-rules.md가 정한 본문 항목을 그 안에 채운다.

- PR이 없으면: 제목·본문 초안을 보여 주고 승인받은 뒤 `gh pr create --draft`로 만든다.
- PR이 있으면: `gh pr view {번호} --json title,body`로 지금 제목·본문을 읽고, 코드와 어긋난 곳(파일 추가·삭제·이동, 바뀐 동작)을 고친 안을 보여 준 뒤 승인받아 `gh pr edit`로 바꾼다.

pr-rules.md에 코멘트 규칙이 있으면 그대로 코멘트를 단다.

완료: PR URL과 크기 판정을 사용자에게 전달했다. 리뷰 전이면 다음은 `/implement-review`다.
