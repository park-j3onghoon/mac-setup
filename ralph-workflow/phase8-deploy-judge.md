# Phase 8: 배포 판정

## 지시사항

최종 배포 가능 여부를 판정하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}
**체크리스트**: {{CHECKLIST_PATH}} (요구사항 인덱스 — 라인 참조로 원본 spec 확인 가능)

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

### 2단계: NO-SHIP 대응
NO-SHIP 판정 시:
- 구체적 수정 사항을 확인한다
- 수정을 수행한다
- 다시 deployment-judge를 호출한다

### 3단계: 최종 확인 (전체 범위)
SHIP 판정을 받은 후 마지막으로 **{{MODULE_PATH}} 전체**를 대상으로 실행한다:
```bash
# 전체 테스트 + 커버리지
docker exec "$DEV_CONTAINER" pytest {{MODULE_PATH}} --reuse-db -x -q --cov={{MODULE_PATH}} --cov-fail-under=80

# pre-commit (ruff check + ruff format + mypy)
pre-commit run --files $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- deployment-judge 판정: SHIP
- {{MODULE_PATH}} 전체 테스트 통과
- 커버리지 80% 이상
- pre-commit 통과

모든 조건 충족 시 <promise>SHIP IT</promise> 출력.
