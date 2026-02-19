# Phase 2: 리뷰 + 수정

## 지시사항

구현된 코드를 다각도로 검토하고 발견된 이슈를 수정하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}
**테스트 디렉토리**: {{TEST_PATH}}

## 절차

### 1단계: 병렬 리뷰 (4개 에이전트를 동시에 호출한다)

다음 4개 에이전트를 **병렬로** 호출한다 (Task tool을 한 번에 4개 호출):

- Task(subagent_type='spec-reviewer'): spec 파일 경로와 구현 디렉토리를 전달 → MISS/DIFF 확인
- Task(subagent_type='code-reviewer'): 코드 품질, 타입 힌트, 패턴 검토
- Task(subagent_type='security-reviewer'): 인젝션 방지, 입력 검증, 시크릿 노출 검토
- Task(subagent_type='side-effect-analyzer'): Hook/Signal 체인, 공유 상태, 레이어 의존성 검토

### 2단계: 이슈 수정
에이전트들이 보고한 CRITICAL/HIGH 이슈를 모두 수정한다.

### 3단계: 테스트 및 lint/format/type check (변경 파일만)
수정 후 regression이 없는지 확인한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 모든 에이전트 리뷰 완료
- CRITICAL 이슈 0건
- HIGH 이슈 0건
- 수정 후 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

모든 조건 충족 시 <promise>REVIEW DONE</promise> 출력.
