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

`adversarial-review`는 git diff 리뷰어다. 대응 diff가 없거나 무관한 변경이 섞여 있으면 그 diff를 리뷰하므로, 계획서만 있을 때는 `task`를 쓴다. `--write`는 쓰지 않는다(읽기 전용). `--help`는 인자로 주면 focus text로 먹혀 실제 job이 뜬다.

## 실행과 회수

블로킹으로 도는 호출(`review`·`adversarial-review`와 아래 `status --wait`)은 Bash `run_in_background: true`로 띄운다. Bash 도구 timeout(기본 120s)이 Codex 실행 길이를 자르지 않게 하려는 것이다.

1. `task --background`는 detached worker로 큐잉되고 출력에 job-id를 찍는다(`started in the background as <id>`). `--background`를 빼면 포그라운드 자식 프로세스로 돌아 job-id 없이 결과만 나오고 호출한 셸이 끝나면 같이 죽는다(회수·취소 불가). `review`·`adversarial-review`는 `--background`를 인자로 받지만 1.0.4 기준 무시하고 포그라운드로 완주해 결과를 stdout에 찍으므로, 이 둘은 그 stdout으로 회수하고 job-id가 필요하면 `status --all`에서 찾는다.
2. job-id가 있으면 반복 폴링 대신 블로킹 대기 한 줄로 완료를 기다린다.
   ```bash
   node "$CODEX_SCRIPT" status --wait <job-id> --timeout-ms 900000 --poll-interval-ms 5000
   ```
   대기가 끝났는데 job이 아직 진행 중이면 대기 창이 닫힌 것일 뿐이므로 같은 명령을 다시 걸어 완료까지 간다. Codex 실행 시간에는 상한을 두지 않는다(`--timeout-ms`를 생략하면 기본 4분이라 재대기가 잦아진다).
3. `node "$CODEX_SCRIPT" result <job-id>`로 회수한다.
4. stall(phase가 `starting`에 머물고 진행 로그가 더 자라지 않음)이면 `cancel <job-id>` 후 자체 적대 점검으로 대체하고 사용자에게 알린다.

`status --all`의 'running' 문자열은 다른 job에도 매칭되므로 완료 판단에 쓰지 않는다. 특정 job-id의 phase만 본다.

## 대상 코드 기준

Codex는 체크아웃된 working tree를 읽는다. 대상 브랜치가 이미 체크아웃돼 있으면 그대로 실행하고, 아니면 격리된 워크트리에서 실행해 사용자 clone의 브랜치·HEAD를 건드리지 않는다.

```bash
WT=$(mktemp -d)/pr; git worktree add --detach "$WT" origin/<head>
# 그 디렉토리에서 Codex 실행
git worktree remove "$WT"
```

프롬프트에 "코드 인용은 브랜치 X 기준(`git show X:path`)"을 명시하면 오탐이 줄고, Codex 지적은 대상 브랜치 코드로 사실 검증한 뒤 반영한다.

## 결과 취급

Codex stdout은 원본 그대로 제시·첨부한다(요약·paraphrase 없이). 통합 리포트에서는 별도 블록으로 붙인다.
