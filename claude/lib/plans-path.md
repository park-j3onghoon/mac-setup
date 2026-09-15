# 작업 산출물 경로

산출물은 `~/plans` 아래에 둔다. 레포 밖이라 PR diff에 들어가지 않고 커밋되지 않는다.

```
~/plans/{작업명}/{레포}/
~/plans/{작업명}/notes/
```

## 첫 칸: 작업명

작업 하나에 디렉토리 하나다. kebab-case로 쓰고 이슈 ID가 있으면 앞에 붙인다(`set-253-payout-rounding`). 레포가 여럿이어도 작업이 하나면 디렉토리도 하나다.

## 둘째 칸: 그 산출물이 어느 레포 것인가

- **레포 이름**: 그 레포에 들어갈 변경을 다루는 산출물. `basename $(git rev-parse --show-toplevel)`
- **`notes`**: 어느 레포에도 매이지 않는 산출물. 둘이 여기 온다. 레포를 하나도 안 건드리는 작업(조사·문서·발표 준비), 그리고 여러 레포에 걸쳐 하나로 써야 하는 것(전체 계획·결정 기록).

레포 칸이 고정 깊이에 있어서 "이 레포의 계획"을 glob으로 찾을 수 있다: `~/plans/*/{레포}/plan.md`.

## 예

한 레포 안에서 끝나는 작업

```
~/plans/set-253-payout-rounding/payments-api/plan.md
```

여러 레포에 걸치는 작업. 계획은 쪼개지 않는다. 배포 순서가 계획의 핵심인데 파일을 나누면 그 순서가 사라진다.

```
~/plans/plb-22-payout-automation/notes/plan.md           전체 계획
~/plans/plb-22-payout-automation/notes/decisions.md
~/plans/plb-22-payout-automation/payments-api/grpc-servicer-plan.md
~/plans/plb-22-payout-automation/mobile-app/bff-plan.md
```

레포를 안 건드리는 작업

```
~/plans/settlement-inquiry-stats/notes/analysis.md
```

## 파일 이름

| 파일 | 만드는 곳 |
|---|---|
| `decisions.md` | `/grill` |
| `plan.md` | `/plan-review` |
| `security-report.md` | `/cso` |
| `security-review.md` | `/sec-review` |
| `explain.html` | `/explain-html` |
| RFC 초안 | `/rfc-write` |
