## 1. PR 링크

인자나 대화에 PR 링크(`https://github.com/{owner}/{repo}/pull/{number}`)가 없으면 "리뷰할 PR 링크를 보내 주세요."라고 묻고 기다린다. `{repo} {number}` 형태로 받았으면 그 레포 클론에서 `gh pr view {number} --json url`로 링크를 확정한다.

```bash
gh pr view {링크} --json number,title,body,author,baseRefName,headRefName,additions,deletions
```

→ 완료: PR 번호·제목·본문·author·base/head를 읽었다.

## 2. 클론

클론은 `~/{owner 소문자}/{repo}`의 메인 클론이다. 없으면 `gh repo clone {owner}/{repo} ~/{owner 소문자}/{repo}`로 받는다. 그다음 메인 클론에서 원격 ref를 받아 온다.

```bash
git -C {클론} fetch origin --quiet
```

`{base_ref}`는 `refs/remotes/origin/{base}`로 정한다. 로컬 head의 구현 커밋은 보존하고, head가 로컬에 없으면 받아 온 원격 head에서 준비한다.

→ 완료: 메인 클론의 원격 ref가 최신화됐고 base_ref와 리뷰할 head가 정해졌다.

## 3. 리뷰 worktree

경로는 `{클론}/.claude/worktrees/review-{number}`이고, 이 경로가 작업 디렉토리다. 만드는 명령은 호출한 쪽이 정한다.

→ 완료: 작업 디렉토리 절대경로가 정해졌고 그 경로에 리뷰 worktree가 있다.

## 4. diff

`{스크래치}`는 이번 리뷰의 임시 디렉토리이고, `{diff 파일}`은 `{스크래치}/{repo}-{number}.diff`다. `~/.claude/lib/review/diff.md`를 Read하고 메인 클론·작업 디렉토리·base_ref로 diff를 한 번 생성한다.

→ 완료: 기준 커밋·대상 커밋·커밋 목록·diff 파일 경로와 `--stat`의 파일 수가 정해졌다.
