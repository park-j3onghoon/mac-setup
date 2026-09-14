---
name: skill-review
description: 스킬이 구조 규약과 문서 기준을 지키는지 점검하고, 어긋난 곳을 고칠 안을 낸다.
disable-model-invocation: true
argument-hint: "[스킬 이름 | 전체]"
---

# /skill-review: 스킬 점검

스킬 하나 또는 전체를 **구조 규약**(어디에 있고 어디에 등록됐나)과 **문서 기준**(읽을 만한가)으로 점검한다. 고치는 것은 승인 후에만 한다.

## 1. 대상 확정

인자가 스킬 이름이면 그 하나, `전체`면 아래 세 곳의 모든 `SKILL.md`를 대상으로 한다. 인자가 없으면 최근에 만들었거나 고친 스킬을 `git log --oneline -20 -- claude/skills example/claude/skills` 로 찾아 제시하고 고르게 한다.

- `~/git/mac-setup/claude/skills/{engineering,productivity}/` (공개, 버킷 있음)
- `~/git/mac-setup/example/claude/skills/` (회사, git 미추적, 버킷 없음)
- `~/example/.claude/skills/` (회사 워크스페이스)

→ 완료: 점검할 `SKILL.md` 경로 목록이 확정됐다.

## 2. 구조 규약

`~/git/mac-setup/CLAUDE.md`가 정본이다. 아래를 항목별로 판정한다.

**버킷과 등록**
- 공개 레포 스킬은 `engineering/`(일상적인 코드 작업) 또는 `productivity/`(일상적인 비코드 업무 도구) 아래에 있다.
- 버킷에 있는 모든 스킬은 최상위 `README.md`에 항목이 있고, **스킬 이름이 그 `SKILL.md`로 링크**돼 있다.
- 각 버킷 폴더에 `README.md`가 있고, 그 버킷의 모든 스킬을 한 줄 설명과 함께 나열하며, 스킬 이름이 `SKILL.md`로 링크돼 있다.
- 회사 스킬은 버킷을 쓰지 않고 최상위 `README.md`에도 올리지 않는다(공개 레포다).

**호출 방식**
- 모든 `SKILL.md`는 user-invoked다: `disable-model-invocation: true`. 프론트매터는 `name`·`description`(사람이 읽을 한 줄)·`disable-model-invocation`·필요하면 `argument-hint`뿐이다. `version`·`context`·전역 허용과 겹치는 `allowed-tools`는 없다.
- user-invoked 스킬은 다른 스킬을 실행하지 않는다. 하위 모듈만 포인터로 읽는다.

**하위 모듈**
- `SKILL.md`가 아닌 `.md`는 스킬 디렉토리 안(그 스킬 전용) 또는 `claude/lib/`·`~/example/.claude/lib/`(둘 이상이 공유)에 있다.
- 하위 모듈은 스킬을 실행하지 않고, 자기를 읽는 스킬 목록도 갖지 않는다.

기계 검사 셋을 돌려 결과를 붙인다.

```bash
bash ~/git/mac-setup/scripts/check-layers.sh
bash ~/git/mac-setup/scripts/verify.sh
bash ~/git/mac-setup/scripts/check-pair.sh
```

→ 완료: 항목마다 OK 또는 위반이 판정됐고, 스크립트 셋의 출력이 붙었다.

## 3. 문서 기준

완성된 스킬은 읽는 사람이 네 가지를 답할 수 있어야 한다. 상세 기준은 `reference/docs-sections.md`를 Read한다.

| 섹션 | 답해야 하는 것 |
|---|---|
| What it does | 한 문장 역할 + **defining constraint**(기본 동작과 달라지는 그 한 가지 사실) |
| When to reach for it | 호출 방식 + 언제 손이 가나 + 헷갈리는 형제와의 경계 |
| Common questions | 실제로 나온 질문. 지어낸 질문으로 채우지 않는다 |
| It's working if | 잘 돌았을 때 눈에 보이는 것 |

우리는 별도 문서 페이지를 두지 않는다(읽을 사이트가 없다). 대신 **`SKILL.md`만 읽고 네 가지에 답할 수 있는지**를 기준으로 본다. 답이 안 나오는 항목이 그 스킬의 구멍이다.

→ 완료: 스킬마다 네 항목이 답변 가능/불가로 판정됐고, 불가한 항목은 어느 문장을 더해야 하는지 적혔다.

## 4. 4단계 체크리스트

- **트리거**: description이 사람용 한 줄인가. 동의어 나열이 남았나.
- **구조**: 절차와 참고가 갈렸나. 특정 분기에서만 쓰는 참고가 본문에 남았나. 단계마다 완료 기준이 있나.
- **유도**: 모델이 이미 아는 단어(leading word)로 압축했나. 부정문이 긍정형 지시 없이 홀로 있나.
- **가지치기**: 지워도 행동이 안 바뀌는 문장(무동작), 같은 말의 반복, 이제는 사실이 아닌 문장.
- **문장부호**: `~/.claude/lib/answer-style.md`의 「문장부호」를 Read하고 em-dash 사용 여부를 본다.

→ 완료: 네 항목마다 지적 또는 "해당 없음"이 적혔다.

## 5. 리포트와 반영

```
SKILL REVIEW: {스킬} ({N}줄)
구조     OK / 위반 N건
문서     4항목 중 N개 답변 가능
체크리스트 트리거 N · 구조 N · 유도 N · 가지치기 N

[위반] {파일}:{줄} {무엇이 어긋났나} → {고칠 안}
```

고칠 안을 보여주고 AskUserQuestion으로 승인받은 항목만 Edit로 반영한다. 스킬을 추가·개명·제거하는 수정이면 `~/git/mac-setup/CLAUDE.md`의 "스킬을 추가·개명·제거할 때 같이 고칠 것" 목록도 함께 처리한다.

→ 완료: 리포트를 냈고, 승인받은 항목만 반영됐으며, 반영 후 기계 검사 셋이 다시 PASS다.

## 상위 관례와 다른 점

이 규약은 `mattpocock/skills`에서 가져왔다. 우리와 다른 셋은 적용하지 않는다. 판단 근거가 필요하면 `reference/invocation.md`(원문)와 `reference/openai.yaml`(Codex 메타데이터 예시)을 Read한다.

- **`.claude-plugin/plugin.json`**: 상위 레포는 스킬을 Claude Code 플러그인으로 배포해 promoted 스킬을 그 매니페스트에 등록한다. 우리는 심링크로 설치하므로 매니페스트가 없다.
- **User-invoked / Model-invoked 구분**: 상위 레포는 둘을 섞어 쓰고 README를 그 둘로 나눈다. 우리는 전부 user-invoked라 나눌 축이 없다.
- **`agents/openai.yaml`**: 상위 레포는 스킬마다 Codex용 메타데이터(`interface.display_name`·`short_description`, user-invoked면 `policy.allow_implicit_invocation: false`)를 둔다. 우리 Codex 스킬은 `codex/skills/`에 별도 사본으로 있어 이 파일을 쓰지 않는다. Codex 사본을 단일 출처로 합칠 때 다시 볼 관례다.
