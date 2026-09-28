---
name: review
description: 브랜치 변경을 서브에이전트 3개(보안 트리거가 있으면 4개)로 병렬 리뷰하고, 수정을 적용한 뒤 PR 크기 검사와 push 안내까지 끝낸다.
disable-model-invocation: true
argument-hint: "[PR URL] [--sec N]"
---

# /review

push·PR 직전에 브랜치 변경을 리뷰하고, 수정을 적용하고, PR 크기를 재고, push 명령을 안내한다. 수정 없이 보고서만 필요하면 `/pr-review-report`.

## 1. 리뷰 대상 확정

인자가 GitHub PR URL(`https://github.com/{owner}/{repo}/pull/{number}`)이면 owner·repo·번호를 파싱하고, 그 레포의 로컬 클론으로 이동한 뒤 PR 브랜치를 체크아웃한다. 클론 경로를 모르면 사용자에게 묻는다.

```bash
git fetch origin <branch> && git checkout <branch>
```

이미 리뷰할 브랜치에서 실행 중이면 이 단계를 건너뛴다.

완료: 리뷰할 브랜치가 체크아웃돼 있고, 작업 디렉토리 절대경로를 안다.

## 2. Diff 수집과 스코프 체크

```bash
BASE=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo main)
git fetch origin $BASE --quiet
git diff origin/$BASE --stat
git log origin/$BASE..HEAD --oneline
git diff origin/$BASE          # 리뷰어에게 넘길 전문. 2-dot이라 커밋 전 작업 트리 변경도 포함된다
```

현재 브랜치가 base이거나 diff가 비면 "리뷰할 변경이 없습니다."로 종료한다. diff가 있으면 `~/.claude/lib/review/fanout.md`를 Read하고 「스코프 체크」대로 판정한다.

완료: diff 전문과 Scope Check 3줄이 나왔다.

## 3. 서브에이전트 병렬 리뷰 (3개 + 조건부 보안 1개)

먼저 보안 레벨을 정한다. `~/.claude/lib/security/index.md`가 있으면 그 「레벨 판정」절차를 2단계의 diff에 적용하고, 인자에 `--sec N`이 있으면 그 값을 쓴다. 파일이 없으면 레벨 1이다. 한 줄로 남긴다: `Security level: N (트리거: ...)`.

Agent tool로 `fanout.md` 「브리프」의 세 개를 동시에 띄우고, 레벨이 2 이상이면 보안 서브에이전트를 같은 배치에 넷째로 띄운다. 프롬프트마다 「서브에이전트 공통 지시」를 모두 넣는다. 보안 서브에이전트의 브리프는 `~/.claude/lib/security/index.md`의 레벨표가 정한 모듈 전부다. 사내 기준(고시·정보보호지침·진단 유형) 준수를 보고, 출력 형식·값 미기재는 index.md를 따른다.

완료: `Security level` 한 줄이 기록됐고, 세(레벨 2 이상이면 네) 결과가 모두 돌아왔다.

## 4. Codex 교차 검증 (선택)

이종 LLM(GPT 계열) 관점을 더할지 묻는다. `~/.claude/lib/codex-adversarial.md`를 Read하고 「언제 무엇을 돌리나」의 A/B/C를 옵션으로 AskUserQuestion 1회 묻는다. 선택 기준을 질문에 같이 적고, 권장 옵션 라벨에 `(Recommended)`를 붙인다. B·C면 그 문서대로 실행·회수한다.

완료: A를 골랐거나, 띄운 Codex job의 결과를 원문으로 회수했다.

## 5. 결과 통합

`fanout.md` 「결과 통합」대로 합치고 정렬한다. 출처 표시에는 보안도 넣는다(`(코드+팀+보안+codex)`).

완료: 중복이 합쳐지고 심각도순으로 정렬된 단일 리포트가 있다.

## 6. 수정 적용

모든 발견에 조치한다: 고치거나, 묻거나, 남기는 이유를 적는다.

1. 기존 패턴 확인: 수정 전에 같은 패턴이 다른 모듈에서 어떻게 쓰이는지 Grep으로 확인한다(예: id 필드 기본값 변경 → `grep "Field.*default.*description.*auto"`로 다른 엔티티 확인). 리뷰어가 제안한 방어 코드(assert·중복 존재 체크·수동 timestamp 세팅 등)가 기존 코드에 없는 패턴이면 ASK로 분류한다. MySQL DDL·프레임워크 빌트인이 이미 처리하고 있을 수 있다.
2. 분류: AUTO-FIX = 기존 패턴과 일치하는 기계적 수정(import 정리, 오타, 누락 필드). ASK = 판단이 필요한 것(아키텍처 결정, 트레이드오프, 기존 패턴과 다른 방향).
3. AUTO-FIX 적용: 수정마다 한 줄: `[AUTO-FIXED] [file:line] 문제 → 조치`.
4. ASK 일괄 질문: ASK 항목을 하나의 AskUserQuestion으로 묶어 묻고, 승인된 것만 적용한다.

완료: 모든 발견이 AUTO-FIXED · 승인 후 수정 · 사용자 보류 중 하나로 처리됐다.

## 7. 문서·페어 점검

`fanout.md` 「문서·페어 점검」을 적용한다. 페어 파일은 `diff -q`로 비교하고, 페어 sync 누락을 잡으면 반대쪽에도 같은 변경을 적용한다.

완료: 스테일 문서를 보고했고, 페어 차이는 양쪽에 반영됐다.

## 8. 변경 설명 문서

`~/.claude/skills/review/change-doc.md`를 Read하고 그 양식대로 이 PR이 왜 필요하고 어떻게 동작하는지 쓴다. 생성한 문서를 사용자에게 보여주고 저장 여부를 묻는다.

완료: 문서를 보여주고 저장 여부 답을 받았다.

## 9. 크기 검사와 push 안내

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
