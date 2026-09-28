# 리뷰 준비

PR 링크 하나에서 리뷰 입력을 만든다: PR 정보, diff 파일, 수정할 작업 디렉토리. 모드는 호출한 쪽이 정한다. 수정 모드는 리뷰용 worktree를 새로 만들어 거기서 고치고, 읽기 모드는 체크아웃 없이 원격 브랜치만 본다.

## 1. PR 링크

인자나 대화에 PR 링크(`https://github.com/{owner}/{repo}/pull/{number}`)가 없으면 "리뷰할 PR 링크를 보내 주세요."라고 묻고 기다린다. `{repo} {번호}` 형태로 받았으면 그 레포 클론에서 `gh pr view {번호} --json url`로 링크를 확정한다.

```bash
gh pr view {링크} --json number,title,body,author,baseRefName,headRefName,additions,deletions
```

제목·본문이 이 PR의 의도다.

## 2. 레포와 작업 위치

로컬 클론을 찾는다(`ls -d ~/*/{repo}/.git`). 없거나 둘 이상이면 사용자에게 묻는다. 이후 git 명령은 `cd` 없이 `git -C {경로}`로 부른다.

```bash
git -C {클론} fetch origin {base} {head} --quiet
```

수정 모드: 리뷰용 worktree를 새로 만들어 작업 디렉토리로 쓴다. 먼저 head가 체크아웃된 트리 `{T}`를 찾는다.

```bash
git -C {클론} worktree list --porcelain    # "branch refs/heads/{head}" 줄이 든 블록의 "worktree" 줄이 {T}다
```

- `{T}`가 있으면: `git -C {T} status --short`에 미커밋 변경이나 untracked 파일이 있을 때 목록을 보여 주고, 먼저 커밋해 리뷰에 넣을지 빼고 진행할지 묻는다. 그다음 `git -C {클론} worktree add -b review/{head} {클론}/.claude/worktrees/review-{number} {head}`로 리뷰 브랜치를 올린다.
- `{T}`가 없으면: `git -C {클론} worktree add {클론}/.claude/worktrees/review-{number} {head}`로 head를 바로 올린다.

`review/{head}` 브랜치가 이미 있으면 `git -C {클론} merge-base --is-ancestor review/{head} {head}`가 참일 때만 그 worktree와 브랜치를 지우고 다시 만든다. 거짓이면 사용자에게 묻는다.

읽기 모드: 작업 트리를 만들지 않는다.

## 3. diff

diff는 merge-base부터 본다.

```bash
# 수정 모드: 리뷰 worktree에서 본다
MB=$(git -C {작업 디렉토리} merge-base origin/{base} HEAD)
git -C {작업 디렉토리} diff $MB --stat
git -C {작업 디렉토리} log --oneline $MB..HEAD
git -C {작업 디렉토리} diff $MB > {스크래치}/{repo}-{number}.diff

# 읽기 모드: 원격 브랜치끼리 본다
git -C {클론} diff origin/{base}...origin/{head} --stat
git -C {클론} log --oneline origin/{base}..origin/{head}
git -C {클론} diff origin/{base}...origin/{head} > {스크래치}/{repo}-{number}.diff
```

`{스크래치}`는 이 세션의 임시 디렉토리다. diff가 1000줄을 넘으면 파일별로 나눠 저장한다.

→ 완료: PR 번호·제목·본문·author·base/head, diff 파일 경로, `--stat`의 파일 수가 정해졌다. 수정 모드면 리뷰 worktree 절대경로(작업 디렉토리)와 `{T}` 유무도 정해졌다.
