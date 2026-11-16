---
name: implement-review
description: 내 PR이나 구현 커밋을 리뷰해 달라고 할 때 위험도에 맞춘 리뷰어로 리뷰한다. 다시 리뷰할 때는 직전 리뷰 뒤 커밋만 보고, `--full`이면 처음부터 다시 본다. 발견마다 고치거나 하나씩 물어 반영하고, 테스트 통과 후 수정분을 별도 커밋한다. 다른 사람의 PR 리뷰에는 쓰지 않는다.
argument-hint: "[PR URL | 기준 ref, 없으면 계획의 기준 ref 또는 upstream] [--full]"
---

## 1. 리뷰 준비

인자나 대화에 PR 링크가 있으면 `~/.claude/lib/review/prepare.md`를 Read하고 수행한다. 없으면 범위 모드 절을 수행해 현재 디렉토리 레포의 구현 커밋을 리뷰한다. 두 경우 모두 리뷰 worktree는 아래처럼 만든다. 먼저 head가 체크아웃된 트리 `{T}`를 찾는다.

```bash
git -C {클론} worktree list --porcelain    # "branch refs/heads/{head}" 줄이 든 블록의 "worktree" 줄이 {T}다
```

작업 디렉토리나 `teddy/review/{head}` 브랜치가 이미 있으면, `teddy/review/{head}`가 없거나 `git -C {클론} merge-base --is-ancestor teddy/review/{head} {head}`가 참일 때만 지우고 다시 만든다. 작업 디렉토리는 `git -C {클론} worktree remove {작업 디렉토리}`로 지우고, `{T}`가 있으면 `teddy/review/{head}`를 `git -C {T} branch -d teddy/review/{head}`로 지운다. 그 밖의 경우나 remove나 `branch -d`가 거절하면 사용자에게 묻는다.

- `{T}`가 있으면: `git -C {T} status --short`에 나온 미커밋 변경과 untracked 파일은 리뷰에서 빼고 결과에 한 줄로 적는다(다른 세션의 미커밋이 섞일 수 있다). 그다음 `git -C {클론} worktree add -b teddy/review/{head} {작업 디렉토리} {head}`로 리뷰 브랜치를 올린다.
- `{T}`가 없으면: `git -C {클론} worktree add {작업 디렉토리} {head}`로 head를 바로 올린다.

PR 모드에서는 worktree를 만든 뒤 받아 온 원격 head와 작업 디렉토리의 HEAD를 비교한다. 원격 head가 앞서 있으면 작업 디렉토리에서 `git merge --ff-only origin/{head}`로 갱신하고, 로컬이 앞서 있으면 로컬 구현 커밋을 보존한다. 서로 갈라졌거나 ff가 실패하면 대상 커밋을 사용자에게 확인한다. 이 확인을 마친 뒤 아래 증분 판정을 하고 diff를 생성한다.

증분 판정: 인자에 `--full`이 있거나 사용자가 전체 리뷰를 요청했으면 리뷰 기록과 상관없이 전체 diff를 만든다. 그 밖에는 연결된 계획 파일(`~/.claude/lib/coding/load-rules.md` 5번이 찾는 `plan.md`)과 같은 디렉토리의 `review-log.md`에서 이 head의 마지막 리뷰 항목을 찾는다.

- 그 항목의 끝 커밋이 작업 디렉토리 HEAD의 조상이고 둘이 다르면 증분 리뷰다. diff를 만들 때 끝 커밋을 넘겨 `~/.claude/lib/review/diff.md`의 증분 블록으로 만든다.
- 끝 커밋이 HEAD와 같거나 증분 커밋 목록이 비면, 직전 리뷰 뒤 새 커밋이 없고 처음부터 다시 보려면 `--full`을 붙이라고 알린다. `git -C {클론} worktree remove {작업 디렉토리}`로 리뷰 worktree를 지우고, `{T}`가 있으면 `git -C {T} branch -d teddy/review/{head}`로 리뷰 브랜치도 지운 뒤 마친다.
- 항목이 없거나, 끝 커밋이 HEAD의 조상이 아니면 전체 diff를 만든다.

`/guard`가 활성화돼 있으면 리뷰 worktree와 이번 작업의 계획 문서 디렉토리를 편집 범위에 포함한다.

→ 완료: prepare.md나 범위 모드 절의 완료 기준을 만족했고, `{T}` 유무와 전체·증분 여부, 모든 리뷰어에게 전달할 기준 커밋·대상 커밋·diff 파일이 정해졌다.

## 2. 문제 지점 찾기

`~/.claude/lib/review/find-issues.md`를 Read하고 그대로 수행한다. diff는 1단계의 diff 파일, 의도는 그 문서의 최신 승인·PR·커밋 기준과 출처이고 증분 리뷰면 증분 커밋 메시지와 최신 승인이다. 대상은 1단계의 작업 디렉토리다.

`~/.claude/lib/review/find-issues.md` 1절의 Risk가 HIGH이면, 서브에이전트 병렬 리뷰 절의 리뷰어와 같은 배치에서 Skill 도구로 `code-review`를 부른다. 인자는 `max` 뒤에 1단계의 diff 파일 경로 전부·기준 커밋·대상 커밋·작업 디렉토리 절대경로와 적재한 규칙·계획·승인 출처를 붙인다. PR 링크는 맥락으로만 전달하고, 리뷰 범위는 같은 diff 파일을 읽게 한다. 도구가 ref만 받으면 `{기준 커밋}..{대상 커밋}`을 쓰고 전달한 diff와 같은 범위인지 확인한다. 결과 통합 절은 code-review 결과가 돌아온 뒤 수행하고, 그 발견을 다른 리뷰어의 발견과 합쳐 출처를 `code-review`로 적는다.

→ 완료: 그 문서의 완료 기준을 만족했고, code-review를 불렀으면 그 발견도 이슈 리포트에 합쳐졌다.

## 3. 수정 적용

`~/.claude/lib/review/apply.md`를 Read하고 2단계 발견에 수행한다. 편집과 명령은 1단계의 작업 디렉토리에서 한다.

→ 완료: 그 문서의 완료 기준을 만족했다.

## 4. 마감

```
Review: N 이슈 (CRITICAL X · INFO Y) · 범위: 전체 또는 증분 {기준 커밋}..{대상 커밋}
Auto-fixed: Z · 승인 후 수정: W · 남은 항목: V (보류 · 기각 · 남김)
리뷰어별: 코드 A · 언어 B · 관점 C · 보안 S · code-review R · 교차 리뷰 D · 교차 적대 검증 E
```

반영한 수정이 있으면 `~/.claude/lib/coding/tests.md`를 Read하고 버그 수정은 red/green, 구조 변경은 Refactoring equivalence 기준으로 검증한다. 유지된 동작·승인된 변경·미확인 범위를 구분해 보고한다. 최종 diff와 최신 의도 및 PR 제목·본문(범위 모드는 해당 문서)을 다시 대조하고, 불일치는 보고하거나 권한이 있을 때만 사용자 작성 부분을 보존해 수정한다.

반영한 수정이 있으면 `~/.claude/lib/pr-rules.md`를 Read하고 커밋 전 검증을 통과할 때까지 수정한 뒤, 원래 구현 커밋 다음에 별도 새 커밋으로 남긴다.

사용자가 커밋을 미뤘거나 커밋 전 검증을 끝내지 못했으면 ff 반영과 정리를 건너뛰고 리뷰 worktree·브랜치를 보존하며 경로와 남은 작업을 알린다.

1단계에서 `{T}`가 있었고, 수정이 없거나 반영한 수정을 모두 커밋했을 때만 리뷰 브랜치를 head에 ff로 반영하고 리뷰 worktree를 지운다. ff가 실패하면 멈추고 묻는다.

```bash
git -C {T} merge --ff-only teddy/review/{head}
git -C {클론} worktree remove {작업 디렉토리}
git -C {T} branch -d teddy/review/{head}
```

커밋을 마쳤고 `{T}`가 없으면 head에서 커밋한 리뷰 worktree를 그대로 두고 그 경로를 알린다.

리뷰 기록을 연결된 계획 파일과 같은 디렉토리의 `review-log.md` 끝에 더한다. 끝 커밋은 리뷰 수정 커밋을 head에 반영했으면 그 커밋, 아니면 대상 커밋이다. 계획 파일을 찾지 못했으면 기록할 곳이 없다고 알린다.

```
## {YYYY-MM-DD} {head} {전체|증분} {기준 커밋}..{대상 커밋}
끝 커밋: {끝 커밋}
- {보류|기각|남김} · {파일:라인} · {발견 요약} · {이유}
```

→ 완료: 요약과 검증 결과를 냈고, 검증을 통과한 수정 커밋이 head에 들어갔거나(`{T}`가 있었으면 ff 반영과 리뷰 worktree 정리까지) 사용자가 커밋을 미뤘다. `review-log.md`에 이번 리뷰 항목을 더했거나, 계획 파일이 없다고 알렸다.

## 범위 모드

1. 현재 작업 트리에서 `git rev-parse --path-format=absolute --git-common-dir`로 얻은 공용 Git 디렉토리의 부모를 메인 클론 `{클론}`으로 정한다. `{repo}`는 그 클론의 디렉토리 이름, `{head}`는 현재 작업 트리의 `git branch --show-current`다.
2. `{base_ref}`는 인자로 받은 기준 ref, 대화나 연결된 계획에 기록한 기준 ref, 현재 작업 트리의 `git rev-parse --symbolic-full-name '@{upstream}'` 순으로 고른다. 셋 다 없으면 기준 브랜치나 커밋을 묻는다. 원격 ref를 쓰면 메인 클론에서 해당 원격을 fetch한 뒤 그 ref를 확정한다. `{base_ref}`에는 원격 접두사를 다시 붙이지 않는다.
3. worktree를 만들기 전에 `git -C {클론} log --oneline {base_ref}..{head}`로 리뷰할 커밋이 있는지 확인한다. 비면 지정한 범위에 리뷰할 커밋이 없다고 알리고 마친다.
4. 작업 디렉토리는 `{클론}/.claude/worktrees/review-{head}`이고, 1단계의 worktree 지시로 만든다.
5. `{스크래치}`는 이번 리뷰의 임시 디렉토리다. head의 `/`를 `-`로 바꾼 이름을 `{범위명}`으로, `{diff 파일}`을 `{스크래치}/{repo}-{범위명}.diff`로 정한다. 1단계의 증분 판정을 한 뒤 `~/.claude/lib/review/diff.md`를 Read하고 메인 클론·작업 디렉토리·base_ref(증분이면 끝 커밋도)로 diff를 한 번 생성한다.

→ 완료: base_ref·head·작업 디렉토리·기준 커밋·대상 커밋·커밋 목록·diff 파일 경로와 `--stat`의 파일 수가 정해졌다.
