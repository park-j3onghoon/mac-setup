# Phase 6: 통합 테스트

## 지시사항

새 코드가 기존 코드베이스와 충돌 없이 통합되는지 검증하라.

**Spec**: {{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}

## 절차

### 1단계: 통합 검증
Task(subagent_type='integration-verifier')를 호출한다:
- Import 충돌
- Model/Schema 충돌
- 라우팅 충돌
- Hook/Signal 간섭
- 기존 코드 영향
- 설정/환경 충돌

### 2단계: 전체 테스트 스위트
```bash
# 새 코드 테스트
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v

# MODULE_PATH 전체 테스트
docker exec "$DEV_CONTAINER" pytest {{MODULE_PATH}} --reuse-db -x -q
```

### 3단계: 충돌 해결
발견된 충돌을 수정한다.

### 4단계: 재검증
수정 후 모든 테스트를 다시 실행한다.

## 완료 조건

- 통합 검증 CRITICAL/HIGH 이슈 0건
- 새 코드 테스트 전체 통과
- 기존 테스트 영향 없음
- MODULE_PATH 전체 테스트 통과

모든 조건 충족 시 <promise>INTEGRATION DONE</promise> 출력.
