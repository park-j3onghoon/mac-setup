# mac-setup 레포 규칙

이 레포를 고칠 때 지켜야 할 정합성 규칙이다. 이 레포가 배포하는 내용(전역 규칙·코드 규칙·스킬)은 `claude/CLAUDE.md`와 `claude/coding-rules*.md`에 있다.

## 스킬 구조

스킬은 `claude/skills/` 아래 버킷 폴더로 정리한다.

- `engineering/`: 일상적인 코드 작업
- `productivity/`: 일상적인 비(非)코드 워크플로 도구

버킷은 이 레포 안에서만 쓴다. 하네스는 `~/.claude/skills/<이름>/SKILL.md` 한 단계만 탐색하므로 `install.sh`가 버킷을 순회해 **평평하게** 심링크한다. 회사 전용 스킬은 이 레포에 두지 않는다(공개 레포다). 그것들은 `~/.claude/skills/`(로컬 실제 파일) 또는 `~/example/.claude/skills/`에 있고 버킷을 갖지 않는다.

모든 `SKILL.md`는 사용자 호출이다(`disable-model-invocation: true`). 모델이 스스로 부르는 스킬은 두지 않는다. 프론트매터는 `name`·`description`(사람이 읽을 한 줄)·`disable-model-invocation`·필요하면 `argument-hint`만 둔다. `version`·`context`·전역 허용과 겹치는 `allowed-tools`는 쓰지 않는다.

하위 모듈은 `SKILL.md`가 아닌 `.md` 파일이다. 스킬 디렉토리 안(그 스킬만 쓰는 것) 또는 `claude/lib/`(둘 이상이 공유하는 것)에 둔다. 하위 모듈은 스킬을 실행하지 않고, 자기를 읽는 스킬 목록도 갖지 않는다. 그 목록은 스킬이 바뀌는 순간 거짓이 되고, 소비자는 `grep -rl`로 찾으면 된다.

## 스킬을 추가·개명·제거할 때 같이 고칠 것

1. 최상위 `README.md`의 스킬 목록. 각 항목은 스킬 이름을 그 `SKILL.md`로 링크한다.
2. `claude/CLAUDE.md`의 스킬 표. 이 표가 라우터다. 스킬 설명문이 컨텍스트에 없으므로, 언급조차 없는 새 스킬이나 사라진 스킬로 보내는 줄은 거짓말을 하는 라우터다.
3. 페어인 `codex/AGENTS.md`. Codex에 없는 스킬이면 "Claude Code 전용" 목록에 넣는다.
4. `bash scripts/verify.sh`·`bash scripts/check-layers.sh`·`bash scripts/check-pair.sh`. 셋 다 PASS여야 한다.

## 문장부호

이 레포의 산문(`SKILL.md`, `claude/**/*.md`, `README.md`, 커밋 메시지)에는 em-dash(`—`)를 쓰지 않는다. 문장이 em-dash를 쓰려 하면 쉼표·콜론·마침표·괄호·접속사 중 그 문장이 실제로 원하는 것으로 다시 쓴다. 기계적인 문자 치환은 하지 않는다.

예외는 외부 서식을 그대로 옮겨 적은 곳뿐이다(예: `~/example/.claude/skills/linear-card/SKILL.md`의 Linear 카드 제목·근거 표기 규격). 그건 우리 산문이 아니라 인용이다.

## 설치

`bash install.sh`는 멱등이다. 레포의 `claude/*.md`·`claude/*.sh`·`settings.json`·`claude/lib/*`·`claude/hooks/*`와 버킷 안 스킬을 각각 심링크하고, 대상이 사라진 심링크는 지운다. 파일을 새로 추가할 때 `install.sh`를 고칠 필요는 없다. 버킷이나 최상위 디렉토리를 새로 만들 때만 고친다.
