---
name: pr-create
description: push된 브랜치로 Draft PR을 만든다. 크기를 검사하고 제목·본문 초안을 승인받아 만든다.
disable-model-invocation: true
---

## 1. 대상 확정

현재 작업 디렉토리의 브랜치로 PR을 만든다. 그 절대경로를 적어 두고 git 명령은 `git -C {작업 디렉토리}`로 부른다. `~/.claude/lib/pr-rules.md`를 Read한다. 본문 구조와 제목·본문 언어는 그 문서를 따른다.

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

제목은 `<type>: [<Linear ID>] <설명>`으로 쓴다. type은 Conventional Commits이고 scope는 쓰지 않는다(예: `fix: [ABC-123] 알림 메일 중복 발송 방어`). Linear ID는 브랜치명·커밋 메시지나 Linear API에서 찾고, 못 찾으면 사용자에게 카드 번호를 묻는다. "없음"이면 대괄호를 뺀다.

본문은 pr-rules.md의 구조로 쓴다. 레포의 PR 템플릿(`.github/pull_request_template.md`)은 읽지 않는다.

제목·본문 초안을 보여 주고 승인받은 뒤 `gh pr create --draft --assignee @me`로 만든다. reviewer는 비워 두고 사용자가 직접 지정한다.

만든 직후 과정 맥락을 코멘트로 단다(`gh pr comment {번호} --body …`). 남길 맥락이 없는 단발성 PR이면 생략한다.

1. 전체 진행 체크박스 목록: 이번 PR 몫은 `[x]`, 멀티-PR 안에서 이 PR의 위치. 줄 수·케이스 수 같은 수치는 넣지 않는다.
2. 후속 작업(다음 PR들).
3. 설계 결정과 대안·근거.

완료: PR URL과 크기 판정을 사용자에게 전달했다.
