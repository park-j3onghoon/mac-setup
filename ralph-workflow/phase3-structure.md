# Phase 3: 구조 개선

## 지시사항

코드 구조를 CLAUDE.md에 명시된 아키텍처 원칙에 맞게 최적화하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}

## 절차

### 1단계: 구조 최적화
Task(subagent_type='structure-optimizer')를 호출한다:
- 50줄 초과 함수, 400줄 초과 파일 분리
- 기존 코드와 재사용 가능한 부분 탐색
- 데드코드 정리
- 아키텍처 구조 정합성 검증
- 확장성 검증: OCP 준수, 새 타입/케이스 추가 시 변경 범위 최소화, 인터페이스 설계 적절성

### 2단계: 잔여 이슈 수정
structure-optimizer가 보고한 잔여 이슈(MEDIUM 이하) 중 수정 가능한 항목을 처리한다:
- 재사용 기회로 보고된 코드 통합
- 400줄 초과 파일 분리 검토 (800줄 이하라도)
- 구조 변경 후 import 경로 정리

### 3단계: 테스트 실행
구조 변경 후 모든 테스트가 통과하는지 확인한다:
```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
```

### 4단계: lint/format/type check (변경 파일만)
```bash
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

## 완료 조건

- 50줄 초과 함수 없음
- 800줄 초과 파일 없음
- 레이어 의존성 위반 없음
- 데드코드 없음
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

모든 조건 충족 시 <promise>REFACTOR DONE</promise> 출력.
