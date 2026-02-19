# Phase 2: 리뷰 + 수정

## 지시사항

구현된 코드를 다각도로 검토하고 발견된 이슈를 수정하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}

## 절차

### 1단계: Spec 대조 리뷰
Task(subagent_type='spec-reviewer')를 호출한다:
- spec 파일 경로와 구현 디렉토리를 전달
- MISS/DIFF 항목 확인

### 2단계: 코드 리뷰
Task(subagent_type='code-reviewer')를 호출한다:
- 코드 품질, 타입 힌트, 패턴 검토

### 3단계: 보안 리뷰
Task(subagent_type='security-reviewer')를 호출한다:
- 인젝션 방지, 입력 검증, 시크릿 노출 검토

### 4단계: 사이드 이펙트 분석
Task(subagent_type='side-effect-analyzer')를 호출한다:
- Hook/Signal 체인, 공유 상태, 레이어 의존성 검토

### 5단계: 이슈 수정
에이전트들이 보고한 CRITICAL/HIGH 이슈를 모두 수정한다.
수정 후 테스트를 다시 실행하여 regression이 없는지 확인한다.

## 완료 조건

- 모든 에이전트 리뷰 완료
- CRITICAL 이슈 0건
- HIGH 이슈 0건
- 수정 후 테스트 전체 통과

모든 조건 충족 시 <promise>REVIEW DONE</promise> 출력.
