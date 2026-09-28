# 리뷰 fan-out 공통

diff를 서브에이전트 여럿에게 나눠 리뷰하는 스킬이 함께 쓰는 틀이다. 스킬마다 다른 부분(더 띄우는 서브에이전트, 수정 여부, 산출물)은 그 스킬이 적는다.

## 스코프 체크

```
Scope Check: [CLEAN / DRIFT / MISSING]
의도: <요청된 작업 1줄>
실제: <diff가 실제로 하는 것 1줄>
```

## 서브에이전트 공통 지시

프롬프트마다 아래를 모두 넣는다.

1. diff 전문(너무 길면 파일별 요약 + 핵심 변경부) 또는 diff를 저장한 파일 경로.
2. 담당 브리프 파일의 절대경로. 서브에이전트가 먼저 Read하고 그 기준·출력 형식을 따른다.
3. 코드 규칙: "`~/.claude/lib/coding-rules.md`의 §0 Precedence·§1 Architecture·§2 Module·§3 Class/Object를 Read하고 적용하라. diff에 Python·프론트엔드·DB 파일이 있으면 `~/.claude/lib/coding-rules-python.md`·`-frontend.md`·`-db.md`도 Read하라."
4. "기준의 각 항목을 빠짐없이 판단한다. 살펴봤는데 발견이 없으면 `PASS`, 이 diff와 무관한 기준이면 `해당 없음`으로 구분해 쓴다."
5. 발견 형식: "발견은 `[CRITICAL|INFO] file:line · 설명` 형식으로 낸다."
6. "코드베이스 확인이 필요한 것은 Grep/Read로 직접 검증한다" + `~/.claude/lib/review/claims.md`의 네 줄.

## 브리프

| 서브에이전트 | 브리프 | 역할 |
|---|---|---|
| 코드 공통 | `~/.claude/lib/review/code.md` | 보안·정확성·계약 일관성·반환 타입·클린코드·YAGNI·아키텍처·에러 핸들링·관측성·성능·테스팅·운영 안전성 |
| 언어별 | `~/.claude/lib/review/language.md` | diff에 포함된 언어(Python·Go·Java·프론트엔드)의 관용구·타입 안전성·플랫폼 특화 이슈 |
| 팀 리뷰어 | `~/.claude/lib/review/team.md` | 리뷰어 카탈로그(R1~R24 매핑표)별 관점. 매핑표의 도메인 컬럼으로 diff에 해당하는 리뷰어를 골라 점검 |

## 결과 통합

- 같은 이슈를 여러 리뷰어가 잡았으면 하나로 합치고 출처를 표시한다(`(코드+팀+codex)`).
- CRITICAL을 위, INFO를 아래로 정렬한다.
- Codex 결과는 요약·paraphrase 없이 별도 블록에 원문 그대로 붙인다.

## 문서·페어 점검

- diff가 바꾼 기능을 설명하는 문서가 그대로면 `[INFO] 문서가 오래됐을 수 있음: {파일}이 {기능}을 설명하지만 코드가 변경됨.`
- diff가 CLAUDE.md·AGENTS.md 중 한쪽만 바꿨으면 `[CRITICAL] 페어 sync 누락: {파일}`. 도구별 분기 섹션(assignee 등) 외의 차이만 센다.
