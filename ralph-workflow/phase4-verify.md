# Phase 4: 최종 검증

## 지시사항

전체 변경 사항을 다시 한 번 검토하라.

**Spec**: {{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}

## 절차

### 1단계: 전체 변경 사항 검토
Task(subagent_type='code-reviewer')를 호출한다:
- 전체 변경 파일 목록 전달
- 코드 품질, 보안, 유지보수성 검토

### 2단계: 이슈 수정
발견된 CRITICAL/HIGH 이슈를 수정한다.

### 3단계: 테스트 및 lint/type check (변경 파일만)
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 코드 리뷰 CRITICAL/HIGH 이슈 0건
- 테스트 전체 통과
- 변경 파일 ruff/mypy 통과

모든 조건 충족 시 <promise>VERIFY DONE</promise> 출력.
