# Phase 5: 엣지케이스 사냥

## 지시사항

코드를 깨뜨릴 수 있는 엣지케이스를 찾고 테스트를 추가하라.

**Spec**: {{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}

## 절차

### 1단계: 엣지케이스 탐색
Task(subagent_type='edge-case-hunter')를 호출한다:
- None/빈값/경계값 시나리오
- 비즈니스 규칙 경계 조건
- 동시성/Race condition
- 외부 의존성 실패 시나리오
- 데이터 정합성 이슈

### 2단계: 테스트 추가
edge-case-hunter가 발견한 커버되지 않은 엣지케이스에 대해 테스트를 추가한다.

### 3단계: 코드 수정
새 테스트가 실패하면 구현 코드를 수정한다.

### 4단계: 전체 테스트 실행
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
```

## 완료 조건

- 새로 발견된 엣지케이스에 대한 테스트 추가됨
- 모든 테스트(기존 + 신규) 통과
- 코드로 해결 불가한 리스크는 잔여 리스크로 문서화됨

모든 조건 충족 시 <promise>EDGE DONE</promise> 출력.
