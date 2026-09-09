---
name: retro
description: 최근 N일 커밋 이력으로 주간 엔지니어링 회고 리포트를 만든다.
disable-model-invocation: true
argument-hint: "[Nd]"
---

현재 레포의 origin 기본 브랜치 커밋에서 메트릭·세션·churn 핫스팟·streak 을 뽑아 KPT(Keep/Problem/Try)로 닫는 회고를 한 번에 출력한다. `/retro [Nd]` — 기본 7d, 예: `/retro 14d`, `/retro 30d`.

## 1. 데이터 수집

```bash
git fetch origin --quiet                 # 분석은 전부 origin/$DEFAULT (로컬 브랜치는 낡을 수 있다)
DAYS=7                                   # /retro 14d → 14, /retro 30d → 30
SINCE="$DAYS days ago"                   # --since 는 approxidate — "7d" 는 안 잡혀 조용히 0건이 된다
SINCE_DATE=$(date -v-"$DAYS"d +%F)       # gh 검색용
USER_EMAIL=$(git config user.email)      # '내 주간' 의 본인 식별 키 (author 이름 표기는 어긋난다)
DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
DEFAULT=${DEFAULT:-$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null)}
# 둘 다 비면(origin/HEAD 미설정) AskUserQuestion 으로 브랜치를 묻는다. main 으로 추측하지 않는다
```

```bash
# 커밋 + stat
git log origin/$DEFAULT --since="$SINCE" --format="%H|%aN|%ae|%ai|%s" --shortstat

# 테스트 vs 프로덕션 LOC (경로에 test·spec 이 있으면 테스트)
git log origin/$DEFAULT --since="$SINCE" --format="COMMIT:%H|%aN" --numstat

# 타임스탬프 (세션 감지용)
git log origin/$DEFAULT --since="$SINCE" --format="%at|%aN|%ai|%s" | sort -n

# 핫스팟 Top 10
git log origin/$DEFAULT --since="$SINCE" --format="" --name-only | grep -v '^$' | sort | uniq -c | sort -rn | head -10

# 작성자별 커밋 수
git shortlog origin/$DEFAULT --since="$SINCE" -sn --no-merges

# streak 용 커밋 날짜
git log origin/$DEFAULT --format="%ad" --date=format:"%Y-%m-%d" | sort -u | tail -60

# 머지된 PR (개수 + 가장 큰 ship)
gh pr list --state merged --search "merged:>=$SINCE_DATE" --limit 200 \
  --json number,title,additions,deletions,author \
  --jq '.[] | "\(.number)|\(.author.login)|+\(.additions)/-\(.deletions)|\(.title)"'
```

`gh` 가 없거나 인증이 끊겼으면 PR 수는 커밋 제목의 `(#숫자)` 개수로 대신한다.

완료 기준: 7개 출력이 모두 손에 있고 커밋이 1건 이상. 0건이면 더 넓은 기간을 AskUserQuestion 으로 제안하고 멈춘다.

## 2. 리포트 작성

첫 줄은 헤드라인 한 줄:
```
이번 주: 47 커밋, 3.2k LOC, 38% 테스트, 12 PR, 피크: 오후 10시 | 연속: 47일
```

이어서 아래 10개 섹션을 이 순서로 쓴다.

### 요약 테이블
메인 커밋 수 / 기여자 / 총 insertions·deletions(`+N / -N`) / 테스트 LOC 비율 / 활동일(커밋이 있는 날짜 수) / 감지된 세션 6행.

### 시간 & 세션 패턴
시간대별 히스토그램(로컬 시간)으로 피크 시간·데드존·야간 코딩 패턴을 짚는다.
```
Hour  Commits
 09:    5      █████
 14:   12      ████████████
 22:    3      ███
```
세션은 **45분 갭**으로 끊고 각 세션의 시작/종료 시간·커밋 수·기간을 적는다. **Deep**(50분+) / **Medium**(20-50분) / **Micro**(<20분) 로 분류하고 총 활동 코딩 시간·평균 세션 길이·시간당 LOC 를 낸다. squash-merge 레포에서는 이 타임스탬프가 머지 시각이므로 세션을 "머지 리듬"으로 읽는다.

### 배포 속도
Conventional commit prefix(feat/fix/refactor/test/chore/docs …) 별 비율을 바로 그린다.
```
feat:     20  (40%)  ████████████████████
fix:      27  (54%)  ███████████████████████████
```
**streak**: 오늘부터 역순으로 커밋 없는 날에서 끊길 때까지의 연속 달력 일수(주말·휴일 포함).

### 코드 품질 신호
테스트 LOC 비율. fix 비율 > 50% 면 **firefighting**("빠르게 배포, 빠르게 수정") 경고. **churn 핫스팟** = Top 10 중 5회 이상 변경된 파일.

### Focus & 하이라이트
**Focus Score** = 가장 많이 변경된 최상위 디렉토리의 커밋 비율(낮으면 컨텍스트 스위칭). **biggest ship** = 기간 내 가장 큰 LOC 의 PR·커밋.

### 내 주간 (개인 심층 분석)
`$USER_EMAIL` 커밋으로: ① 커밋 수·LOC ② 집중 영역 Top 3 디렉토리 ③ 커밋 타입 믹스 ④ 테스트 비율 ⑤ 가장 큰 기여.

### 팀 분석 (멀티 기여자 시)
기여자가 2명 이상일 때만 쓴다. 본인 외 각 기여자에게 위 5항목을 그대로 적용.

### Top 3 이번 주 성과
Keep. 커밋 해시·제목을 인용해 무엇이 왜 좋았는지 쓴다.

### 개선할 3가지 (구체적, 커밋 기반)
Problem. 근거 커밋을 붙이고, 제안은 ROI(투자 조언) 프레이밍으로 — "이것에 시간을 투자할 가치가 있습니다" 식.

### 다음 주 습관 3가지 (5분 이내 실천 가능)
Try. 5분 안에 실천 가능한 **micro-habit**.

완료 기준: 헤드라인 + 10개 섹션 전부 + 성과·개선·습관 각 3개, 각 항목이 커밋 해시나 제목을 인용.

## 규칙
- 리포트는 한국어, LOC·시간은 50 단위 반올림.
- LOC(Lines of Code)·PR(Pull Request)은 요약 테이블에서 한 번만 풀어쓰고, 헤드라인은 축약 형식 그대로 둔다.
