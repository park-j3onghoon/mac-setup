---
name: pr-size-check
version: 1.0.0
description: PR 생성 전에 추가된 코드가 200~400줄 이하인지 확인한다. 초과 시 분할을 제안한다.
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - AskUserQuestion
---

# PR Size Check

PR 생성 전에 추가된 코드(additions) 규모를 검증한다.

- **200줄 이하**: PASS (최선)
- **201~300줄**: PASS (양호)
- **301~400줄**: WARNING (허용하되 주의)
- **401줄 이상**: FAIL (분할 권장)

## 실행 방법

### 1. 추가된 줄 수 측정
```bash
git diff master...HEAD --stat
git diff master...HEAD --numstat | awk '{sum += $1} END {print sum}'
```
- `master` 대신 실제 base branch 사용
- additions(첫 번째 컬럼)만 합산

### 2. 결과 판정

#### 200줄 이하: PASS (최선)
```
PR Size Check: PASS ✅
추가된 줄 수: {N}줄 (최선 범위: ~200줄)
```
그대로 PR 생성을 진행한다.

#### 201~300줄: PASS (양호)
```
PR Size Check: PASS ✅
추가된 줄 수: {N}줄 (양호 범위: ~300줄)
```
그대로 PR 생성을 진행한다.

#### 301~400줄: WARNING
```
PR Size Check: WARNING ⚠️
추가된 줄 수: {N}줄 (권장: 300줄 이하, 상한: 400줄)
```
파일별 additions 내역을 보여주고, 분할 가능 여부를 간단히 언급한 뒤 진행 여부를 묻는다.

#### 401줄 이상: FAIL
```
PR Size Check: FAIL ❌
추가된 줄 수: {N}줄 (상한 400줄 초과: +{N-400}줄)
```

초과 시 아래를 수행:
1. **파일별 additions 내역**을 테이블로 보여준다 (많은 순 정렬)
2. **분할 제안**: 논리적으로 독립적인 커밋/변경 그룹을 분석해서 2개 이상의 PR로 나눌 수 있는 방안을 제시
3. AskUserQuestion으로 사용자에게 선택지를 제시:
   - A) 제안대로 PR 분할
   - B) 그래도 하나의 PR로 생성 (사유 입력)
   - C) 직접 분할 방법 지정

## 분할 제안 기준
- 테스트 파일과 구현 파일을 같은 PR에 유지 (테스트만 분리하지 않음)
- 독립적인 기능/모듈 단위로 분리
- migration 파일은 관련 모델 변경과 같은 PR에 유지
