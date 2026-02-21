# Phase 18: 배포 판정

## 지시사항

최종 배포 가능 여부를 판정하라.
**매 이터레이션마다 전체 spec을 최종 재대조한다.**

**Spec**:
{{SPEC_PATH}}
**스펙 요약**: {{DIGEST_PATH}} (핵심 개념, 교차 참조, 전역 제약. 먼저 읽고 큰 그림을 파악하라.)
**구현 디렉토리**: {{MODULE_PATH}}
**테스트 디렉토리**: {{TEST_PATH}}
**체크리스트**: {{CHECKLIST_PATH}}
**메모**: {{NOTES_PATH}} (이전 Phase의 발견/수정 사항. 읽고 참조하라. 수정 시 기록하라.)

## 공통 원칙

1. **발견된 문제의 관련 영역도 재검토** — 문제 수정 후 영향받을 수 있는 코드를 추적하여 추가 검토
2. **모든 spec 파일을 매 이터레이션마다 함께 처리** — 체크리스트 라인 참조로 해당 줄만 Read
3. **이전 이터레이션 이어받기** — 체크리스트/결과 파일로 진행 상황 추적
4. **수정 발생 시 promise 출력 금지** — 수정 없는 클린 이터레이션에서만 promise 출력

## 절차

### 1단계: 배포 판정

Task(subagent_type='deployment-judge')를 호출한다. **{{CHECKLIST_PATH}}를 전달**하여:
- 테스트 통과 여부
- 테스트 커버리지 80% 이상
- lint/format/type check 통과 여부
- **Spec 완전성**: 체크리스트의 모든 REQ 항목이 `- [x]`이고, 각 항목의 라인 참조를 따라 원본 spec과 대조
- 아키텍처 준수 (DDD 레이어 의존성 포함)
- 보안 검증
- 코드 품질
- 하위 호환성 (기존 API breaking change 없는지)
- DB 마이그레이션 안전성 (마이그레이션 파일이 있는 경우)

### 2단계: NO-SHIP 대응
NO-SHIP 판정 시:
- 구체적 수정 사항을 확인한다
- 수정을 수행한다
- 다시 deployment-judge를 호출한다
- **수정이 있었으면 promise를 출력하지 않는다.** 다음 이터레이션에서 재판정.

### 3단계: Spec 최종 재대조 (SHIP 판정 후)

**SHIP 판정을 받은 후에도 promise를 바로 출력하지 않는다.**
매 이터레이션마다 최종 재대조를 수행한다.

**절차:**
1. {{CHECKLIST_PATH}}의 `[x]` 항목을 **처음부터 끝까지** 순회한다.
2. 각 항목의 라인 참조를 따라 원본 spec을 Read(offset, limit)로 읽는다.
3. 구현 코드가 spec 원문의 **모든 조건**을 정확히 구현했는지 최종 대조한다.
4. 불일치 발견 시 → 수정하고 다시 deployment-judge를 호출한다. promise를 출력하지 않는다.

### 4단계: 최종 확인
SHIP 판정 + 재대조 완료 후 마지막으로 **{{MODULE_PATH}} 전체**를 대상으로 실행한다:
```bash
# 전체 테스트 + 커버리지
docker exec "$DEV_CONTAINER" pytest {{MODULE_PATH}} --reuse-db -x -q --cov={{MODULE_PATH}} --cov-fail-under=80

# pre-commit (ruff check + ruff format + mypy)
pre-commit run --files $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

### 5단계: 메모 기록

최종 판정 결과를 {{NOTES_PATH}}에 기록한다.

## 완료 조건

- deployment-judge 판정: SHIP
- **Spec 최종 재대조 불일치 0건** (모든 REQ를 라인 참조로 원본 spec과 대조 완료)
- {{MODULE_PATH}} 전체 테스트 통과
- 커버리지 80% 이상
- pre-commit 통과

- **클린 이터레이션 ≥ 1** (수정 없는 이터레이션이 최소 1회 있어야 함)

모든 조건 충족 시 <promise>SHIP IT</promise> 출력.
