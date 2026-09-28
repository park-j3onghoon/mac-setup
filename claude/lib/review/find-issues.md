# 문제 지점 찾기

diff에서 문제 지점을 찾아 이슈 리포트 하나로 모은다. 입력은 셋이다: diff 파일 경로, 의도가 되는 PR 제목·본문, 리뷰할 코드가 체크아웃된 대상 경로.

## 1. 스코프 체크

의도와 diff가 실제로 하는 일을 비교해 적는다.

```
Scope Check: [CLEAN / DRIFT / MISSING]
의도: <PR 제목·본문이 말하는 것 1줄>
실제: <diff가 실제로 하는 것 1줄>
```

diff에서 돈 계산·권한·데이터 변경·외부 호출처럼 틀리면 비싼 곳을 `파일:라인`으로 골라 먼저 볼 곳 목록을 만든다.

## 2. 보안 레벨

`~/.claude/lib/security/index.md`가 있으면 그 파일의 레벨 판정 절 패턴을 입력 diff에 대고, 없으면 레벨 1이다. `Security level: N (트리거: ...)` 한 줄을 남긴다.

## 3. 서브에이전트 병렬 리뷰

한 메시지에서 아래 리뷰어를 동시에 띄운다. 호출한 쪽이 더하는 서브에이전트도 같은 배치에 띄운다.

- 코드 공통: `~/.claude/lib/review/code.md`
- 언어별: `~/.claude/lib/review/language.md`
- 팀 리뷰어: `~/.claude/lib/review/team.md`
- 보안: 레벨이 2 이상일 때만. `~/.claude/lib/security/index.md`의 레벨표가 정한 모듈 전부

프롬프트마다 넣을 것:

1. diff 파일 경로 전부, 의도 요약, 먼저 볼 곳 목록, 대상 경로.
2. 담당 기준 파일의 절대경로와 이 지시: "이 파일을 먼저 Read하고, 항목마다 PASS·해당 없음·발견 중 하나로 판정한다. PASS는 살펴봤는데 발견이 없는 것이고, 해당 없음은 이 diff와 무관한 것이다. 출력은 이 파일의 출력 형식을 따른다."
3. 발견 형식: "발견은 `[CRITICAL|INFO] file:line · 설명` 형식으로 낸다." 보안은 index.md의 출력 형식과 값 미기재 규칙을 따른다.
4. "코드 확인은 대상 경로 안에서 Grep/Read로 한다" + `~/.claude/lib/review/claims.md`의 네 줄.

## 4. Codex 교차 검증

Codex로 한 번 더 볼지 AskUserQuestion 1회로 묻는다. 권장안을 첫 옵션에 두고, 일반 리뷰와 리뷰 + 적대 검증 중 무엇을 돌릴지와 그 이유를 한 줄 붙인다. 판단 기준과 실행·회수는 `~/.claude/lib/codex-adversarial.md`를 따르고, Codex는 대상 경로에서 실행한다.

## 5. 결과 통합

- 같은 이슈를 여러 리뷰어가 잡았으면 하나로 합치고 출처를 `(코드+팀+보안+codex)`처럼 표시한다.
- Codex 발견도 같은 목록에 합친다. Codex 발견은 빼지 않고, Claude 리뷰어와 판단이 다르면 두 판단을 같이 적는다.
- CRITICAL을 위, INFO를 아래로 정렬한다.
- diff가 바꾼 기능을 설명하는 문서가 그대로면 `[INFO] 문서가 오래됐을 수 있음: {파일}이 {기능}을 설명하지만 코드가 변경됨.`
- 모든 주장에 `~/.claude/lib/review/claims.md`를 적용한다.

→ 완료: `Security level` 한 줄, Scope Check, 먼저 볼 곳 목록, 중복이 합쳐지고 심각도순으로 정렬된 이슈 리포트가 있다.
