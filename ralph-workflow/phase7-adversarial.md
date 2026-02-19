# Phase 7: 적대적 리뷰

## 지시사항

이 코드를 reject하려는 시니어 리뷰어 관점에서 결함을 찾고 수정하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}

## 절차

### 1단계: 적대적 리뷰
Task(subagent_type='adversarial-reviewer')를 호출한다:
- Spec 한 줄씩 대조
- 비즈니스 규칙 전수 검사
- 테스트 assert 유효성 검증
- 에러 핸들링 완전성
- 네이밍 일관성
- 아키텍처 위반
- DDD 레이어 의존성 방향 검증

### 2단계: 결함 수정
adversarial-reviewer가 REJECT 사유로 보고한 항목을 모두 수정한다.

### 3단계: 의문 사항 해소
"확인 필요" 카테고리의 항목들을 코드/spec 대조하여 해소한다.

### 4단계: 테스트 및 lint/format/type check (변경 파일만)
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

### 5단계: 재리뷰
수정 후 adversarial-reviewer를 다시 호출하여 APPROVE 판정을 받는다.

## 완료 조건

- adversarial-reviewer 판정: APPROVE 또는 APPROVE WITH COMMENTS
- REJECT 사유 0건
- 모든 테스트 통과
- ruff check/format/mypy 통과

모든 조건 충족 시 <promise>ADVERSARIAL DONE</promise> 출력.
