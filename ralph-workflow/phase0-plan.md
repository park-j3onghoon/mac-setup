# Phase 0: 계획

## 지시사항

아래 spec 파일을 읽고 구현 계획을 수립하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}
**계획 저장 경로**: {{PLAN_PATH}}

## 절차

### 1단계: Spec 분석
spec 파일을 읽고 요구사항을 파악한다:
- 구현해야 할 기능 목록
- 변경/생성할 파일 목록
- 외부 의존성 (다른 모듈, 라이브러리)
- 기존 코드와의 관계

### 2단계: 구현 계획 작성
Task(subagent_type='planner')를 호출한다:
- spec 요구사항 기반 구현 계획 수립
- 파일별 변경 내용 명시
- 구현 순서와 의존 관계 정리
- 위험 요소 및 주의사항 식별

계획을 {{PLAN_PATH}}에 저장한다.

### 3단계: 계획 검토
Task(subagent_type='plan-reviewer')를 호출한다:
- spec과 계획을 1:1 대조하여 누락/불일치 식별
- 기존 코드와의 충돌 가능성 확인
- 검토 자체의 완전성 재검토 (meta-review)

plan-reviewer가 보고한 CRITICAL/HIGH 이슈를 {{PLAN_PATH}}에 반영한다.

### 4단계: YAGNI 검토
Task(subagent_type='yagni-reviewer')를 호출한다:
- spec에 명시되지 않은 기능 식별
- 미래 확장을 위한 사전 추상화 식별
- 현재 단계에서 필요하지 않은 코드 식별
- 과도한 설계 패턴 식별

yagni-reviewer가 보고한 YAGNI/OVER 항목을 {{PLAN_PATH}}에서 제거한다.

### 반복 확인 (이전 이터레이션에서 수정한 경우)
이전 이터레이션에서 계획을 수정했다면:
1. {{PLAN_PATH}}를 다시 읽는다
2. plan-reviewer와 yagni-reviewer를 재호출하여 수정 결과를 검증한다
3. 잔여 이슈가 있으면 수정하고 다음 이터레이션에서 재검증한다

## 완료 조건

- spec의 모든 요구사항이 계획에 포함
- plan-reviewer CRITICAL/HIGH 이슈 0건
- yagni-reviewer YAGNI 항목 0건
- {{PLAN_PATH}}에 계획 파일 저장 완료
- 계획이 CLAUDE.md 아키텍처 원칙과 정합

모든 조건 충족 시 <promise>PLAN DONE</promise> 출력.
