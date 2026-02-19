# Phase 0: 계획

## 지시사항

아래 spec 파일을 **섹션별로** 읽고, 요구사항 체크리스트를 생성한 뒤, 구현 계획을 수립하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}
**체크리스트 저장 경로**: {{CHECKLIST_PATH}}
**계획 저장 경로**: {{PLAN_PATH}}

## 이어받기 (이전 이터레이션이 있는 경우)

**먼저 {{CHECKLIST_PATH}}가 이미 존재하는지 확인한다.**
- 존재하면: 이전 이터레이션의 작업을 이어받는다. "섹션 처리 현황"을 확인하고 미처리 섹션부터 진행한다.
- 존재하지 않으면: 1단계부터 새로 시작한다.

## 절차

### 1단계: Spec 섹션 맵 생성

각 spec 파일의 마크다운 헤더를 **Grep으로** 추출한다 (파일 전체를 Read하지 않는다):

```
Grep(pattern="^#{1,4} ", path="spec.md", output_mode="content")
```

Grep 결과에서 각 헤더의 라인 번호를 파악하고, 인접 헤더 간의 라인 범위를 계산하여 섹션 맵을 만든다:

```
spec.md (총 5000줄):
  - L1-L45: # Overview
  - L46-L120: ## Domain Entities
  - L121-L200: ## Approval Flow
  ...
```

### 2단계: 섹션별 요구사항 추출 → 체크리스트 생성

{{CHECKLIST_PATH}}에 체크리스트를 생성한다. **맨 위에 섹션 처리 현황**을 포함한다:

```markdown
# Spec Checklist

## 섹션 처리 현황
- [x] spec.md: # Overview (L1-L45)
- [x] spec.md: ## Domain Entities (L46-L120)
- [ ] spec.md: ## Approval Flow (L121-L200)
- [ ] spec_detail_2.md: # PR2 상세 (L1-L30)
...

## Domain
- [ ] REQ-001 [spec.md:46-52] DisplaycamPartner entity에 status_type 필드 추가
- [ ] REQ-002 [spec.md:53-58] StatusType은 PENDING, APPROVED, REJECTED 값
...
```

**처리 방법**:
1. 섹션 처리 현황의 **미처리(`- [ ]`) 섹션**을 하나씩 순서대로 처리한다.
2. 해당 섹션만 Read(offset, limit)로 읽는다. **다른 섹션은 읽지 않는다.**
3. 읽은 내용에서 요구사항을 추출하여 체크리스트 하단에 REQ 항목으로 추가한다.
4. 해당 섹션을 `- [x]`로 변경한다.
5. 다음 미처리 섹션으로 넘어간다.

**컨텍스트 관리**: 한 이터레이션에서 모든 섹션을 처리할 필요 없다. 컨텍스트가 부담되면 처리한 데까지 저장하고, 다음 이터레이션에서 이어받는다.

**체크리스트 작성 규칙**:
1. 요약하지 않는다. 해당 라인 범위의 핵심 동작/조건을 한 줄로 정확히 기술한다.
2. 하나의 요구사항에 여러 조건이 있으면 **조건마다 별도 REQ 항목**으로 분리한다.
3. 라인 참조 `[파일명:시작줄-끝줄]`은 반드시 정확해야 한다. 나중에 이 참조로 원본을 읽는다.
4. 암묵적 요구사항(명시되지 않았지만 문맥상 필요한 것)도 추출하되, `(암묵적)` 표시를 붙인다.
5. DDD 레이어별로 그룹핑한다: Domain → Application → Adapter → Test → 기타.

### 3단계: 체크리스트 완전성 검증

**모든 섹션이 `- [x]`가 된 후에만** 이 단계를 실행한다.

섹션 처리 현황에 미처리 섹션이 남아있으면 2단계로 돌아간다.

모든 섹션 처리 완료 후:
- 섹션 맵과 체크리스트를 대조하여 빠뜨린 섹션이 없는지 확인한다
- 라인 참조가 정확한지 확인한다 (Grep으로 해당 라인의 내용을 샘플 검증)
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

### 반복 확인 (이전 이터레이션에서 계획을 수정한 경우)
이전 이터레이션에서 계획을 수정했다면:
1. {{CHECKLIST_PATH}}와 {{PLAN_PATH}}를 다시 읽는다
2. planner와 yagni-reviewer를 재호출하여 수정 결과를 검증한다
3. 잔여 이슈가 있으면 수정하고 다음 이터레이션에서 재검증한다

## 완료 조건

- 섹션 처리 현황의 **모든 섹션**이 `- [x]` (미처리 0건)
- 체크리스트의 모든 REQ 항목이 계획의 Unit에 포함됨
- planner CRITICAL/HIGH 이슈 0건
- yagni-reviewer YAGNI 항목 0건
- {{CHECKLIST_PATH}}에 체크리스트 파일 저장 완료
- {{PLAN_PATH}}에 계획 파일 저장 완료
- 계획이 CLAUDE.md 아키텍처 원칙과 정합

모든 조건 충족 시 <promise>PLAN DONE</promise> 출력.
