---
name: implement-review
description: 내 PR이나 push 안 한 커밋을 서브에이전트로 병렬 리뷰하고, 발견마다 고치거나 하나씩 물어 반영한 뒤 커밋까지 끝낸다.
disable-model-invocation: true
argument-hint: "[PR URL, 없으면 push 안 한 커밋]"
---

## 1. 리뷰 준비

인자나 대화에 PR 링크가 있으면 `~/.claude/lib/review/prepare.md`를 Read하고 수행한다. 없으면 범위 모드 절을 수행해 현재 디렉토리 레포의 push 안 한 커밋을 리뷰한다. 두 경우 모두 리뷰 worktree는 아래처럼 만든다. 먼저 head가 체크아웃된 트리 `{T}`를 찾는다.

```bash
git -C {클론} worktree list --porcelain    # "branch refs/heads/{head}" 줄이 든 블록의 "worktree" 줄이 {T}다
```

- `{T}`가 있으면: `git -C {T} status --short`에 미커밋 변경이나 untracked 파일이 있을 때 목록을 보여 주고, 먼저 커밋해 리뷰에 넣을지 빼고 진행할지 묻는다. 그다음 `git -C {클론} worktree add -b review/{head} {작업 디렉토리} {head}`로 리뷰 브랜치를 올린다.
- `{T}`가 없으면: `git -C {클론} worktree add {작업 디렉토리} {head}`로 head를 바로 올린다.

작업 디렉토리나 `review/{head}` 브랜치가 이미 있으면, `review/{head}`가 없거나 `git -C {클론} merge-base --is-ancestor review/{head} {head}`가 참일 때만 지우고 다시 만든다. 작업 디렉토리는 `git -C {클론} worktree remove {작업 디렉토리}`로 지우고, `{T}`가 있으면 `review/{head}`를 `git -C {T} branch -d review/{head}`로 지운다. 그 밖의 경우나 remove나 `branch -d`가 거절하면 사용자에게 묻는다.

→ 완료: prepare.md나 범위 모드 절의 완료 기준을 만족했고, `{T}` 유무가 정해졌다.

## 2. 문제 지점 찾기

`~/.claude/lib/review/find-issues.md`를 Read하고 그대로 수행한다. diff는 1단계의 diff 파일, 의도는 PR 제목·본문(범위 모드는 커밋 메시지), 대상은 1단계의 작업 디렉토리다.

레이어·예외 위치 발견은 `~/.claude/lib/coding/architecture.md`·`~/.claude/lib/coding/domain.md`·`~/.claude/lib/coding/errors.md`의 소유권 기준으로 확인한다. 현재 판정이 업무 불변식인지 실행 절차 정책인지 설명하고, 이동 제안은 판정과 예외를 함께 다루며 domain → usecase 의존을 만들지 않는지 본다.

`~/.claude/lib/review/find-issues.md` 다른 AI 교차 검증 절의 건너뛰기 조건에 해당하지 않으면, 서브에이전트 병렬 리뷰 절의 리뷰어와 같은 배치에서 Skill 도구로 `code-review`를 부른다. 인자는 `max` 뒤에 대상(PR 링크, 범위 모드면 `{base}..HEAD`)과 작업 디렉토리 절대경로를 붙인다. 결과 통합 절은 code-review 결과가 돌아온 뒤 수행하고, 그 발견을 다른 리뷰어의 발견과 합쳐 출처를 `code-review`로 적는다.

→ 완료: 그 문서의 완료 기준을 만족했고, code-review를 불렀으면 그 발견도 이슈 리포트에 합쳐졌다.

## 3. 수정 적용

모든 발견에 조치한다: 고치거나, 묻거나, 남기는 이유를 적는다. 편집과 명령은 1단계의 작업 디렉토리에서 한다.

1. 기존 패턴 확인: `~/.claude/lib/coding/process.md`를 Read하고 Existing patterns first를 2단계 발견에 적용한다.
2. 분류: AUTO-FIX = 기존 패턴과 일치하는 기계적 수정(import 정리, 오타, 누락 필드). ASK = 판단이 필요한 것(아키텍처 결정, 트레이드오프, 기존 패턴과 다른 방향). 새로 넣는 방어 코드(assert, 중복 `updated_count` 검사, 손으로 넣는 `updated_at`)도 ASK이고, 그 설명에는 DB 스키마(`ON UPDATE CURRENT_TIMESTAMP`)나 프레임워크(Django `auto_now`)가 이미 처리하는지 확인한 결과를 넣는다. 남김 = 고치지 않을 INFO. 남김은 이유를 한 줄로 적는다. 출처가 `code-review`뿐인 발견은 `~/.claude/lib/coding/index.md`를 Read하고 그 목록에서 발견이 닿는 모듈을 Read해, 그 규칙과 어긋나면 남김으로 두고 이유에 그 규칙을 적는다.
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

반영한 수정이 있으면 `~/.claude/lib/pr-rules.md`를 Read하고 그 문서의 커밋 규칙대로 커밋한다. 리뷰 대상과 무관한 파일(생성물 · 잠금 파일 등)은 커밋할 파일 목록에서 뺀다.

1단계에서 `{T}`가 있었으면 리뷰 브랜치를 head에 ff로 반영하고 리뷰 worktree를 지운다. ff가 실패하면 멈추고 묻는다.

```bash
git -C {T} merge --ff-only review/{head}
git -C {클론} worktree remove {작업 디렉토리}
git -C {T} branch -d review/{head}
```

`{T}`가 없었거나 사용자가 커밋을 미뤘으면 리뷰 worktree를 그대로 두고 그 경로를 알린다.

범위 모드는 커밋까지로 마치고, 리뷰한 범위를 `{base}..{리뷰를 마친 커밋의 짧은 해시}`로 알린다.

→ 완료: 요약을 냈고, 반영분이 head에 들어갔거나(`{T}`가 있었으면 ff 반영과 리뷰 worktree 정리까지) 사용자가 커밋을 미뤘다. 범위 모드면 리뷰한 범위를 알렸다.

## 범위 모드

1단계에서 PR 링크가 없을 때 prepare.md 대신 수행한다.

1. 현재 디렉토리의 레포로 정한다: `{클론}`은 `git rev-parse --show-toplevel`, `{repo}`는 `{클론}`의 디렉토리 이름, `{head}`는 `git branch --show-current`, `{base}`는 `git rev-parse --abbrev-ref '@{upstream}'`의 출력이다. upstream이 없으면 "push 안 한 커밋을 가를 upstream이 없습니다."라고 알리고 멈춘다.
2. 작업 디렉토리는 `{클론}/.claude/worktrees/review-{head}`이고, 1단계의 worktree 지시로 만든다.
3. 커밋 목록과 diff를 만든다. 커밋 목록이 비면 "리뷰할 커밋이 없습니다. 모두 push됐습니다."라고 알리고, `git -C {클론} worktree remove {작업 디렉토리}`와 `git -C {클론} branch -d review/{head}`로 작업 디렉토리와 리뷰 브랜치를 지운 뒤 멈춘다.

```bash
git -C {작업 디렉토리} log --format='%h %s%n%n%b' {base}..HEAD    # 커밋 목록이자 2단계의 의도
git -C {작업 디렉토리} diff {base}..HEAD --stat
git -C {작업 디렉토리} diff {base}..HEAD > {스크래치}/{repo}-{head}.diff
```

`{스크래치}`는 이 세션의 임시 디렉토리다. diff가 1000줄을 넘으면 파일별로 나눠 저장한다.

→ 완료: `{base}`·`{head}`·작업 디렉토리·커밋 목록·diff 파일 경로와 `--stat`의 파일 수가 정해졌다.
