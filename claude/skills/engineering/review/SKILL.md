---
name: review
description: 브랜치 변경을 서브에이전트 3개(보안 트리거가 있으면 4개)로 병렬 리뷰하고, 수정을 적용한 뒤 PR 크기 검사와 push 안내까지 끝낸다.
disable-model-invocation: true
argument-hint: "[PR URL] [--sec N]"
---

# /review

## 1. 리뷰 대상 확정

인자가 GitHub PR URL(`https://github.com/{owner}/{repo}/pull/{number}`)이면 owner·repo·번호를 파싱하고, 그 레포의 로컬 클론으로 이동한 뒤 PR 브랜치를 체크아웃한다. 클론 경로를 모르면 사용자에게 묻는다.

```bash
git fetch origin <branch> && git checkout <branch>
```

이미 리뷰할 브랜치에서 실행 중이면 이 단계를 건너뛴다.

완료: 리뷰할 브랜치가 체크아웃돼 있고, 작업 디렉토리 절대경로를 안다.

## 2. Diff 수집

```bash
BASE=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo main)
git fetch origin $BASE --quiet
git diff origin/$BASE --stat
git log origin/$BASE..HEAD --oneline
git diff origin/$BASE          # 리뷰어에게 넘길 전문. 2-dot이라 커밋 전 작업 트리 변경도 포함된다
```

현재 브랜치가 base이거나 diff가 비면 "리뷰할 변경이 없습니다."로 종료한다.

완료: diff 전문이 나왔다.

## 3. 문제 지점 찾기

`~/.claude/lib/review/find-issues.md`를 Read하고 그대로 수행한다. 입력: 2단계 diff, 의도(요청된 작업), 대상 브랜치는 현재 브랜치, 인자에 `--sec N`이 있으면 그 보안 레벨.

완료: 그 문서의 완료 기준을 만족했다.

## 4. 수정 적용

모든 발견에 조치한다: 고치거나, 묻거나, 남기는 이유를 적는다.

1. 기존 패턴 확인: 수정 전에 같은 패턴이 다른 모듈에서 어떻게 쓰이는지 Grep으로 확인한다(예: id 필드 기본값 변경 → `grep "Field.*default.*description.*auto"`로 다른 엔티티 확인). 리뷰어가 제안한 방어 코드(assert·중복 존재 체크·수동 timestamp 세팅 등)가 기존 코드에 없는 패턴이면 ASK로 분류한다. MySQL DDL·프레임워크 빌트인이 이미 처리하고 있을 수 있다.
2. 분류: AUTO-FIX = 기존 패턴과 일치하는 기계적 수정(import 정리, 오타, 누락 필드). ASK = 판단이 필요한 것(아키텍처 결정, 트레이드오프, 기존 패턴과 다른 방향).
3. AUTO-FIX 적용: 수정마다 한 줄: `[AUTO-FIXED] [file:line] 문제 → 조치`.
4. ASK 일괄 질문: ASK 항목을 하나의 AskUserQuestion으로 묶어 묻고, 승인된 것만 적용한다.
5. 페어 sync 누락은 `diff -q`로 확인하고 반대쪽에도 같은 변경을 적용한다.

완료: 모든 발견이 AUTO-FIXED · 승인 후 수정 · 사용자 보류 중 하나로 처리됐고, 페어 차이는 양쪽에 반영됐다.

## 5. 변경 설명 문서

`~/.claude/skills/review/change-doc.md`를 Read하고 그 양식대로 이 PR이 왜 필요하고 어떻게 동작하는지 쓴다. 생성한 문서를 사용자에게 보여주고 저장 여부를 묻는다.

완료: 문서를 보여주고 저장 여부 답을 받았다.

## 6. 크기 검사와 push 안내

`~/.claude/skills/review/size-check.md`를 Read하고 판정까지 수행한다. 판정이 끝나면(FAIL이면 분할 합의까지) 요약과 push 명령을 낸다.

```
Review: N 이슈 (CRITICAL X · INFO Y)
Auto-fixed: Z · 승인 후 수정: W · 남은 항목: V
리뷰어별: 코드 A · 언어 B · 팀 C · 보안 S · Codex D · Codex adversarial E

/review 완료. 아래 명령으로 push해주세요:

! cd {작업 디렉토리 절대경로} && git push
```

push는 사용자가 `!` 접두사로 직접 실행한다. Claude는 `git push`·`gh pr create`를 실행하지 않는다(PreToolUse 훅도 이 둘을 ask로 잡는다). 이어지는 PR 생성은 `~/.claude/lib/pr-rules.md` 가 있으면 그것을 읽고 그대로 따른다(제목의 이슈 ID·assignee·본문 형식).

완료: 크기 판정과 절대경로가 든 push 명령을 사용자에게 전달했다.
