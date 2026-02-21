# Phase 13: 코드 품질

## 지시사항

코드 품질에 집중하여 최종 검토하라. 타입 힌트, 네이밍, 에러 핸들링, 유지보수성을 중점적으로 본다.

**Spec**:
{{SPEC_PATH}}
**스펙 요약**: {{DIGEST_PATH}} (핵심 개념, 교차 참조, 전역 제약. 먼저 읽고 큰 그림을 파악하라.)
**구현 디렉토리**: {{MODULE_PATH}}
**테스트 디렉토리**: {{TEST_PATH}}
**메모**: {{NOTES_PATH}} (이전 Phase의 발견/수정 사항. 읽고 참조하라. 수정 시 기록하라.)

## 공통 원칙

1. **발견된 문제의 관련 영역도 재검토** — 문제 수정 후 영향받을 수 있는 코드를 추적하여 추가 검토
2. **모든 spec 파일을 매 이터레이션마다 함께 처리** — 체크리스트 라인 참조로 해당 줄만 Read
3. **이전 이터레이션 이어받기** — 체크리스트/결과 파일로 진행 상황 추적
4. **수정 발생 시 promise 출력 금지** — 수정 없는 클린 이터레이션에서만 promise 출력

## 절차

### 1단계: 코드 품질 검토

Task(subagent_type='quality-inspector')를 호출한다:
- 모든 public 함수에 타입 힌트가 있는지
- 반환 타입이 명시되었는지
- 변수/함수명이 의도를 명확히 전달하는지
- 도메인 용어와 일치하는지
- **긍정 네이밍 원칙**: 부정 표현(`is_invalid`, `not_found`, `cannot_*`, `lacks_*`) 대신 긍정 표현(`is_valid`, `exists`, `can_*`, `has_*`)을 사용하는지. 조건 분기도 `if is_valid` → 정상 로직, `else` → 에러 형태가 가독성이 높다.
- **기존 코드베이스의 네이밍 패턴과 일관성**: 동일/유사 기능의 함수가 다른 이름을 쓰고 있지 않은지 (예: 기존에 `get_by_id`이면 새 코드도 `get_by_id`, `fetch_by_id`로 섞지 않음). {{MODULE_PATH}}와 프로젝트의 기존 네이밍 패턴을 Grep으로 확인하고 불일치 시 통일한다.
- 에러 메시지가 디버깅에 충분한지
- 함수 50줄 이하, 파일 800줄 이하
- 중복 코드, 매직 넘버, 불필요한 복잡성

### 2단계: 이슈 수정

quality-inspector가 보고한 CRITICAL/HIGH 이슈를 수정한다.

수정 사항을 {{NOTES_PATH}}에 기록한다.

### 3단계: 테스트 및 lint/format/type check

```bash
docker exec "$DEV_CONTAINER" pytest {{TEST_PATH}} --reuse-db -v
uv run ruff check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run ruff format --check $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
uv run mypy $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```

**수정이 있었으면 promise를 출력하지 않는다.**

## 완료 조건

- quality-inspector CRITICAL/HIGH 이슈 0건
- 기존 코드베이스와 네이밍 패턴 일관성 확인 완료
- 모든 public 함수에 타입 힌트 존재
- 함수 50줄 이하
- 파일 800줄 이하
- 테스트 전체 통과
- 변경 파일 ruff check/format/mypy 통과

- **클린 이터레이션 ≥ 1** (수정 없는 이터레이션이 최소 1회 있어야 함)

모든 조건 충족 시 <promise>QUALITY DONE</promise> 출력.
