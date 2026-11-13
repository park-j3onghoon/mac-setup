---
name: refresh-session
description: 다음 작업을 새 프로세스의 빈 컨텍스트에서 잇는다. Claude Code는 지금 세션을 끄고 설치된 최신 버전으로 다시 띄우거나 새 탭 명령을 만들고, Codex는 새 세션 명령과 이어갈 프롬프트를 만든다.
disable-model-invocation: true
argument-hint: "[--tab] [--model 모델] [--effort 레벨] [/스킬 인자 | 할 일]"
allowed-tools:
  - Bash(bash ${CLAUDE_SKILL_DIR}/restart.sh *)
---

Codex에서 실행하면 `~/.claude/skills/refresh-session/codex.md`를 Read하고 그 절차를 수행한다. Claude Code에서는 아래 절차를 수행한다.

## 1. 값 확정

인자에서 `--tab`·`--model`·`--effort`를 떼고, 남은 글을 첫 프롬프트로 쓴다.

- 첫 프롬프트: 남은 글이 없으면 이 대화에서 마지막으로 안내한 다음 단계 명령을 쓴다. 그것도 없으면 AskUserQuestion으로 무엇을 실행할지 묻는다.
- 첫 프롬프트에는 슬래시 명령을 하나만 둔다. 한 입력에 둘이 있으면 Claude Code가 둘 다 실행한다.
- 첫 프롬프트가 슬래시 명령이 아니면, 새 세션이 이 대화 없이 시작할 수 있게 읽을 파일의 절대경로를 프롬프트에 넣는다.
- 모델: `--model` 값, 없으면 이 세션 모델의 별칭(`opus`·`sonnet`·`haiku`·`fable`)을 쓴다.
- effort: `--effort` 값, 없으면 `${CLAUDE_EFFORT}`를 쓴다.
- 권한 모드: 이 세션이 auto 모드면 `auto`, 아니면 `manual`을 쓴다.
- 디렉토리: 항상 `${CLAUDE_PROJECT_DIR}`를 쓴다.
- 모드: `--tab`이 있으면 새 탭(2절), 없으면 재시작(3절)이다.

→ 완료: 모드, 첫 프롬프트, 모델·effort·권한 모드·디렉토리가 정해졌다.

## 2. 새 탭

아래를 Bash 한 번으로 실행한다. 스크립트가 새 탭에서 칠 명령을 클립보드에 넣고 그 명령을 출력한다. 이 세션은 그대로 둔다. {첫 프롬프트} 안의 `'`는 `'\''`로 바꾼다.

```bash
bash ${CLAUDE_SKILL_DIR}/restart.sh tab '{디렉토리}' '{모델}' '{effort}' '{권한 모드}' '{첫 프롬프트}'
```

출력은 두 부분만 쓴다: 스크립트가 출력한 명령을 담은 bash 코드 블록 한 줄, 그 아래 "클립보드에 복사했습니다." 한 줄. 스크립트가 실패했으면 그 에러 메시지를 한 줄로 쓴다.

→ 완료: 명령이 bash 코드 블록 한 줄로 보였고, 같은 문자열이 클립보드에 있다.

## 3. 재시작

아래를 Bash 한 번으로 실행한다. 스크립트가 `claude agents` 목록에서 이 세션의 종류를 보고, 지금 Claude Code를 끈 뒤 설치된 최신 버전으로 첫 프롬프트를 실행한다. `"$PPID"`는 이 세션의 Claude Code 프로세스다. {첫 프롬프트} 안의 `'`는 `'\''`로 바꾼다.

```bash
bash ${CLAUDE_SKILL_DIR}/restart.sh restart '{디렉토리}' '{모델}' '{effort}' '{권한 모드}' "$PPID" '{첫 프롬프트}'
```

출력은 스크립트가 출력한 줄만 그대로 쓴다. 스크립트가 실패했으면 그 에러 메시지를 한 줄로 쓰고 다시 실행하지 않는다.

→ 완료: 스크립트가 0으로 끝났고, 그 출력이 그대로 보였다.
