# Codex 교차 검증

codex-companion 플러그인을 Bash로 부른다.

```bash
CODEX_SCRIPT=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1)
```

## 모드

| 대상 | 명령 |
|---|---|
| diff 리뷰 | `node "$CODEX_SCRIPT" review --background [--base <ref>] [--scope auto\|working-tree\|branch]` |
| diff 적대 검증 | `node "$CODEX_SCRIPT" adversarial-review --background [--scope …] [focus text]` |
| diff가 없는 파일(계획서 등) 적대 검증 | `node "$CODEX_SCRIPT" task --effort high --background "<절대경로>를 읽고 설계 선택·가정·트레이드오프·실패 모드를 공격적으로 검증하라. git diff는 무시하라."` |

`adversarial-review`는 git diff 리뷰어다. 대응 diff가 없거나 무관한 변경이 섞여 있으면 그 diff를 리뷰하므로, 계획서만 있을 때는 `task`를 쓴다. Codex는 `--write` 없이 읽기 전용으로 부른다. `--help`는 인자로 주면 focus text로 먹혀 실제 job이 뜬다.

## 언제 무엇을 돌리나

diff 리뷰에 Codex를 더할지는 아래 셋 중에서 고른다.

- 건너뛰기: 변경 200줄 미만 + 루틴 수정
- `codex review`: 200줄 이상 또는 도메인·애플리케이션 레이어 변경
- `codex review` + `codex adversarial-review`: 새 추상화·레이어 도입, 마이그레이션 동반, 아키텍처 결정

## 실행과 회수

블로킹으로 도는 호출(`review`·`adversarial-review`와 아래 `status --wait`)은 Bash `run_in_background: true`로 띄운다.

1. `task`는 `--background`를 붙여 띄우고, 출력의 `started in the background as <id>`에서 job-id를 읽는다. `review`·`adversarial-review`는 결과를 stdout으로 회수하고, job-id가 필요하면 `status --all`에서 찾는다.
2. job-id가 있으면 반복 폴링 대신 블로킹 대기 한 줄로 완료를 기다린다.
   ```bash
   node "$CODEX_SCRIPT" status --wait <job-id> --timeout-ms 900000 --poll-interval-ms 5000
   ```
   대기가 끝났는데 job이 아직 진행 중이면 같은 명령을 다시 걸어 완료까지 간다.
3. `node "$CODEX_SCRIPT" result <job-id>`로 회수한다.
4. job의 phase가 `starting`에 머물고 진행 로그가 더 자라지 않으면 `cancel <job-id>`한 뒤 자체 적대 점검으로 대체하고 사용자에게 알린다.

완료는 그 job-id의 phase로만 판단한다.

## 대상 코드

diff 리뷰와 diff 적대 검증은 호출한 쪽이 준 대상 경로에서 실행한다: `(cd {대상 경로} && node "$CODEX_SCRIPT" review --background --base origin/{base})`. Codex 지적은 그 경로의 코드로 사실을 검증한 뒤 반영한다.

## 결과 취급

Codex 발견은 모두 원래 뜻대로 싣는다. Claude의 판단이 다르면 두 판단을 같이 적는다.
