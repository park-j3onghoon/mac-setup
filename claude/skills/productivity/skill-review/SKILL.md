---
name: skill-review
description: 스킬이 구조 규약과 실행 기준을 지키는지 점검하고, 어긋난 곳을 고칠 안을 낸다.
disable-model-invocation: true
argument-hint: "[스킬 이름 | 전체]"
---

# /skill-review: 스킬 점검

스킬 하나 또는 전체를 구조 규약(어디에 있고 어디에 등록됐나)과 실행 기준(AI가 그대로 실행할 수 있나)으로 점검한다. 고치는 것은 승인 후에만 한다.

## 1. 대상 확정

인자가 스킬 이름이면 그 하나, 그 외에는 아래 두 곳의 모든 `SKILL.md`를 대상으로 한다.

- `~/git/mac-setup/claude/skills/{engineering,productivity}/` (공개, 버킷 있음)
- `~/git/mac-setup/private/claude/skills/*/` (회사)

→ 완료: 점검할 `SKILL.md` 경로 목록이 확정됐다.

## 2. 구조 규약

아래 항목별로 판정한다.

버킷과 등록
- 공개 레포 스킬은 `engineering/`(일상적인 코드 작업) 또는 `productivity/`(일상적인 비코드 업무 도구) 아래에 있다. 버킷은 레포 안에서만 쓴다. 하네스는 `~/.claude/skills/<이름>/SKILL.md` 한 단계만 탐색하므로 `install.sh`가 버킷을 순회해 평평하게 심링크한다.
- 버킷에 있는 모든 스킬은 최상위 `README.md`에 항목이 있고, 스킬 이름이 그 `SKILL.md`로 링크돼 있다.
- 각 버킷 폴더에 `README.md`가 있고, 그 버킷의 모든 스킬을 한 줄 설명과 함께 나열하며, 스킬 이름이 `SKILL.md`로 링크돼 있다.
- 회사 스킬은 `private/claude/skills/` 바로 아래에 두고 목록도 그 트리 안에서만 관리한다(공개 레포다).

호출 방식
- 모든 `SKILL.md`는 user-invoked다: `disable-model-invocation: true`. 프론트매터에 두는 것은 이 다섯뿐이다: `name`·`description`(사람이 읽을 한 줄)·`disable-model-invocation`, 필요하면 `argument-hint`, 그리고 전역 allow에 없는 도구를 그 스킬 범위에서만 열 때의 `allowed-tools`.
- user-invoked 스킬은 하위 모듈만 포인터로 읽는다. 스킬을 부르는 것은 사람뿐이다.

하위 모듈
- `SKILL.md`가 아닌 `.md`는 스킬 디렉토리 안(그 스킬 전용) 또는 `claude/lib/`·`~/.claude/lib/`(둘 이상이 공유)에 있다.
- 하위 모듈은 내용만 담는다. 소비자는 `grep -rl`로 찾는다.
- 스킬은 쓰는 모듈을 포인터로 밝힌다. `~/.claude/CLAUDE.md`가 이미 로드하는 모듈이어도 지우지 않는다(Codex와 `grep -rl`이 포인터를 본다).
- 포인터는 「`경로`를 Read하고 …」 평문으로 쓴다. 같은 파일을 두 번 읽지 않게 하는 일은 `~/.claude/CLAUDE.md`의 전역 규칙 한 줄이 맡는다.
- 모든 답에 쓰이는 규칙만 `~/.claude/CLAUDE.md`에서 import한다. 일부 답에만 쓰이는 규칙은 그 조건을 적은 포인터로 읽는다.

기계 검사 셋을 돌려 결과를 붙인다.

```bash
bash ~/git/mac-setup/scripts/check-layers.sh
bash ~/git/mac-setup/scripts/verify.sh
bash ~/git/mac-setup/scripts/check-pair.sh
```

→ 완료: 항목마다 OK 또는 위반이 판정됐고, 스크립트 셋의 출력이 붙었다.

## 3. 실행 기준

`SKILL.md`는 AI가 실행하는 문서다. 스킬마다 아래 셋을 판정한다.

- 핵심 제약: 기본 동작과 달라지게 만드는 사실이 본문에 있다(예: grill의 "사실은 내 몫, 결정은 사용자 몫").
- 완료 기준: 단계마다 끝났다고 판정할 한 줄(`→ 완료:` 등)이 있고, 마지막 완료 기준이 곧 성공한 모습이다.
- 사람용 문장 없음: 사람만 돕는 머리말·표·형제 경계 문장·자주 나온 질문이 없다. 사람용 설명은 description과 README 한 줄로 둔다. 표는 AI가 따르는 규칙·분기·출력 형식이면 둔다. 다음 스킬을 권하고 멈추라는 지시는 AI 동작이라 둔다.

→ 완료: 스킬마다 세 항목이 충족/미충족으로 판정됐고, 미충족이면 더하거나 지울 문장이 적혔다.

## 4. 4단계 체크리스트

- 트리거: description이 사람용 한 줄인가. 동의어 나열이 남았나.
- 구조: 절차와 참고가 갈렸나. 특정 분기에서만 쓰는 참고가 본문에 남았나. 여러 스킬에 같은 내용이 있으면 lib 모듈로 뽑았나.
- 유도: 모델이 이미 아는 단어로 압축했나. 지시가 긍정형인가(부정문이면 짝이 되는 긍정형 지시가 붙어 있나). 포인터에 무엇을 하러 가는지 한 구절을 붙였나(모듈의 절 이름만 부르지 않나).
- 가지치기: 지워도 행동이 안 바뀌는 문장(무동작), 같은 말의 반복, 이제는 사실이 아닌 문장. 줄번호·커밋 해시·수치처럼 코드가 바뀌면 틀려지는 것이 박혀 있으면 파일 경로까지로 줄인다(쓸 때 확인해 적는다). 같은 규칙이 다른 파일에도 있으면 한 곳만 남기고 포인터로 바꾼다. 예시가 그 파일의 규칙을 어기지 않나.

→ 완료: 네 항목마다 지적 또는 "해당 없음"이 적혔다.

## 5. 리포트와 반영

```
SKILL REVIEW: {스킬} ({N}줄)
구조     OK / 위반 N건
실행     3항목 중 N개 충족
체크리스트 트리거 N · 구조 N · 유도 N · 가지치기 N

[위반] {파일}:{줄} {무엇이 어긋났나} → {고칠 안}
```

고칠 안을 보여주고 AskUserQuestion으로 승인받은 항목만 Edit로 반영한다.

스킬을 추가·개명·제거하는 수정이면 아래도 같이 처리한다.

1. 버킷 `README.md`(`claude/skills/{engineering,productivity}/README.md`)와 최상위 `README.md`의 스킬 목록. 각 항목은 스킬 이름을 그 `SKILL.md`로 링크한다.
2. Codex에도 둘 스킬이면 `install.sh`의 Codex 절에 이름을 넣는다. 사본을 만들지 않고 같은 `SKILL.md`를 링크한다.
3. 기계 검사 셋이 다시 PASS인지.

→ 완료: 리포트를 냈고, 승인받은 항목만 반영됐으며, 반영 후 기계 검사 셋이 다시 PASS다.

## 참고

상위 레포(`mattpocock/skills`) 관례와 다른 점은 `reference/upstream-diff.md`에 있다. 판단 근거가 필요할 때만 Read한다.
