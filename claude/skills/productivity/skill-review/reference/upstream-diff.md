# 상위 관례와 다른 점

아래 셋은 상위 레포(`mattpocock/skills`)에만 해당한다. 판단 근거가 필요하면 `~/.claude/skills/skill-review/reference/invocation.md`와 `~/.claude/skills/skill-review/reference/openai.yaml`을 Read한다.

- `.claude-plugin/plugin.json`: 상위 레포는 스킬을 Claude Code 플러그인으로 배포해 promoted 스킬을 그 매니페스트에 등록한다. 우리는 심링크로 설치한다.
- User-invoked / Model-invoked 구분: 상위 레포는 둘을 섞어 쓰고 README를 그 둘로 나눈다. 우리는 전부 user-invoked이고 README를 한 목록으로 둔다.
- `agents/openai.yaml`: 상위 레포는 스킬마다 Codex용 메타데이터(`interface.display_name`·`short_description`, user-invoked면 `policy.allow_implicit_invocation: false`)를 둔다. 우리는 Codex가 같은 `SKILL.md`를 링크해서 본다. Codex 쪽 user-invoked 강제는 아직 확인하지 않았다.
