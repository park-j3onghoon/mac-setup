---
name: implement
description: 확정된 계획을 vertical slice 단위로 구현한다. 안전 모드를 걸고, 코드 규칙을 적재하고, 슬라이스마다 테스트를 green으로 만든다.
disable-model-invocation: true
argument-hint: "[계획 파일 경로 | 구현 범위]"
---

## 1. 범위 확정

인자가 경로면 그 계획 파일을 Read한다. 인자가 없으면 `~/.claude/lib/plans-path.md`를 Read하고 그 경로 규칙에 맞는 `plan.md`를 Glob으로 찾아 후보를 보여주고 고르게 한다.

계획 파일이 없으면 왜 없는지부터 가른다.

| 상태 | 다음 |
|---|---|
| 갈림길이 안 닫혔다: 방식·범위·계약 중 사용자가 골라야 할 것이 남았다 | `/grill`을 권하고 멈춘다 |
| 결정은 됐는데 설계가 없다 | 계획을 쓴 뒤 `/plan-review`를 권하고 멈춘다 |
| 작고 자명하다: 단일 파일, 기존 패턴 그대로 | 대화 맥락에서 무엇을 만들지 정리해 출력하고 승인을 받는다 |

계획이 여러 PR로 쪼개져 있으면 이번에 어디까지 할지 확정한다.

→ 완료: 구현할 항목 목록과 이번 범위의 끝이 한 문단으로 적혔고 사용자가 동의했다.

## 2. 안전 모드

`~/.claude/lib/guard.md`를 Read하고, 계획이 가리키는 레포 경로로 careful·freeze를 건다. 그 문서의 활성화 메시지를 출력한다. 이미 `/guard`가 걸려 있으면 범위만 확인하고 넘어간다.

→ 완료: 위험 명령 경고와 편집 범위가 적용 중이고 사용자가 범위를 봤다.

## 3. 규칙 적재

- `~/.claude/lib/coding/index.md`를 Read하고, 그 목록에서 이번 변경이 닿는 모듈(스택 파일 포함)을 모두 Read한다.
- 작업 중인 레포에 CLAUDE.md·AGENTS.md가 있고 거기서 레포 전용 규칙 파일을 가리키면 그것도 Read한다.
- API(proto·REST)를 새로 만들거나 기존 엔드포인트를 고치면 API 규칙 모듈(`~/.claude/lib/api-aip/index.md`)을 Read하고 그 문서의 트랙 판정부터 수행한다.

→ 완료: 이번 변경에 걸리는 규칙을 모듈별로 뽑아 뒀고, `~/.claude/lib/coding/change-discipline.md`의 Existing patterns first에 따라 참고할 형제 파일 경로를 적었고, API 변경이면 트랙과 엔벨로프·페이지네이션·에러 shape·필드 케이스 컨벤션이 확정됐다.

## 4. 슬라이스 구현

범위를 `~/.claude/lib/coding/simple-design.md`의 Tracer bullet대로 슬라이스로 나눠 하나씩 끝내고, 슬라이스마다 `~/.claude/lib/coding/tdd.md`를 따라 테스트를 먼저 쓰고 통과시킨다. 슬라이스 경계는 계획의 항목을 따른다.

이 스킬은 변경을 작업 트리에 남기고 끝난다.

→ 완료: 슬라이스마다 red를 본 테스트가 green이고, 변경한 모듈의 테스트 전체와 파일을 옮겼을 때의 빌드가 통과했고, plan.md에 이번 범위 항목 체크와 구현 중 미룬 판단이 적혔다.
