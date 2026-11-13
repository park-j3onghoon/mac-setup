---
name: investigate
description: 버그를 근본 원인까지 추적해 고치고 DEBUG REPORT로 마감한다.
disable-model-invocation: true
argument-hint: "[증상 또는 에러 메시지]"
---

`~/.claude/lib/debug.md`를 Read하고 그 순서로 원인을 찾고 고친다. 아래는 그 순서에 이 스킬이 더하는 일이다.

1. 증상 수집: 에러 메시지·스택 트레이스·재현 단계를 모은다. 코드·로그·데이터로 알 수 없는 맥락만 AskUserQuestion으로 한 번에 하나씩 묻는다. 서버에서 난 장애라 로그·메트릭이 필요하면 `~/.claude/lib/grafana/index.md`를 Read해 Loki·Prometheus를 조회한다. → 완료: `~/.claude/lib/debug.md` 1단계의 증상 문장이 적혔다.
2. 역추적: 증상 지점에서 데이터 흐름을 거슬러 코드를 읽고 `git log --oneline -20 -- <affected-files>`로 최근 변경을 본다. 회귀면 근본 원인은 diff에 있다(구간이 넓으면 `git bisect`). 같은 파일에서 버그가 반복되면 아키텍처 hotspot으로 적는다. 후보가 안 잡히면 패턴과 대조한다: race condition · null 전파 · 상태 오염 · 통합 장애 · 설정 드리프트 · 캐시 오염. → 완료: `~/.claude/lib/debug.md` 3단계의 후보 목록이 근거·예상 관측과 함께 적혔다.
3. 실험과 재현: `~/.claude/lib/debug.md` 4단계대로 실험해 후보를 하나로 좁히고, 그 원인으로 버그를 원할 때 일으키는 최소 절차나 테스트를 만든다. 계측이 필요하면 의심 지점에 임시 로그·assertion을 넣고 재현을 돌린다. 후보가 모두 지워지면 2단계로 돌아가고, 새 후보를 찾는 데 운영 로그 추가처럼 배포가 필요하면 확인한 사실·지운 후보·더할 로그를 DEBUG REPORT(상태 BLOCKED)로 내고 멈춘다. → 완료: 원인이 하나로 확인됐고 재현 루프가 red.
4. 최소 diff 수정: `~/.claude/lib/debug.md` 5단계대로 고친다. "일단 임시로" 요청이 와도 선택지는 근본 수정 아니면 에스컬레이션이다. `~/.claude/lib/coding/index.md`를 Read하고 그 목록에서 이번 수정과 회귀 테스트가 닿는 모듈을 Read해 그 규칙을 따른다. 회귀 테스트는 수정 없이 red · 수정 있으면 green 을 둘 다 눈으로 확인하고, `~/.claude/lib/pr-rules.md`를 Read하고 그 문서의 테스트·빌드 규칙대로 관련 테스트를 돌려 출력을 증거로 붙인다. → 완료: 재현 루프가 green, 관련 테스트 회귀 0.
5. 보고: 원래 버그 시나리오를 재현해 수정을 확인하고, 결과는 `~/.claude/lib/debug.md` 6단계대로 기준과 비교해 쓴다(확인 불가면 BLOCKED, hotspot·잔여 우려가 있으면 DONE_WITH_CONCERNS). → 완료: 아래 형식으로 출력했다.

```
DEBUG REPORT
════════════════════════════════════════
증상:          [사용자가 관찰한 것]
근본 원인:     [실제로 잘못된 것]
수정:          [무엇을 변경했는지, file:line]
증거:          [테스트 출력, 재현 결과]
회귀 테스트:   [file:line]
관련:          [같은 영역의 과거 버그, 아키텍처 노트]
상태:          DONE | DONE_WITH_CONCERNS | BLOCKED
════════════════════════════════════════
```

원인 구조가 복잡해 그림이 있어야 전달되면 `~/.claude/lib/explain-html.md`를 Read해 같은 내용을 HTML 해설서로 낸다.

수정이 5개 파일 이상이면 고치기 전에 `/implement`를 권하고 멈춘다.

수정 파일 수는 테스트 파일을 빼고 센다. 이 기준으로 멈출 때도 DEBUG REPORT를 내고, 수정 칸에 고칠 파일 목록을, 상태 칸에 BLOCKED를 쓴다.
