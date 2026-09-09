---
name: review
description: 브랜치 변경을 서브에이전트 3개로 병렬 리뷰하고, 수정을 적용한 뒤 PR 크기 검사와 push 안내까지 끝낸다.
disable-model-invocation: true
argument-hint: "[PR URL]"
---

# /review

push·PR 직전에 브랜치 변경을 리뷰하고, 수정을 적용하고, PR 크기를 재고, push 명령을 안내한다. 수정 없이 보고서만 필요하면 `/pr-review-report`.

## 1. 리뷰 대상 확정

인자가 GitHub PR URL(`https://github.com/{owner}/{repo}/pull/{number}`)이면 owner·repo·번호를 파싱하고, 그 레포의 로컬 클론으로 이동한 뒤 PR 브랜치를 체크아웃한다. 클론 경로를 모르면 사용자에게 묻는다.

```bash
git fetch origin <branch> && git checkout <branch>
```

이미 리뷰할 브랜치에서 실행 중이면 이 단계를 건너뛴다.

**완료**: 리뷰할 브랜치가 체크아웃돼 있고, 작업 디렉토리 절대경로를 안다.

## 2. Diff 수집과 스코프 체크

```bash
BASE=$(gh pr view --json baseRefName -q .baseRefName 2>/dev/null || gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo main)
git fetch origin $BASE --quiet
git diff origin/$BASE --stat
git log origin/$BASE..HEAD --oneline
git diff origin/$BASE          # 리뷰어에게 넘길 전문. 2-dot이라 커밋 전 작업 트리 변경도 포함된다
```

현재 브랜치가 base이거나 diff가 비면 "리뷰할 변경이 없습니다."로 종료한다. diff가 있으면 스코프를 판정한다.

```
Scope Check: [CLEAN / DRIFT / MISSING]
의도: <요청된 작업 1줄>
실제: <diff가 실제로 하는 것 1줄>
```

**완료**: diff 전문과 Scope Check 3줄이 나왔다.

## 3. 서브에이전트 3개 병렬 리뷰

Agent tool로 **세 개를 동시에** 띄운다. 각 프롬프트에 아래를 모두 넣는다.

1. diff 전문(너무 길면 파일별 요약 + 핵심 변경부).
2. 담당 기준 파일 경로 — 서브에이전트가 직접 Read한다.
3. "`~/.claude/coding-rules.md`의 §0 Precedence·§1 Architecture·§2 Module·§3 Class/Object를 Read하고 적용하라. diff에 Python·프론트엔드·DB 파일이 있으면 `~/.claude/coding-rules-python.md`·`-frontend.md`·`-db.md`도 Read하라."
4. "기준의 각 항목을 빠짐없이 판단하고, 해당 없으면 PASS라고 쓴다."
5. "발견은 `[CRITICAL|INFO] file:line — 설명` 형식으로 낸다."
6. "코드베이스 확인이 필요한 것은 Grep/Read로 직접 검증한다" + 아래 [주장 검증](#주장-검증) 4줄.

| 서브에이전트 | 기준 파일 | 역할 |
|---|---|---|
| 코드 공통 | `~/.claude/lib/review/code.md` | 보안·정확성·계약 일관성·클린코드·YAGNI·아키텍처·에러핸들링·관측성·성능·테스팅·운영 안전성 |
| 언어별 | `~/.claude/lib/review/language.md` | diff에 포함된 언어(Python·Go·Java·프론트엔드)의 관용구·타입 안전성·플랫폼 특화 이슈 |
| 팀 리뷰어 | `~/.claude/lib/review/team.md` | 리뷰어 카탈로그(R1~R24 매핑표)별 관점. 매핑표의 도메인 컬럼으로 diff에 해당하는 리뷰어를 골라 점검 |

**완료**: 세 결과가 모두 돌아왔다.

## 4. Codex 교차 검증 (선택)

이종 LLM(GPT 계열) 관점을 더할지 AskUserQuestion으로 **1회** 묻는다. 선택 기준을 질문에 같이 적고, 권장 옵션 라벨에 `(Recommended)`를 붙인다.

- A) 건너뛰기 — 변경 200줄 미만 + 루틴 수정
- B) `codex review` — 200줄 이상 또는 도메인·애플리케이션 레이어 변경
- C) `codex review` + `codex adversarial-review` — 새 추상화·레이어 도입, 마이그레이션 동반, 아키텍처 결정

B·C면 `~/.claude/lib/codex-adversarial.md`를 Read하고 그대로 실행·회수한다.

**완료**: A를 골랐거나, 띄운 Codex job의 결과를 원문으로 회수했다.

## 5. 결과 통합

같은 이슈를 여러 리뷰어가 잡았으면 하나로 합치고 출처를 표시한다(`(코드+팀+codex)`). CRITICAL을 위, INFO를 아래로 정렬한다. Codex 결과는 요약·paraphrase 없이 별도 블록에 원문 그대로 붙인다.

**완료**: 중복이 합쳐지고 심각도순으로 정렬된 단일 리포트가 있다.

## 6. 수정 적용

**모든 발견에 조치한다** — 고치거나, 묻거나, 남기는 이유를 적는다.

1. **기존 패턴 확인**: 수정 전에 같은 패턴이 다른 모듈에서 어떻게 쓰이는지 Grep으로 확인한다(예: id 필드 기본값 변경 → `grep "Field.*default.*description.*auto"`로 다른 엔티티 확인). 리뷰어가 제안한 방어 코드(assert·중복 존재 체크·수동 timestamp 세팅 등)가 기존 코드에 없는 패턴이면 ASK로 분류한다 — MySQL DDL·프레임워크 빌트인이 이미 처리하고 있을 수 있다.
2. **분류**: AUTO-FIX = 기존 패턴과 일치하는 기계적 수정(import 정리, 오타, 누락 필드). ASK = 판단이 필요한 것(아키텍처 결정, 트레이드오프, 기존 패턴과 다른 방향).
3. **AUTO-FIX 적용** — 수정마다 한 줄: `[AUTO-FIXED] [file:line] 문제 → 조치`.
4. **ASK 일괄 질문** — ASK 항목을 하나의 AskUserQuestion으로 묶어 묻고, 승인된 것만 적용한다.

**완료**: 모든 발견이 AUTO-FIXED · 승인 후 수정 · 사용자 보류 중 하나로 처리됐다.

## 7. 문서·페어 점검

diff가 바꾼 기능을 설명하는 문서가 그대로면 알린다: `[INFO] 문서가 오래됐을 수 있음: [파일]이 [기능]을 설명하지만 코드가 변경됨.`

diff가 CLAUDE.md나 AGENTS.md를 건드렸다면 페어 파일도 같이 바뀌었는지 확인한다.

```bash
diff -q ~/.claude/CLAUDE.md ~/.codex/AGENTS.md
diff -q ~/example/CLAUDE.md ~/example/AGENTS.md
diff -q ~/example_analysis/CLAUDE.md ~/example_analysis/AGENTS.md
```

도구별 분기 섹션(assignee 등) 외에 차이가 있으면 `[CRITICAL] 페어 sync 누락: {파일}`로 잡고 반대쪽에도 같은 변경을 적용한다.

**완료**: 스테일 문서를 보고했고, 페어 차이는 양쪽에 반영됐다.

## 8. 변경 설명 문서

`~/.claude/skills/review/change-doc.md`를 Read하고 그 양식대로 이 PR이 왜 필요하고 어떻게 동작하는지 쓴다. 생성한 문서를 사용자에게 보여주고 저장 여부를 묻는다.

**완료**: 문서를 보여주고 저장 여부 답을 받았다.

## 9. 크기 검사와 push 안내

`~/.claude/skills/review/size-check.md`를 Read하고 판정까지 수행한다. 판정이 끝나면(FAIL이면 분할 합의까지) 요약과 push 명령을 낸다.

```
Review: N 이슈 (CRITICAL X · INFO Y)
Auto-fixed: Z · 승인 후 수정: W · 남은 항목: V
리뷰어별: 코드 A · 언어 B · 팀 C · Codex D · Codex adversarial E

/review 완료. 아래 명령으로 push해주세요:

! cd {작업 디렉토리 절대경로} && git push
```

push는 사용자가 `!` 접두사로 직접 실행한다 — Claude는 `git push`·`gh pr create`를 실행하지 않는다(PreToolUse 훅도 이 둘을 ask로 잡는다). 이어지는 PR 생성은 `~/example/.claude/pr-rules.md`를 읽고 그대로 따른다(제목의 Linear ID·assignee·본문 형식).

**완료**: 크기 판정과 절대경로가 든 push 명령을 사용자에게 전달했다.

## 주장 검증

- "이 패턴은 안전" → 안전을 증명하는 구체적 라인을 인용한다.
- "다른 곳에서 처리됨" → 그 코드를 읽고 인용한다.
- "테스트가 커버함" → 테스트 파일과 메서드 이름을 댄다.
- 확인하지 못한 것은 "미확인"으로 표시한다 — "아마 처리됐을 것"으로 넘기지 않는다.
