# Phase 0: 계획

## 지시사항

아래 spec 파일을 **섹션별로** 읽고, 요구사항 체크리스트를 생성한 뒤, 구현 계획을 수립하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}
**체크리스트 저장 경로**: {{CHECKLIST_PATH}}
**계획 저장 경로**: {{PLAN_PATH}}

## 절차

### 1단계: Spec 섹션 맵 생성

각 spec 파일을 Read로 열고, 마크다운 헤더(`#`, `##`, `###`, `####`)의 위치와 라인 번호를 파악한다.
결과를 섹션 맵으로 정리한다:

```
spec.md:
  - L1-L45: # Overview
  - L46-L120: ## Domain Entities
  - L121-L200: ## Approval Flow
  ...
spec_detail_2.md:
  - L1-L30: # PR2 상세
  - L31-L85: ## 승인/거절 API
  ...
```

**주의**: 파일이 500줄 이상이면 반드시 Read의 offset/limit를 사용하여 구간별로 읽는다. 한 번에 전체를 읽지 않는다.

### 2단계: 섹션별 요구사항 추출 → 체크리스트 생성

섹션 맵의 각 섹션을 **하나씩** Read(offset, limit)로 읽고, 해당 섹션의 요구사항을 추출한다.

추출한 요구사항을 {{CHECKLIST_PATH}}에 다음 형식으로 작성한다:

```markdown
# Spec Checklist

## Domain
- [ ] REQ-001 [spec.md:45-52] DisplaycamPartner entity에 status_type 필드 추가
- [ ] REQ-002 [spec.md:53-58] StatusType은 PENDING, APPROVED, REJECTED 값
- [ ] REQ-003 [spec.md:60-68] approve() 시 REJECTED→APPROVED 전이 시 reject_reason null 초기화

## Application
- [ ] REQ-010 [spec_detail_2.md:31-45] ApproveService.execute() 정의
...

## Adapter
- [ ] REQ-020 [spec.md:180-195] DjangoDisplaycamPartnerRepo 구현
...
```

**체크리스트 작성 규칙**:
1. 요약하지 않는다. 해당 라인 범위의 핵심 동작/조건을 한 줄로 정확히 기술한다.
2. 하나의 요구사항에 여러 조건이 있으면 **조건마다 별도 REQ 항목**으로 분리한다.
3. 라인 참조 `[파일명:시작줄-끝줄]`은 반드시 정확해야 한다. 나중에 이 참조로 원본을 읽는다.
4. 암묵적 요구사항(명시되지 않았지만 문맥상 필요한 것)도 추출하되, `(암묵적)` 표시를 붙인다.
5. DDD 레이어별로 그룹핑한다: Domain → Application → Adapter → Test → 기타.

### 3단계: 체크리스트 완전성 검증

체크리스트를 작성한 후, 각 spec 파일의 **모든 섹션**을 다시 훑으며:
- 빠뜨린 요구사항이 없는지 확인한다
- 라인 참조가 정확한지 확인한다
- 하나의 REQ에 2개 이상의 독립된 조건이 뭉쳐있지 않은지 확인한다

누락이 있으면 {{CHECKLIST_PATH}}에 추가한다.

### 4단계: 구현 계획 수립

체크리스트의 REQ 항목들을 구현 Unit으로 묶어 {{PLAN_PATH}}에 저장한다.

```markdown
# 구현 계획

## Unit 1: Domain entities
- REQ-001, REQ-002, REQ-003
- 구현 파일: domain/entities.py, domain/value_objects.py
- 의존: 없음

## Unit 2: Domain services
- REQ-005, REQ-006
- 구현 파일: domain/services.py
- 의존: Unit 1

## Unit 3: Application services
- REQ-010, REQ-011, REQ-012
- 구현 파일: application/approve_service.py
- 의존: Unit 1, Unit 2
...
```

**Unit 구성 규칙**:
- DDD 레이어 순: domain → application → adapter
- 각 Unit은 **하나의 이터레이션**에서 구현 가능한 크기 (REQ 5~10개 이내)
- Unit 간 의존 관계를 명시한다

### 5단계: 계획 검토

Task(subagent_type='planner')를 호출한다:
- 체크리스트({{CHECKLIST_PATH}})와 계획({{PLAN_PATH}})을 1:1 대조
- 모든 REQ 항목이 최소 하나의 Unit에 포함되는지 확인
- Unit 간 의존 관계가 올바른지 확인

### 6단계: YAGNI 검토

Task(subagent_type='yagni-reviewer')를 호출한다:
- spec에 명시되지 않은 기능 식별
- 미래 확장을 위한 사전 추상화 식별
- 과도한 설계 패턴 식별

yagni-reviewer가 보고한 YAGNI/OVER 항목을 {{PLAN_PATH}}에서 제거한다.

### 반복 확인 (이전 이터레이션에서 수정한 경우)
이전 이터레이션에서 체크리스트나 계획을 수정했다면:
1. {{CHECKLIST_PATH}}와 {{PLAN_PATH}}를 다시 읽는다
2. planner와 yagni-reviewer를 재호출하여 수정 결과를 검증한다
3. 잔여 이슈가 있으면 수정하고 다음 이터레이션에서 재검증한다

## 완료 조건

- spec의 **모든 섹션**이 체크리스트에 반영됨 (누락 0건)
- 체크리스트의 모든 REQ 항목이 계획의 Unit에 포함됨
- planner CRITICAL/HIGH 이슈 0건
- yagni-reviewer YAGNI 항목 0건
- {{CHECKLIST_PATH}}에 체크리스트 파일 저장 완료
- {{PLAN_PATH}}에 계획 파일 저장 완료
- 계획이 CLAUDE.md 아키텍처 원칙과 정합

모든 조건 충족 시 <promise>PLAN DONE</promise> 출력.
