---
name: refresh-session
description: 다음 작업을 빈 컨텍스트에서 잇는다. 인자가 없으면 지금 탭의 대화를 /clear로 비우고 다음 명령을 이어서 실행하고, --tab이면 새 탭에서 시작할 셸 명령 한 줄을 모델·effort와 함께 만들어 복사한다.
disable-model-invocation: true
argument-hint: "[--tab] [--model 모델] [--effort 레벨] [/스킬 인자 | 할 일]"
allowed-tools:
  - Bash(printf *)
  - Bash(pbcopy)
  - Bash(mkdir -p *)
  - Bash(cmux send *)
  - Bash(cmux send-key *)
  - Bash(rm -f ~/.claude/state/refresh-session/*)
---

## 1. 값 확정

인자에서 `--tab`·`--model`·`--effort`를 떼고, 남은 글을 첫 프롬프트로 쓴다.

- 첫 프롬프트: 남은 글이 없으면 이 대화에서 마지막으로 안내한 다음 단계 명령을 쓴다. 그것도 없으면 AskUserQuestion으로 무엇을 실행할지 묻는다.
- 첫 프롬프트에는 슬래시 명령을 하나만 둔다. 한 입력에 둘이 있으면 Claude Code가 둘 다 실행한다.
- 첫 프롬프트가 슬래시 명령이 아니면, 새 컨텍스트가 이 대화 없이 시작할 수 있게 읽을 파일의 절대경로를 프롬프트에 넣는다.
- 모드: `--tab`·`--model`·`--effort` 중 하나라도 있으면 새 탭(2절), 없으면 같은 탭(3절)이다. 같은 탭은 지금 세션의 모델·effort를 그대로 쓴다.

→ 완료: 모드와 첫 프롬프트가 정해졌다.

## 2. 새 탭

인자에 없는 값은 아래로 채운다.

- 모델: 이 세션 모델의 별칭(`opus`·`sonnet`·`haiku`·`fable`)을 쓴다.
- effort: `${CLAUDE_EFFORT}`를 쓴다.
- 디렉토리: 항상 `${CLAUDE_PROJECT_DIR}`를 쓴다.

명령은 `cd {디렉토리} && claude --model {모델} --effort {effort} '{첫 프롬프트}'` 꼴로 조립한다.

- 디렉토리가 홈 아래면 `~/…`로 쓰고, 경로에 영문·숫자·`/._-~` 밖의 글자가 있으면 작은따옴표로 감싼 절대경로로 쓴다.
- 첫 프롬프트 안의 `'`는 `'\''`로 바꾼다.

예: `cd ~/{프로젝트} && claude --model opus --effort max '/plan-review ~/plans/{주제}/notes/plan.md'`

`printf '%s' '{명령}' | pbcopy`로 클립보드에 넣는다. {명령} 자리에는 명령 안의 `'`를 모두 `'\''`로 바꾼 글을 넣는다.

출력은 두 부분만 쓴다: 명령을 담은 bash 코드 블록 한 줄, 그 아래 "클립보드에 복사했습니다." 한 줄. 복사가 실패했으면 아래 줄 대신 에러 메시지를 한 줄로 쓴다.

→ 완료: 명령이 bash 코드 블록 한 줄로 보였고, 같은 문자열을 pbcopy로 복사했다.

## 3. 같은 탭

모델은 `/clear`를 직접 실행할 수 없으므로, cmux가 이 탭에 사용자 입력처럼 쳐 넣는다. 이 턴에서 `/clear`를 입력하면 명령이라 턴이 끝날 때까지 큐에서 기다린다. 턴이 끝나 `/clear`가 돌면, SessionStart(`clear`) 훅 `~/.claude/hooks/refresh-session-continue.sh`가 표시 파일의 첫 프롬프트를 입력한다.

`CMUX_SURFACE_ID`가 비었으면 cmux 밖이다. `printf '%s' '{첫 프롬프트}' | pbcopy`로 첫 프롬프트를 복사하고, 첫 프롬프트를 담은 bash 코드 블록 한 줄과 "`/clear` 뒤 붙여 넣으세요. 클립보드에 복사했습니다." 한 줄만 출력한 뒤 멈춘다.

cmux 안이면 아래를 Bash 한 번으로 실행한다. {첫 프롬프트} 안의 `'`는 `'\''`로 바꾼다. `--surface`는 빼지 않는다: 이 값이 `/clear`를 받을 탭을 정한다.

```bash
mkdir -p ~/.claude/state/refresh-session && printf '%s' '{첫 프롬프트}' > ~/.claude/state/refresh-session/"$CMUX_SURFACE_ID" && cmux send --surface "$CMUX_SURFACE_ID" -- /clear && cmux send-key --surface "$CMUX_SURFACE_ID" enter
```

출력은 한 줄만 쓴다: "이 턴이 끝나면 대화를 비우고 `{첫 프롬프트}`를 이어서 실행합니다." 실행이 실패했으면 `rm -f ~/.claude/state/refresh-session/"$CMUX_SURFACE_ID"`로 표시 파일을 지우고, 그 줄 대신 에러 메시지를 한 줄로 쓴다.

→ 완료: 표시 파일이 생겼고, `/clear`가 큐에 들어갔고, 한 줄을 출력했다.
