지난달(인자로 받은 달) 머지된 PR 묶음으로 내 리뷰·리뷰봇·사람 리뷰를 머지된 결과에 대어 센다. 이 파일의 채점 방법은 사용자만 고친다. 결과는 `~/plans/ai-rules-refresh/notes/pr/{YYYY-MM}/`에 둔다. PR 하나씩 규칙을 고치고 같은 PR로 다시 확인하지 않는다.

## 1. 사례 모으기

```bash
python3 ~/.claude/skills/rules-refresh/refresh.py pr-collect {YYYY-MM} ~/plans/ai-rules-refresh/notes/pr/{YYYY-MM}
```

- PR 묶음: 그 달 머지된 PR 가운데 내가 작성했거나 리뷰했거나 내 리뷰 기록이 있는 PR.
- 내 리뷰: 내 계정 GitHub 리뷰 가운데 본문에 `🤖 ai-review가 작성한 리뷰입니다.`가 든 것, `~/plans` 아래 review-log.md의 그 브랜치 항목, `~/pr_reviews/{repo}/{number}/review.html`.
- 리뷰봇: GitHub Bot 계정의 리뷰, `~/.claude/lib/review-bots/index.md` 봇 리뷰 판별 절의 계정과 본문 표식이 맞는 리뷰·PR 대화 코멘트. 표식이 없는 Bot 계정의 PR 대화 코멘트(이슈 연결·커버리지·CI 결과)는 리뷰가 아니라 사례 파일의 `skipped_bot_comments`로만 센다.
- 사람 리뷰: PR 작성자를 뺀 나머지 User 계정의 리뷰·PR 대화 코멘트.
- 리뷰가 본 커밋: GitHub 리뷰의 commit, review.html의 head, review-log 항목 범위의 끝 커밋. 코멘트처럼 커밋이 없으면 그 시각까지 head 줄기에 올라온 마지막 커밋.
- 첫 외부 리뷰: 내 리뷰를 뺀 리뷰 가운데 가장 이른 것(사례 파일의 `first_external_commit`).

→ 완료: `prs.json`과 PR마다 사례 파일(`cases/*.json`)이 있다.

## 2. 정답

정답은 리뷰 지적이 아니라 머지된 결과다. 리뷰마다 정답은 그 리뷰가 본 커밋 다음부터 머지까지 PR 커밋이 바꾼 곳이다(사례 파일의 `post_commits`와 `patches`).

- 사례 파일의 `post_commits`는 PR head에서 첫 부모만 따라간 줄기의 커밋이라, 기준 브랜치(master나 stacked PR의 아래 브랜치)를 병합해 들어온 커밋은 이미 빠졌다. 그 줄기의 병합 커밋은 손으로 푼 충돌 해결(`git show --cc`)이 있을 때만 `(병합 충돌 해결)` 패치로 남는다. 로컬 클론에 없어 보지 못한 병합 커밋은 `unresolved_merges`에 있고, 판정 파일에 그 사실을 적는다. 요구사항이 바뀐 커밋은 판정에서 뺀다.
- 요구사항이 바뀐 커밋은 커밋 메시지나 PR 대화에 요구·범위가 바뀌었다는 근거가 있는 커밋이다. 뺄 때 그 근거를 적는다.
- 바뀐 곳 하나는 남긴 커밋의 hunk 하나다. 같은 커밋·같은 파일에서 3줄 안으로 붙은 hunk는 하나로 센다. 뒤 커밋이 같은 줄을 원래대로 되돌린 hunk 짝은 머지된 결과에 없으니 둘 다 뺀다. 패치가 `truncated`면 `gh api repos/{owner}/{repo}/commits/{oid}`로 전체를 읽고 센다. 사례 파일이 `commits_truncated`면 그 사실을 판정 파일에 적는다.

→ 완료: 리뷰마다 바뀐 곳 목록과 뺀 커밋의 근거가 있다.

## 3. 대조

PR마다 서브에이전트 하나에 사례 파일 경로와 이 파일의 2·3·4절을 주고, 결과를 `judged/{owner}__{repo}__{number}.json`에 쓰게 한다. 서브에이전트는 한 메시지에 10개씩 띄운다.

묶음(내 리뷰·리뷰봇·사람 리뷰)마다 그 묶음이 리뷰한 PR에서만 센다. 지적은 코드나 PR의 문제를 가리키는 문장이고, 승인·요약·감사 인사만 있는 리뷰는 지적 0개다. 내 리뷰가 남김·기각·보류로 닫은 발견과 고칠 것이 없다고 적은 INFO는 지적으로 세지 않고 4절 찾고 버림 판정에만 쓴다.

- 잡은 것: 지적이 가리킨 문제를 바뀐 곳이 고쳤다.
- 놓친 것: 그 묶음의 첫 리뷰가 본 커밋 뒤에 바뀐 곳 가운데 그 묶음의 어느 지적도 가리키지 않은 것.
- 헛짚은 것: 바뀐 곳과 이어지지 않는 지적. 이미 고쳐진 코드를 가리킨 지적도 여기에 센다.
- 지적 하나가 바뀐 곳 여럿을 가리키면 잡은 것 1로 센다. 바뀐 곳 하나를 여러 묶음이 가리키면 묶음마다 센다.

판정 파일 꼴:

```json
{"pr": "{owner}/{repo}#{number}",
 "excluded_commits": [{"oid": "", "reason": ""}],
 "groups": {"mine": {"caught": 0, "missed": 0, "false_positive": 0}, "bot": {}, "human": {}},
 "my_misses": [{"change": "{file}:{line}", "class": "맥락 밖 | 찾고 버림 | 지식 공백 | 탐지 공백", "pattern": "", "severity": "CRITICAL | INFO", "domain": "돈 | 보안 | 그 밖"}],
 "my_caught": [{"finding": "", "criterion": "{리뷰 기준 파일}:{항목}"}]}
```

→ 완료: 사례 파일마다 판정 파일이 있다.

## 4. 내가 놓친 것

내 리뷰가 놓친 바뀐 곳마다 하나로 나눈다.

- 맥락 밖: 정책·요구사항을 알아야 찾는다.
- 찾고 버림: 내 리뷰가 같은 문제를 남김·기각·보류로 닫았거나 INFO로 낮췄다.
- 지식 공백: 코드베이스나 도메인의 사실을 알아야 찾는다.
- 탐지 공백: diff와 리뷰 기준만으로 찾을 수 있었다.

잡은 것마다 그 지적을 낸 리뷰 기준(`~/.claude/lib/review/` 아래 파일과 항목)을 적는다.

## 5. 질문

- 리뷰 기준을 더하자는 질문은 탐지 공백에서만 낸다. 같은 꼴이 PR 2개 이상(돈·보안 CRITICAL은 1개)에서 나와야 올린다. 규칙 문장에는 PR 고유 이름(레포·파일·함수·필드)을 쓰지 않는다.
- 리뷰 기준 항목은 `~/.claude/lib/review/` 아래 파일의 절 하나이고, 목록은 그 폴더를 Grep으로 `^## `을 찾아 뽑는다. 내 리뷰가 있는 PR을 판정한 달마다, 잡은 것이 0인 항목은 state.json `pr_eval.zero_streak`의 그 항목 값을 1 올리고 잡은 항목은 0으로 둔다. 3이 된 항목은 삭제 후보로 질문에 올린다.
- 리뷰 규칙을 바꾸자는 질문마다 6절 재생으로 근거 PR과 회귀용 PR을 지금 규칙과 바꾼 규칙으로 돌려, 잡은 것과 잃은 것을 숫자로 붙인다.

## 6. 재생

- 재생은 내 리뷰가 없는 PR에 내 리뷰를 만들 때와 바꾼 규칙을 시험할 때만, 한 달에 리뷰 10회 안에서 한다. 내 리뷰가 없는 PR은 외부 리뷰 뒤 바뀐 곳이 많은 순으로 고른다.
- head는 그 PR의 첫 외부 리뷰가 본 커밋(사례 파일의 `first_external_commit`)으로 고정한다. 그 PR의 코멘트·plan.md·review-log.md는 읽지 않는다.
- 아래 명령이 두 조건을 강제한다: head 조상만 든 격리 저장소, 미리 뽑은 diff·커밋 기록·PR 제목과 본문, 사용자 설정을 뺀 허용 목록(Bash·웹·`~/plans`의 다른 파일·`~/pr_reviews` 불가), find-issues 1·2·3·5절.

  ```bash
  python3 ~/.claude/skills/rules-refresh/refresh.py replay {사례 파일} ~/plans/ai-rules-refresh/notes/pr/{YYYY-MM}/replay/{repo}-{number}-{규칙 이름} [--rules {바꾼 lib/review 사본}]
  ```

- `replay-check.json`의 `exit`가 0, `result_written`과 `head_pinned`가 참, `refs`가 비고 `commits_outside_head`와 `forbidden_succeeded`가 0인 재생만 쓴다. 아니면 그 재생은 버리고 이유를 적는다.
- 재생의 `result.md` 이슈 리포트를 그 PR의 내 리뷰로 보고 3절대로 판정한다.

→ 완료: 쓴 재생마다 replay-check.json이 조건을 만족하고, 버린 재생은 이유가 있고, 재생 횟수가 10 이하다.

## 7. 리포트

`python3 ~/.claude/skills/rules-refresh/refresh.py pr-tally ~/plans/ai-rules-refresh/notes/pr/{YYYY-MM}`의 합계로 `~/plans/ai-rules-refresh/notes/pr/{YYYY-MM}/report.md`를 한 페이지로 쓰고 state.json `pr_eval.month`를 그 달로 고친다.

```
# PR 대조 {YYYY-MM} · PR {n}개
| 묶음 | 리뷰한 PR | 잡은 것 | 놓친 것 | 헛짚은 것 |
|---|---|---|---|---|
| 내 리뷰 | | | | |
| 리뷰봇 | | | | |
| 사람 리뷰 | | | | |

내가 놓친 것: 맥락 밖 {n} · 찾고 버림 {n} · 지식 공백 {n} · 탐지 공백 {n}
재생: {n}회 · head 고정 {n}/{n} · 코멘트 차단 {n}/{n}
## 질문
1. {질문} · 근거 PR {n}개 · 재생 수치
## 판정 근거
- {owner}/{repo}#{number}: {판정 파일 경로}
```

→ 완료: 리포트에 세 묶음의 잡은 것·놓친 것·헛짚은 것 숫자와 재생 검사 결과가 있다.
