# 다른 AI 교차 검증

지금 도는 에이전트가 Claude면 Codex로, Codex면 Claude로 검증한다. 다른 AI는 읽기 전용으로 부른다. 대상에 따라 diff 리뷰, diff 적대 검증, diff가 없는 파일 적대 검증 가운데 한 행을 쓴다.

## Claude에서 Codex로

codex-companion 플러그인을 Bash로 부른다.

```bash
CODEX_SCRIPT=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | head -1)
```

| 대상 | 명령 |
|---|---|
| diff 리뷰 | `node "$CODEX_SCRIPT" review --background [--base <ref>] [--scope auto\|working-tree\|branch]` |
| diff 적대 검증 | `node "$CODEX_SCRIPT" adversarial-review --background [--scope …] [focus text]` |
| diff가 없는 파일(계획서 등) 적대 검증 | `node "$CODEX_SCRIPT" task --background "<절대경로>를 읽고 설계 선택·가정·트레이드오프·실패 모드를 공격적으로 검증하라. git diff는 무시하라."` |

대응 diff가 없거나 무관한 변경이 섞여 있으면 `task`를 쓴다. Codex는 `--write` 없이 읽기 전용으로 부른다. 모델·effort는 `--model`·`--effort` 없이 `~/.codex/config.toml`의 값(Fast 포함)을 쓴다. 사용법은 위 표에서 찾는다: adversarial-review·task 뒤에 붙인 `--help`나 모르는 옵션은 리뷰 초점·작업 지시로 들어가 실제 job이 뜬다.

### 실행과 회수

블로킹으로 도는 호출(`review`·`adversarial-review`와 아래 `status --wait`)은 Bash `run_in_background: true`로 띄운다.

1. `task`는 `--background`를 붙여 띄우고, 출력의 `started in the background as <id>`에서 job-id를 읽는다. `review`·`adversarial-review`는 결과를 stdout으로 회수하고, job-id는 띄운 뒤 `status --all`에서 찾는다. `status`·`result`·`cancel`은 job을 띄운 경로에서 부른다.
2. job-id로 5분씩 끊어 완료를 기다린다.
   ```bash
   node "$CODEX_SCRIPT" status --wait <job-id> --timeout-ms 300000 --poll-interval-ms 5000
   ```
   대기가 끝났는데 job이 아직 진행 중이면 상태와 마지막 진행 기록 뒤 지난 초를 본다.
   ```bash
   node "$CODEX_SCRIPT" status <job-id> --json | python3 -c 'import json,os,sys,time; j=json.load(sys.stdin)["job"]; print(j["status"], int(time.time() - os.path.getmtime(j["logFile"])))'
   ```
   300초 미만이면 대기 명령을 다시 건다. 300초 이상이면 멈춘 job으로 보고 4로 간다.
3. `node "$CODEX_SCRIPT" result <job-id>`로 회수한다. phase가 `failed`면 4로 간다.
4. 멈춘 job은 `cancel <job-id>`한다. 멈추거나 실패한 job은 어느 명령이 멈췄거나 실패했는지(실패면 오류 원문)를 사용자에게 알리고 자체 적대 점검으로 대체한다.

완료는 그 job-id의 phase로만 판단한다.

### 대상 경로

diff 리뷰와 diff 적대 검증은 호출한 쪽이 준 대상 경로에서 실행한다: `(cd {대상 경로} && node "$CODEX_SCRIPT" review --background --base origin/{base})`.

## Codex에서 Claude로

`claude -p`를 Bash로 부르고 도구는 `--allowedTools "Read,Grep,Glob"`만 준다. 결과는 stdout으로 받는다.

| 대상 | 명령 |
|---|---|
| diff 리뷰 | `(cd {대상 경로} && git diff origin/{base}...HEAD \| claude -p "이 diff를 리뷰하라. 버그·회귀·빠진 테스트를 file:line과 함께 낸다." --allowedTools "Read,Grep,Glob")` |
| diff 적대 검증 | `(cd {대상 경로} && git diff origin/{base}...HEAD \| claude -p "이 diff가 실제 운영에서 어떻게 깨질 수 있는지 공격적으로 검증하라. {리뷰 초점}" --allowedTools "Read,Grep,Glob")` |
| diff가 없는 파일(계획서 등) 적대 검증 | `claude -p "<절대경로>를 읽고 설계 선택·가정·트레이드오프·실패 모드를 공격적으로 검증하라." --allowedTools "Read,Grep,Glob"` |

10분 안에 끝나지 않거나 0이 아닌 코드로 끝나면, 그 사실과 오류 원문을 사용자에게 알리고 자체 적대 점검으로 대체한다.

## 결과 취급

다른 AI의 발견은 모두 원래 뜻대로 싣는다. 내 판단이 다르면 두 판단을 같이 적는다. diff 리뷰와 diff 적대 검증의 발견은 대상 경로의 코드로 사실을 검증한 뒤 반영한다.
