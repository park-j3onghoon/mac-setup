# Phase 4: 최종 검증

## 지시사항

Phase 3 구조 변경 후 전체 변경 사항을 재검증하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}

## 절차

### 1단계: 병렬 재검증 (2개 에이전트를 동시에 호출한다)

다음 2개 에이전트를 **병렬로** 호출한다:

- Task(subagent_type='spec-reviewer'): 구조 변경 후에도 spec 요구사항이 모두 충족되는지 확인
- Task(subagent_type='code-reviewer'): 전체 변경 파일의 코드 품질, 타입 힌트, 패턴, 유지보수성 검토

### 2단계: DDD 레이어 의존성 확인
변경된 파일들의 import를 직접 검사하여 레이어 규칙 위반이 없는지 확인한다:
- `domain/` 파일이 Django/adapter/infra를 import하지 않는지
- `application/` 파일이 adapter/infra를 import하지 않는지
- 의존성 방향: domain ← application ← adapter

### 3단계: 이슈 수정
발견된 CRITICAL/HIGH 이슈를 수정한다.

### 4단계: 테스트 및 lint/format/type check (변경 파일만)
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- spec-reviewer MISS/DIFF 0건
- code-reviewer CRITICAL/HIGH 이슈 0건
- DDD 레이어 의존성 위반 0건
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

모든 조건 충족 시 <promise>VERIFY DONE</promise> 출력.
