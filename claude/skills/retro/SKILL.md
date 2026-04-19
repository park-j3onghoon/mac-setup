---
name: retro
version: 1.0.0
description: 주간 엔지니어링 회고. 커밋 이력, 작업 패턴, 코드 품질 메트릭을 분석한다. "주간 회고", "이번 주 뭐 했지" 등으로 트리거.
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - AskUserQuestion
---

# /retro — 주간 엔지니어링 회고

## 인자
- `/retro` — 기본: 최근 7일
- `/retro 14d` — 최근 14일
- `/retro 30d` — 최근 30일

## Step 1: 데이터 수집

```bash
git fetch origin --quiet
USER_NAME=$(git config user.name)
USER_EMAIL=$(git config user.email)
DEFAULT=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo main)
```

아래 명령을 **병렬 실행**:
```bash
# 커밋 + stat
git log origin/$DEFAULT --since="<window>" --format="%H|%aN|%ae|%ai|%s" --shortstat

# 테스트 vs 프로덕션 LOC
git log origin/$DEFAULT --since="<window>" --format="COMMIT:%H|%aN" --numstat

# 타임스탬프 (세션 감지용)
git log origin/$DEFAULT --since="<window>" --format="%at|%aN|%ai|%s" | sort -n

# 핫스팟
git log origin/$DEFAULT --since="<window>" --format="" --name-only | grep -v '^$' | sort | uniq -c | sort -rn | head -15

# 작성자별 커밋 수
git shortlog origin/$DEFAULT --since="<window>" -sn --no-merges
```

## Step 2: 메트릭 계산

| 메트릭 | 값 |
|---|---|
| 메인 커밋 수 | N |
| 기여자 | N |
| 총 insertions / deletions | +N / -N |
| 테스트 LOC 비율 | N% |
| 활동일 | N |
| 감지된 세션 | N |

## Step 3: 커밋 시간 분포

시간대별 히스토그램 (로컬 시간):
```
Hour  Commits
 09:    5      █████
 10:    8      ████████
 14:   12      ████████████
 22:    3      ███
```

피크 시간, 데드존, 야간 코딩 패턴 식별.

## Step 4: 작업 세션 감지

**45분 갭**으로 세션 구분. 각 세션:
- 시작/종료 시간, 커밋 수, 기간
- 분류: **Deep**(50분+), **Medium**(20-50분), **Micro**(<20분)
- 총 활동 코딩 시간, 평균 세션 길이, 시간당 LOC

## Step 5: 커밋 타입 분류

Conventional commit prefix (feat/fix/refactor/test/chore/docs) 별 비율:
```
feat:     20  (40%)  ████████████████████
fix:      27  (54%)  ███████████████████████████
```
fix 비율 > 50%면 경고 — "빠르게 배포, 빠르게 수정" 패턴.

## Step 6: 핫스팟 분석

가장 많이 변경된 파일 Top 10. 5회 이상 변경 = 청크 핫스팟 경고.

## Step 7: Focus Score

가장 많이 변경된 최상위 디렉토리의 커밋 비율. 높을수록 집중, 낮을수록 컨텍스트 스위칭.

## Step 8: Ship of the Week

기간 내 가장 큰 LOC의 PR/커밋 하이라이트.

## Step 9: 기여자별 분석

각 기여자(본인 포함):
1. 커밋 수, LOC
2. 집중 영역 (Top 3 디렉토리)
3. 커밋 타입 믹스
4. 테스트 비율
5. 가장 큰 기여

## Step 10: 연속 출근 (Shipping Streak)

```bash
git log origin/$DEFAULT --format="%ad" --date=format:"%Y-%m-%d" | sort -u
```
오늘부터 역순으로 몇 일 연속 커밋이 있는지.

## 출력 구조

**1줄 요약** (첫 줄):
```
이번 주: 47 커밋, 3.2k LOC, 38% 테스트, 12 PR, 피크: 오후 10시 | 연속: 47일
```

### 요약 테이블
### 시간 & 세션 패턴
### 배포 속도
### 코드 품질 신호
### Focus & 하이라이트
### 내 주간 (개인 심층 분석)
### 팀 분석 (멀티 기여자 시)
### Top 3 이번 주 성과
### 개선할 3가지 (구체적, 커밋 기반)
### 다음 주 습관 3가지 (5분 이내 실천 가능)

## 톤
- 격려하되 솔직. 구체적으로 — 항상 실제 커밋에 근거.
- 일반적 칭찬("좋은 작업!") 금지 — 무엇이 왜 좋았는지 정확히.
- 개선 제안은 투자 조언처럼 — "이것에 시간을 투자할 가치가 있습니다" 식.
- 3000-4500 단어.

## 중요 규칙
- `origin/$DEFAULT` 사용 (로컬 main은 오래됐을 수 있음)
- 타임스탬프는 로컬 시간대
- 커밋 0개면 다른 기간 제안
- LOC/시간은 50 단위 반올림
