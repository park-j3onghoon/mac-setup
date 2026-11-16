---
name: push-commit
description: 사용자가 push를 요청할 때 변경을 커밋하고 브랜치를 push한 뒤, PR이 있으면 제목·본문을 코드에 맞춘다. 사람 리뷰를 받기 전이면 Claude가 push하고, 받은 뒤면 사용자가 push한다. push 요청이 없는 로컬 커밋에는 쓰지 않는다.
effort: xhigh
---

1. 대상 확정: `~/.claude/lib/push.md`를 Read하고 그 문서 첫머리대로 대상을 정한다. `~/.claude/lib/pr-rules.md`를 Read한다. 커밋·push 전 확인·본문 규칙은 그 문서를 따른다. → 완료: 작업 디렉토리 절대경로, 브랜치, `{owner}/{repo}`, PR 번호와 작성자(PR이 없으면 없음)가 정해졌다.
2. 커밋: 미커밋 변경이 있으면 `~/.claude/lib/pr-rules.md`의 커밋 규칙대로 커밋한다. → 완료: 미커밋 변경은 커밋됐거나 사용자가 빼기로 했다.
3. push: `~/.claude/lib/push.md`의 push 절을 수행한다. → 완료: 그 절의 완료 기준을 만족했다.
4. PR 갱신: `~/.claude/lib/push.md`의 PR 갱신 절을 수행한다. → 완료: push한 커밋 범위와 PR URL(PR이 없으면 없다는 사실)을 사용자에게 전달했다.
