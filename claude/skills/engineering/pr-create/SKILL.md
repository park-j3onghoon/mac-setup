---
name: pr-create
description: push된 브랜치로 Draft PR을 만든다. 크기를 검사하고 제목·본문 초안을 승인받아 만든다.
disable-model-invocation: true
---

# /pr-create

## 1. 대상 확정

현재 작업 디렉토리의 브랜치로 PR을 만든다. 그 절대경로를 적어 두고 git 명령은 `git -C {작업 디렉토리}`로 부른다. `~/.claude/lib/pr-rules.md`가 있으면 Read한다. 제목·본문·코멘트 규칙은 그 문서를 따른다.

```bash
git -C {작업 디렉토리} fetch origin --quiet
git -C {작업 디렉토리} status --short --branch
gh pr list --head {브랜치} --json number,url
```

- 미커밋 변경이 있거나, 브랜치가 origin에 없거나 origin보다 앞서 있으면 `/push-commit`으로 먼저 올리라고 권하고 멈춘다.
- 이 브랜치의 PR이 이미 있으면 URL을 알리고 멈춘다. 제목·본문 갱신은 `/push-commit`이 맡는다.

완료: 작업 디렉토리 절대경로와 브랜치가 정해졌고, 브랜치가 origin과 같으며, 이 브랜치의 PR이 없다.

## 2. 크기 검사

`~/.claude/skills/pr-create/size-check.md`를 Read하고 판정까지 수행한다.

완료: 판정이 나왔고, FAIL이면 분할 방법이 합의됐다.

## 3. PR 생성

본문은 pr-rules.md가 있으면 그 구조로, 없으면 이 PR이 왜 필요하고 무엇이 어떻게 바뀌는지 쓴다. 레포의 PR 템플릿(`.github/pull_request_template.md`)은 읽지 않는다.

제목·본문 초안을 보여 주고 승인받은 뒤 `gh pr create --draft`로 만든다. pr-rules.md에 코멘트 규칙이 있으면 그대로 코멘트를 단다.

완료: PR URL과 크기 판정을 사용자에게 전달했다.
