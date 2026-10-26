입력은 메인 클론 `{클론}`·리뷰 worktree `{작업 디렉토리}`·기준 ref `{base_ref}`·diff 저장 경로다. `{base_ref}`는 원격 접두사까지 포함한 ref나 커밋 해시로 받고 그대로 사용한다.

원격 ref 최신화는 메인 클론에서 fetch로 마친다. 작업 파일이나 체크아웃된 브랜치를 바꾸는 pull·reset 대신 Git 객체와 ref를 갱신한다. 리뷰할 worktree의 HEAD를 대상 커밋으로, 기준 ref와의 merge-base를 기준 커밋으로 고정한다.

```bash
REVIEW_HEAD_SHA=$(git -C "{작업 디렉토리}" rev-parse HEAD)
REVIEW_BASE_SHA=$(git -C "{클론}" merge-base "{base_ref}" "$REVIEW_HEAD_SHA")
git -C "{클론}" log --format='%h %s%n%n%b' "$REVIEW_BASE_SHA..$REVIEW_HEAD_SHA"
git -C "{클론}" diff --no-ext-diff --no-textconv --stat "$REVIEW_BASE_SHA" "$REVIEW_HEAD_SHA"
git -C "{클론}" diff --no-ext-diff --no-textconv "$REVIEW_BASE_SHA" "$REVIEW_HEAD_SHA" > "{diff 파일}"
```

`{기준 커밋}`은 `REVIEW_BASE_SHA`, `{대상 커밋}`은 `REVIEW_HEAD_SHA`다. 모든 명령이 성공했는지 확인하고 두 해시·커밋 목록·diff 파일 경로·`--stat`의 파일 수를 기록한다.

모든 리뷰어와 다른 AI에 같은 diff 파일과 두 해시를 전달한다. ref나 PR 링크에서 diff를 다시 계산하는 대신 이 파일을 읽게 한다. diff가 1000줄을 넘으면 파일별 사본을 나누고 모든 리뷰어에게 같은 파일 목록을 준다. 리뷰 중에는 이 diff 파일을 유지하고, 수정 후 최종 확인용 diff는 별도 파일로 만든다.

→ 완료: 메인 클론에서 고정한 두 커밋의 diff가 저장됐고, 모든 리뷰어가 같은 diff 파일과 대상 커밋의 코드를 본다.
