# 리뷰 준비

PR 링크 하나에서 리뷰 입력을 만든다: PR 정보, diff 파일, 수정할 작업 디렉토리. 모드는 호출한 쪽이 정한다. 수정 모드는 고칠 작업 트리를 쓰고, 읽기 모드는 체크아웃 없이 원격 브랜치만 본다.

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

수정 모드: head 브랜치가 체크아웃된 작업 트리를 찾아 그 절대경로를 작업 디렉토리로 쓴다. 그 트리의 미커밋 변경도 리뷰 대상이다.

```bash
git -C {클론} worktree list --porcelain    # "branch refs/heads/{head}" 줄이 든 블록의 "worktree" 줄이 경로다
```

없으면 `git -C {클론} worktree add {클론}/.claude/worktrees/{head의 마지막 경로 조각} {head}`로 새로 만든다. 다른 브랜치가 체크아웃된 트리(다른 세션이 쓰는 중일 수 있다)에서 `git checkout`으로 브랜치를 바꾸지 않는다.

읽기 모드: 작업 트리를 만들지 않는다.

## 3. diff

브랜치가 base에서 갈라진 지점(merge-base)부터 본다. `git diff origin/{base}`처럼 base 끝과 바로 비교하면 갈라진 뒤 base에 들어온 커밋이 되돌림처럼 섞인다.

```bash
# 수정 모드: 커밋과 미커밋 변경을 함께 본다
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

수정 모드의 `git diff`는 추적되지 않는 새 파일을 보여 주지 않는다. `git -C {작업 디렉토리} status --short`의 `??` 파일 중 이 PR에 들어갈 것이 있으면 사용자에게 알리고 리뷰 대상에 넣는다.

→ 완료: PR 번호·제목·본문·author·base/head, diff 파일 경로, `--stat`의 파일 수가 정해졌다. 수정 모드면 작업 디렉토리 절대경로도 정해졌다.
