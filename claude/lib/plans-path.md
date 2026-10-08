산출물은 `~/plans` 아래에 둔다.

```
~/plans/{작업명}/{레포}/
~/plans/{작업명}/notes/
```

## 첫 칸: 작업명

작업 하나에 디렉토리 하나다. kebab-case로 쓰고 이슈 ID가 있으면 앞에 붙인다. 레포가 여럿이어도 작업이 하나면 디렉토리도 하나다.

## 둘째 칸: 그 산출물이 어느 레포 것인가

- 레포 이름: 그 레포에 들어갈 변경을 다루는 산출물. `basename $(dirname $(git rev-parse --path-format=absolute --git-common-dir))`
- `notes`: 어느 레포에도 매이지 않는 산출물. 둘이 여기 온다. 레포를 하나도 안 건드리는 작업(조사·문서·발표 준비), 그리고 여러 레포에 걸쳐 하나로 써야 하는 것(전체 계획·결정 기록).

## HTML 파일

- 같은 경로에 파일이 있으면 `{이름}.{YYYYMMDD}.bak.html`로 백업한다. 백업과 덮어쓰기에 쓰는 복사는 `/bin/cp -f`로 한다. 셸의 `cp`는 `cp -i` 별칭이다.
- 저장한 뒤 `open {절대경로}`로 브라우저에 띄우고, 채팅에 절대경로를 알린다.

## 예

한 레포 안에서 끝나는 작업

```
~/plans/abc-123-payout-rounding/payments-api/plan.md
```

여러 레포에 걸치는 작업

```
~/plans/payout-automation/notes/plan.md           전체 계획
~/plans/payout-automation/notes/decisions.md
~/plans/payout-automation/payments-api/grpc-servicer-plan.md
~/plans/payout-automation/mobile-bff/bff-plan.md
```

레포를 안 건드리는 작업

```
~/plans/settlement-inquiry-stats/notes/analysis.md
```
