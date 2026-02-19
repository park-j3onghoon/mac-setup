# Phase 5: 엣지케이스 사냥

## 지시사항

코드를 깨뜨릴 수 있는 엣지케이스를 찾고 테스트를 추가하라.

**Spec**:
{{SPEC_PATH}}
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

### 4단계: 전체 테스트 및 커버리지 확인
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v --cov={{MODULE_PATH}} --cov-fail-under=80
```

### 5단계: lint/format/type check (변경 파일만)
```bash
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 새로 발견된 엣지케이스에 대한 테스트 추가됨
- 모든 테스트(기존 + 신규) 통과
- 커버리지 80% 이상
- 변경 파일 ruff check/format/mypy 통과
- 코드로 해결 불가한 리스크는 테스트 파일 내 주석 또는 docstring으로 문서화됨

모든 조건 충족 시 <promise>EDGE DONE</promise> 출력.
