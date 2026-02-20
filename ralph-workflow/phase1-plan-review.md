# Phase 1: 계획 검토

## 지시사항

Phase 0에서 생성된 체크리스트와 구현 계획을 plan-reviewer 에이전트로 검토하라.

**Spec**:
{{SPEC_PATH}}
**스펙 요약**: {{DIGEST_PATH}} (핵심 개념, 교차 참조, 전역 제약. 먼저 읽고 큰 그림을 파악하라.)
**구현 디렉토리**: {{MODULE_PATH}}
**체크리스트**: {{CHECKLIST_PATH}}
**계획**: {{PLAN_PATH}}
**메모**: {{NOTES_PATH}} (이전 Phase의 발견/수정 사항. 읽고 참조하라. 수정 시 기록하라.)

## 공통 원칙

1. **발견된 문제의 관련 영역도 재검토** — 문제 수정 후 영향받을 수 있는 코드를 추적하여 추가 검토
2. **모든 spec 파일을 매 이터레이션마다 함께 처리** — 체크리스트 라인 참조로 해당 줄만 Read
3. **이전 이터레이션 이어받기** — 체크리스트/결과 파일로 진행 상황 추적
4. **수정 발생 시 promise 출력 금지** — 수정 없는 클린 이터레이션에서만 promise 출력

## 절차

### 1단계: 계획 검토

Task(subagent_type='plan-reviewer')를 호출한다:
- 체크리스트({{CHECKLIST_PATH}})와 계획({{PLAN_PATH}})을 1:1 대조
- 모든 REQ 항목이 최소 하나의 Unit에 포함되는지 확인
- Unit 간 의존 관계가 올바른지 확인
- 기존 코드 영향 분석

### 2단계: 이슈 수정

plan-reviewer가 보고한 CRITICAL/HIGH 이슈를 수정한다:
- MISS (누락) 항목: 계획에 Unit 추가 또는 기존 Unit에 REQ 추가
- DIFF (불일치) 항목: 계획의 접근방식을 spec에 맞게 수정
- RISK (위험) 항목: 위험 완화 전략을 계획에 반영

수정 사항을 {{NOTES_PATH}}에 기록한다.

**수정이 있었으면 promise를 출력하지 않는다.** 다음 이터레이션에서 plan-reviewer를 재호출하여 수정 결과를 검증한다.

## 완료 조건

- plan-reviewer CRITICAL/HIGH 이슈 0건
- 모든 REQ 항목이 최소 하나의 Unit에 포함됨
- Unit 간 의존 관계가 올바름
- 기존 코드 영향이 계획에 반영됨

모든 조건 충족 시 <promise>PLAN REVIEW DONE</promise> 출력.
