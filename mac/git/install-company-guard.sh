#!/usr/bin/env bash
# 개인 repo에만 company-guard를 git 설정 훅(hook.<이름>.command)으로 건다. install.sh가 부르고,
# 혼자 돌려도 된다. 여러 번 돌려도 결과가 같다.
# 개인 repo = 이 repo(mac-setup)와 같은 GitHub 계정의 원격이 있거나 ~/git 아래에 있는 repo.
# 설정 훅은 repo 자체 훅(.git/hooks, core.hooksPath)과 함께 돌아서 그 훅을 덮지 않는다.
set -eu

REPO_DIR=$(cd "$(dirname "$0")/../.." && pwd -P)
GUARD="$REPO_DIR/mac/git/company-guard"
INCLUDE="$HOME/.config/git/personal.gitconfig"
owner=$(git -C "$REPO_DIR" remote get-url origin | sed -E 's#^(git@github\.com:|https://github\.com/)([^/]+)/.*$#\2#')
case "$owner" in
  ""|*/*|*:*) echo "[error] GitHub 계정을 origin에서 읽지 못함: $owner" >&2; exit 1 ;;
esac

mkdir -p "$(dirname "$INCLUDE")"
cat > "$INCLUDE" <<CONFIG
# install-company-guard.sh가 만든다. ~/.gitconfig의 includeIf로 개인 repo에만 들어간다.
# 「event =」로 목록을 먼저 비워서, 조건 두 개가 함께 맞아 두 번 들어와도 한 번만 돈다.
[hook "company-guard-commit"]
	event =
	event = pre-commit
	command = $GUARD pre-commit
[hook "company-guard-message"]
	event =
	event = commit-msg
	command = $GUARD commit-msg
[hook "company-guard-push"]
	event =
	event = pre-push
	command = $GUARD pre-push
CONFIG

for condition in "hasconfig:remote.*.url:git@github.com:$owner/**" \
                 "hasconfig:remote.*.url:https://github.com/$owner/**" \
                 "gitdir:~/git/"; do
  git config --global "includeIf.$condition.path" "$INCLUDE"
done
if [ ! -s "$REPO_DIR/private/git/company-terms" ]; then
  echo "[warn] private/git/company-terms가 없다: 목록을 채울 때까지 개인 repo의 커밋과 push가 거부된다" >&2
fi
