---
name: new-session
description: 다음 작업을 새 세션에서 바로 시작할 셸 명령 한 줄을 모델·effort와 함께 만들어 보여 주고 클립보드에 복사한다.
disable-model-invocation: true
argument-hint: "[--model 모델] [--effort 레벨] [/스킬 인자 | 할 일]"
allowed-tools:
  - Bash(printf *)
  - Bash(pbcopy)
---

## 1. 값 확정

인자에서 `--model`·`--effort` 값을 떼고, 남은 글을 첫 프롬프트로 쓴다. 인자에 없는 값은 아래로 채운다.

- 첫 프롬프트: 이 대화에서 마지막으로 안내한 다음 단계 명령을 쓴다. 그것도 없으면 AskUserQuestion으로 무엇을 실행할지 묻는다.
- 모델: 이 세션 모델의 별칭(`opus`·`sonnet`·`haiku`·`fable`)을 쓴다.
- effort: `${CLAUDE_EFFORT}`를 쓴다.

디렉토리는 항상 `${CLAUDE_PROJECT_DIR}`를 쓴다. 첫 프롬프트가 슬래시 명령이 아니면, 새 세션이 이 대화 없이 시작할 수 있게 읽을 파일의 절대경로를 프롬프트에 넣는다.

→ 완료: 디렉토리·모델·effort·첫 프롬프트가 정해졌다.

## 2. 명령 조립

꼴: `cd {디렉토리} && claude --model {모델} --effort {effort} '{첫 프롬프트}'`

- 디렉토리가 홈 아래면 `~/…`로 쓰고, 경로에 영문·숫자·`/._-~` 밖의 글자가 있으면 작은따옴표로 감싼 절대경로로 쓴다.
- 첫 프롬프트 안의 `'`는 `'\''`로 바꾼다.

예: `cd ~/{프로젝트} && claude --model opus --effort max '/plan-review ~/plans/{주제}/notes/plan.md'`

→ 완료: 한 줄 명령이 만들어졌다.

## 3. 출력과 복사

`printf '%s' '{명령}' | pbcopy`로 클립보드에 넣는다. {명령} 자리에는 명령 안의 `'`를 모두 `'\''`로 바꾼 글을 넣는다.

명령을 bash 코드 블록 한 줄로 보여 주고, 그 아래에 "클립보드에 복사했습니다."를 쓴다. 복사가 실패했으면 그 줄 대신 에러 메시지를 쓴다.

→ 완료: 명령이 bash 코드 블록 한 줄로 보였고, 같은 문자열을 pbcopy로 복사했다.
