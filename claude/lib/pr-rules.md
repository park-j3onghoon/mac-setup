# PR·브랜치·커밋 규칙

PR 본문·코멘트·답글은 `~/.claude/lib/document-tone.md`를 Read하고 그 어투로 쓴다.

## 브랜치·커밋

- 새 브랜치는 `teddy/` prefix로 만든다(예: `teddy/abc-123-fix-duplicate-mail`).
- commit·merge 전 `git branch --show-current`로 현재 브랜치를 확인한다.
- 커밋은 언제나 새 커밋이다. amend·reset·rebase·squash로 history를 고치지 않는다. 이미 커밋한 파일을 되돌릴 때도 삭제를 새 커밋으로 남긴다.
- 커밋 메시지·PR 제목·본문은 한글로 쓴다.
- 커밋 전에 파일 목록과 커밋 메시지 안을 보여 주고, 승인받은 파일만 새 커밋으로 남긴다.
- push 전에 변경한 모듈의 테스트를 돌린다. 파일 이동·import 변경 뒤에는 빌드 명령도 돌린다.

## PR 본문

리뷰어가 변경을 이해하는 데 필요한 것만 남긴다.

- `## As-Is` → `## To-Be` → Background(Linear/RFC/PRD 링크) → 호환성·영향 → Test plan. As-Is와 To-Be는 각각 3줄 이내로 쓴다.
- 레포의 PR 템플릿(`.github/pull_request_template.md`)이 있어도 이 구조로 쓴다.
- 진행 상황·설계 논의·중간 과정·멀티-PR 맥락은 코멘트로 쓴다.

## 리뷰 대응

- 답글에는 커밋 해시·로봇 포맷을 넣지 않는다.
- 지적이 의도한 설계를 건드리면, 같은 지적을 한 리뷰어가 몇 명이든 의도를 설명하는 답글로 갈음할 수 있다. 의도가 아니면 반영한다.
- 이전 라운드에 의도라고 답한 이슈를 다시 지적받으면 재검토·반영한다.
- 반영 전 `git diff`로 PR 범위를 확인하고 범위 안 변경만 반영한다.
- PRD·디자인 근거 없는 방어 로직(취소 확인 모달 등)은 빼는 쪽이 기본. 되돌릴 수 없는 유저 손실을 막을 때만 넣는다.

## stacked PR

- base 브랜치에 push한 뒤 의존 브랜치에 merge로 전파한다. conflict는 즉시 해결한다.
- 각 PR 브랜치는 자기 base 대비 변경만 담는다. 다른 PR 브랜치의 변경을 가져와야 하면 사용자 확인 후에 merge한다.
- 압축이 필요하면 force push 없이 끝단 PR의 base를 재지정하고(`gh pr edit --base`) 흡수된 PR을 close한다.
- merge conflict는 어느 쪽이 최신인지 판단해 해결한다. base(master)에 이미 머지·검증된 코드가 최신이면 base 기준으로 해결한다.
