## base 확정

레포 기본 브랜치(`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`)가 base다. stacked PR이면 base는 직전 스택 브랜치다. 사용자가 base를 지정했으면 그 값을 쓴다.

```bash
BASE={위에서 정한 base}
git -C {작업 디렉토리} fetch origin $BASE --quiet
```

## 측정

```bash
git -C {작업 디렉토리} diff origin/$BASE...HEAD --shortstat            # "N files changed, A insertions(+), D deletions(-)"
git -C {작업 디렉토리} diff origin/$BASE...HEAD --numstat | sort -rn   # 파일별 additions 내림차순
```

- `--shortstat`의 insertions 값이 판정 대상이다.
- `--numstat`의 정렬 상위 파일이 곧 분할 후보다.

## 판정

| insertions | 판정 | 괄호 문구 | 조치 |
|---|---|---|---|
| ~200 | PASS ✅ | `(최선 범위: ~200줄)` | 그대로 진행 |
| 201~300 | PASS ✅ | `(양호 범위: ~300줄)` | 그대로 진행 |
| 301~400 | WARNING ⚠️ | `(권장: 300줄 이하, 상한: 400줄)` | 파일별 내역을 보여주고 분할 여지를 한 줄로 언급한 뒤 진행 여부를 묻는다 |
| 401~ | FAIL ❌ | `(상한 400줄 초과: +{N-400}줄)` | 아래 분할 제안 |

판정은 두 줄로 낸다.

```
PR Size Check: {PASS ✅ | WARNING ⚠️ | FAIL ❌}
추가된 줄 수: {N}줄 {괄호 문구}
```

## FAIL 시 분할 제안

1. 파일별 additions를 많은 순 테이블로 보여준다.
2. 논리적으로 독립적인 커밋·변경 그룹으로 2개 이상의 PR 안을 만든다. 각 PR은 구현·테스트·migration을 한 덩어리로 담고, 뒤 PR이 쓸 공용 코드를 앞 PR로 먼저 빼는 것도 유효한 분할이다.
3. AskUserQuestion으로 고르게 한다: A) 제안대로 분할 B) 하나의 PR로 진행(사유 입력) C) 사용자가 분할 방법 지정. B의 사유는 받은 그대로 PR 본문·코멘트에 쓴다.
