# Phase 1: 구현

## 지시사항

아래 spec 파일을 읽고 구현하라.

**Spec**:
{{SPEC_PATH}}

## 절차

1. spec 파일을 읽고 요구사항을 파악한다.
2. spec에 명시된 파일들을 생성/수정한다.
3. CLAUDE.md와 CLAUDE.local.md의 코딩 컨벤션을 준수한다.
4. 테스트를 작성하고 실행한다:
   ```bash
   docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
   ```
5. lint/type check (변경 파일만):
   ```bash
   uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
   uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
   ```

## 완료 조건

- spec에 명시된 파일이 모두 존재
- 모든 테스트 통과
- 변경 파일 ruff 경고 0건
- 변경 파일 mypy 에러 0건

모든 조건 충족 시 <promise>IMPL DONE</promise> 출력.
