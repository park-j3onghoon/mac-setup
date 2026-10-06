# 리뷰 준비

## 1. PR 링크

인자나 대화에 PR 링크(`https://github.com/{owner}/{repo}/pull/{number}`)가 없으면 "리뷰할 PR 링크를 보내 주세요."라고 묻고 기다린다. `{repo} {number}` 형태로 받았으면 그 레포 클론에서 `gh pr view {number} --json url`로 링크를 확정한다.

```bash
gh pr view {링크} --json number,title,body,author,baseRefName,headRefName,additions,deletions
```

→ 완료: PR 번호·제목·본문·author·base/head를 읽었다.

## 2. 클론

클론은 `~/{owner 소문자}/{repo}`다. 없으면 `gh repo clone {owner}/{repo} ~/{owner 소문자}/{repo}`로 받는다. 그다음 base와 head를 받아 온다.

```bash
git -C {클론} fetch origin {base} {head} --quiet
```

→ 완료: 클론이 있고 base와 head를 받아 왔다.

## 3. 리뷰 worktree

경로는 `{클론}/.claude/worktrees/review-{number}`이고, 이 경로가 작업 디렉토리다. 만드는 명령은 호출한 쪽이 정한다.

→ 완료: 작업 디렉토리 절대경로가 정해졌고 그 경로에 리뷰 worktree가 있다.

## 4. diff

diff는 PR 화면과 같은 범위, 곧 head가 base에서 갈라진 지점부터 HEAD까지다.

```bash
MB=$(git -C {작업 디렉토리} merge-base origin/{base} HEAD)
git -C {작업 디렉토리} diff $MB --stat
git -C {작업 디렉토리} log --oneline $MB..HEAD
git -C {작업 디렉토리} diff $MB > {스크래치}/{repo}-{number}.diff
```

`{스크래치}`는 이 세션의 임시 디렉토리다. diff가 1000줄을 넘으면 파일별로 나눠 저장한다.

→ 완료: diff 파일 경로와 `--stat`의 파일 수가 정해졌다.
