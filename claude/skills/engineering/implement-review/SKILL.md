---
name: implement-review
description: 내 PR이나 구현 커밋을 같은 diff로 병렬 리뷰한다. 발견마다 고치거나 하나씩 물어 반영하고, 테스트 통과 후 수정분을 별도 커밋한다.
disable-model-invocation: true
argument-hint: "[PR URL | 기준 ref, 없으면 계획의 기준 ref 또는 upstream]"
---

## 1. 리뷰 준비

인자나 대화에 PR 링크가 있으면 `~/.claude/lib/review/prepare.md`를 Read하고 수행한다. 없으면 범위 모드 절을 수행해 현재 디렉토리 레포의 구현 커밋을 리뷰한다. 두 경우 모두 리뷰 worktree는 아래처럼 만든다. 먼저 head가 체크아웃된 트리 `{T}`를 찾는다.

```bash
git -C {클론} worktree list --porcelain    # "branch refs/heads/{head}" 줄이 든 블록의 "worktree" 줄이 {T}다
```

작업 디렉토리나 `teddy/review/{head}` 브랜치가 이미 있으면, `teddy/review/{head}`가 없거나 `git -C {클론} merge-base --is-ancestor teddy/review/{head} {head}`가 참일 때만 지우고 다시 만든다. 작업 디렉토리는 `git -C {클론} worktree remove {작업 디렉토리}`로 지우고, `{T}`가 있으면 `teddy/review/{head}`를 `git -C {T} branch -d teddy/review/{head}`로 지운다. 그 밖의 경우나 remove나 `branch -d`가 거절하면 사용자에게 묻는다.

- `{T}`가 있으면: `git -C {T} status --short`에 미커밋 변경이나 untracked 파일이 있을 때 목록을 보여 주고, 먼저 커밋해 리뷰에 넣을지 빼고 진행할지 묻는다. 먼저 커밋하면 `~/.claude/lib/pr-rules.md`를 Read하고 커밋 전 검증과 커밋 규칙을 따른다. 그다음 `git -C {클론} worktree add -b teddy/review/{head} {작업 디렉토리} {head}`로 리뷰 브랜치를 올린다.
- `{T}`가 없으면: `git -C {클론} worktree add {작업 디렉토리} {head}`로 head를 바로 올린다.

PR 모드에서는 worktree를 만든 뒤 받아 온 원격 head와 작업 디렉토리의 HEAD를 비교한다. 원격 head가 앞서 있으면 작업 디렉토리에서 `git merge --ff-only origin/{head}`로 갱신하고, 로컬이 앞서 있으면 로컬 구현 커밋을 보존한다. 서로 갈라졌거나 ff가 실패하면 대상 커밋을 사용자에게 확인한다. 이 확인을 마친 뒤 diff를 생성한다.

`/guard`가 활성화돼 있으면 리뷰 worktree와 이번 작업의 계획 문서 디렉토리를 편집 범위에 포함한다.

→ 완료: prepare.md나 범위 모드 절의 완료 기준을 만족했고, `{T}` 유무와 모든 리뷰어에게 전달할 기준 커밋·대상 커밋·diff 파일이 정해졌다.

## 2. 문제 지점 찾기

`~/.claude/lib/review/find-issues.md`를 Read하고 그대로 수행한다. diff는 1단계의 diff 파일, 의도는 그 문서의 최신 승인·PR·커밋 기준과 출처, 대상은 1단계의 작업 디렉토리다.

타입·예외·추상화 발견은 `~/.claude/lib/coding/architecture.md`·`~/.claude/lib/coding/domain.md`·`~/.claude/lib/coding/errors.md`·`~/.claude/lib/coding/types.md`·`~/.claude/lib/coding/design.md` 기준으로 소유자와 생산자→소비자 경로를 읽어 확인한다. 적절한 entity/value object나 더 직접적인 흐름과 비교하고, 예외의 소유권과 usecase의 처리 정책을 구분하며 domain → application 역방향 의존을 만들지 않는지 본다.

`~/.claude/lib/review/find-issues.md` 다른 AI 교차 검증 절의 건너뛰기 조건에 해당하지 않으면, 서브에이전트 병렬 리뷰 절의 리뷰어와 같은 배치에서 Skill 도구로 `code-review`를 부른다. 인자는 `max` 뒤에 1단계의 diff 파일 경로 전부·기준 커밋·대상 커밋·작업 디렉토리 절대경로와 적재한 규칙·계획·승인 출처를 붙인다. PR 링크는 맥락으로만 전달하고, 리뷰 범위는 같은 diff 파일을 읽게 한다. 도구가 ref만 받으면 `{기준 커밋}..{대상 커밋}`을 쓰고 전달한 diff와 같은 범위인지 확인한다. 결과 통합 절은 code-review 결과가 돌아온 뒤 수행하고, 그 발견을 다른 리뷰어의 발견과 합쳐 출처를 `code-review`로 적는다.

→ 완료: 그 문서의 완료 기준을 만족했고, code-review를 불렀으면 그 발견도 이슈 리포트에 합쳐졌다.

## 3. 수정 적용

모든 발견에 조치한다: 고치거나, 묻거나, 남기는 이유를 적는다. 편집과 명령은 1단계의 작업 디렉토리에서 한다.

`~/.claude/lib/coding/tests.md`와 `~/.claude/lib/pr-rules.md`를 Read하고 버그 수정은 테스트 예외에 해당하지 않는 한 먼저 red를 확인한 뒤 고친다. 구조 변경과 동작 변경을 함께 반영할 때는 `~/.claude/lib/coding/process.md`의 Two hats대로 나누고, 각 묶음을 검증 후 새 커밋으로 남긴 뒤 다음 묶음을 반영한다.

1. 기존 패턴 확인: `~/.claude/lib/coding/process.md`를 Read하고 Existing patterns first를 2단계 발견에 적용한다.
2. 분류: AUTO-FIX = 기존 패턴과 일치하는 기계적 수정(import 정리, 오타, 누락 필드). ASK = 판단이 필요한 것(아키텍처 결정, 트레이드오프, 기존 패턴과 다른 방향). 새로 넣는 방어 코드(assert, 중복 `updated_count` 검사, 손으로 넣는 `updated_at`)도 ASK이고, 그 설명에는 DB 스키마(`ON UPDATE CURRENT_TIMESTAMP`)나 프레임워크(Django `auto_now`)가 이미 처리하는지 확인한 결과를 넣는다. 남김 = 고치지 않을 INFO 또는 적용 규칙·승인된 판단과 대조해 위반이 아닌 것으로 확인한 발견. 남김은 적용 규칙이나 승인 출처 등 이유를 한 줄로 적는다. 이 대조는 발견의 출처나 출처 수와 관계없이 모두 적용한다.
3. AUTO-FIX 적용: 주석은 줄이거나 지우기만 한다. 수정마다 한 줄: `[AUTO-FIXED] [file:line] 문제 → 조치`.
4. ASK는 한 번에 하나씩 묻는다. 사용자가 발견 원문을 보지 못했다고 가정하고 설명한다.
   1. 목록: 묻기 전에 ASK 전체를 번호 목록으로 한 번 보여 준다(`ASK 2/5 · orders/refund.py:42 · 부분 환불 누적 초과`).
   2. 설명: 항목마다 아래 순서로 쓴다. 발견 원문의 압축 용어(불변식, 필드명만 쓴 표현 등)는 풀어 쓴다.
      - 지금 코드: 해당 부분 3~10줄 인용과 한 줄 요약
      - 틀어지는 경우: 실제 값이 든 입력과 그 결과
      - 얼마나 자주: 확인한 근거(코드 경로 · 로그 · 쿼리). 확인하지 못했으면 미확인과 어디까지 봤는지
      - 선택지: 선택지마다 코드와 동작이 어떻게 달라지는지, 추천 하나와 이유 한 줄
   3. 질문: AskUserQuestion 한 번에 질문 하나만 넣고, 추천을 첫 옵션에 둔다.
   4. 답: 승인되면 바로 고치고 다음 항목으로 간다. 사용자가 되물으면 선택지를 다시 내기 전에 그 물음부터 코드·데이터로 답한다. 답 때문에 다른 ASK의 전제가 바뀌면 목록을 고쳐 다시 보여 준다.
   5. 대조: 끝나면 목록을 다시 보여 주고 항목마다 결과(승인 후 수정 · 보류 · 기각)를 채운다. 빈 칸이 있으면 그 항목부터 다시 묻는다.

   설명 예시:

   ```
   ASK 2/5 · orders/refund.py:42 · 부분 환불 누적 초과

   지금 코드: 환불 한 건이 결제액을 넘는지만 본다.
       if amount > order.paid_amount:
           raise RefundExceeded(order.id)
   틀어지는 경우: 결제 10,000원 주문에 7,000원 환불 요청이 두 번 오면 둘 다 통과해 14,000원이 나간다.
   얼마나 자주: 누적액을 보는 검사가 코드에 없다(grep -rn "paid_amount" orders/ 결과 이 검사 1곳). 운영 로그 빈도는 미확인.
   선택지:
     A) 누적 환불액으로 검사한다(추천: 초과 환불은 되돌리기 어렵다). 쿼리 1개 추가
     B) 멱등 키로 같은 요청의 재시도만 막는다. 서로 다른 두 요청은 여전히 통과
     C) 이번 PR에서는 보류하고 이슈로 남긴다
   ```

→ 완료: AUTO-FIXED · 승인 후 수정 · 보류 · 기각 · 남김의 합이 발견 총수와 같고, ASK 대조표에 빈 칸이 없다.

## 4. 마감

```
Review: N 이슈 (CRITICAL X · INFO Y)
Auto-fixed: Z · 승인 후 수정: W · 남은 항목: V (보류 · 기각 · 남김)
리뷰어별: 코드 A · 언어 B · 관점 C · 보안 S · code-review R · 교차 리뷰 D · 교차 적대 검증 E
```

반영한 수정이 있으면 `~/.claude/lib/coding/tests.md`를 Read하고 버그 수정은 red/green, 구조 변경은 Refactoring equivalence 기준으로 검증한다. 유지된 동작·승인된 변경·미확인 범위를 구분해 보고한다. 최종 diff와 최신 의도 및 PR 제목·본문(범위 모드는 해당 문서)을 다시 대조하고, 불일치는 보고하거나 권한이 있을 때만 사용자 작성 부분을 보존해 수정한다.

반영한 수정이 있으면 `~/.claude/lib/pr-rules.md`를 Read하고 커밋 전 검증을 통과할 때까지 수정한 뒤, 원래 구현 커밋 다음에 별도 새 커밋으로 남긴다. 구조 변경과 동작 변경은 `~/.claude/lib/coding/process.md`의 Two hats대로 나누고 각 커밋 전에 검증한다. 리뷰 대상과 무관한 파일(생성물 · 잠금 파일 등)은 커밋할 파일 목록에서 뺀다. 수정이 없으면 빈 커밋을 만들지 않는다.

사용자가 커밋을 미뤘거나 커밋 전 검증을 끝내지 못했으면 ff 반영과 정리를 건너뛰고 리뷰 worktree·브랜치를 보존하며 경로와 남은 작업을 알린다.

1단계에서 `{T}`가 있었고, 수정이 없거나 반영한 수정을 모두 커밋했을 때만 리뷰 브랜치를 head에 ff로 반영하고 리뷰 worktree를 지운다. ff가 실패하면 멈추고 묻는다.

```bash
git -C {T} merge --ff-only teddy/review/{head}
git -C {클론} worktree remove {작업 디렉토리}
git -C {T} branch -d teddy/review/{head}
```

커밋을 마쳤고 `{T}`가 없으면 head에서 커밋한 리뷰 worktree를 그대로 두고 그 경로를 알린다.

범위 모드는 커밋까지로 마치고, 처음 리뷰한 범위를 `{기준 커밋}..{대상 커밋}`, 추가한 수정 커밋을 별도로 알린다.

→ 완료: 요약과 검증 결과를 냈고, 검증을 통과한 수정 커밋이 head에 들어갔거나(`{T}`가 있었으면 ff 반영과 리뷰 worktree 정리까지) 사용자가 커밋을 미뤘다. 범위 모드면 고정한 리뷰 범위와 추가 수정 커밋을 알렸다.

## 범위 모드

1단계에서 PR 링크가 없을 때 prepare.md 대신 수행한다.

1. 현재 작업 트리에서 `git rev-parse --path-format=absolute --git-common-dir`로 얻은 공용 Git 디렉토리의 부모를 메인 클론 `{클론}`으로 정한다. `{repo}`는 그 클론의 디렉토리 이름, `{head}`는 현재 작업 트리의 `git branch --show-current`다.
2. `{base_ref}`는 인자로 받은 기준 ref, 대화나 연결된 계획에 기록한 기준 ref, 현재 작업 트리의 `git rev-parse --symbolic-full-name '@{upstream}'` 순으로 고른다. 셋 다 없으면 기준 브랜치나 커밋을 묻는다. 원격 ref를 쓰면 메인 클론에서 해당 원격을 fetch한 뒤 그 ref를 확정한다. `{base_ref}`에는 원격 접두사를 다시 붙이지 않는다.
3. worktree를 만들기 전에 `git -C {클론} log --oneline {base_ref}..{head}`로 리뷰할 커밋이 있는지 확인한다. 비면 지정한 범위에 리뷰할 커밋이 없다고 알리고 마친다.
4. 작업 디렉토리는 `{클론}/.claude/worktrees/review-{head}`이고, 1단계의 worktree 지시로 만든다.
5. `{스크래치}`는 이번 리뷰의 임시 디렉토리다. head의 `/`를 `-`로 바꾼 이름을 `{범위명}`으로, `{diff 파일}`을 `{스크래치}/{repo}-{범위명}.diff`로 정한다. `~/.claude/lib/review/diff.md`를 Read하고 메인 클론·작업 디렉토리·base_ref로 diff를 한 번 생성한다.

→ 완료: base_ref·head·작업 디렉토리·기준 커밋·대상 커밋·커밋 목록·diff 파일 경로와 `--stat`의 파일 수가 정해졌다.
