# Phase 19: 커밋

## 지시사항

모든 리뷰를 통과한 변경 사항을 커밋하라.

**Spec**:
{{SPEC_PATH}}
**구현 디렉토리**: {{MODULE_PATH}}
**체크리스트**: {{CHECKLIST_PATH}} (커밋 메시지 작성 시 참조용, 커밋 대상 아님)

## 절차

### 1단계: 최종 상태 확인

커밋 전 상태를 확인한다:
```bash
git status
git diff --stat $(git merge-base HEAD master)
```

### 2단계: 변경 파일 분류

{{MODULE_PATH}} 범위 내 변경된 파일을 확인하고 커밋 대상을 분류한다:
- 구현 코드 (.py)
- 테스트 코드 (tests/)
- 설정/기타 파일
- **제외**: .env, credentials, 임시 파일, .claude/rw-plan.md, .claude/rw-checklist.md, .claude/rw-spec-digest.md, .claude/rw-notes.md

### 3단계: pre-commit 확인
```bash
pre-commit run --files $(git diff --name-only $(git merge-base HEAD master) -- '*.py')
```
실패 시 자동 수정된 파일을 확인하고 반영한다.

### 4단계: 커밋 생성

{{CHECKLIST_PATH}}의 REQ 목록과 spec을 참조하여 커밋 메시지를 작성하고 커밋한다:
```bash
git add <변경 파일들>
git commit -m "<type>: <description>"
```

커밋 메시지 규칙:
- Conventional Commits 형식 (feat/fix/refactor/test/docs/chore)
- spec의 핵심 내용을 한 줄로 요약
- 본문에 주요 변경 사항 나열

## 완료 조건

- {{MODULE_PATH}} 범위의 모든 변경 파일이 커밋됨
- pre-commit 통과
- 커밋 메시지가 Conventional Commits 형식
- .env, 시크릿, .claude/rw-plan.md, .claude/rw-checklist.md, .claude/rw-spec-digest.md, .claude/rw-notes.md 등 민감/임시 파일 미포함
- git status가 clean (추적되지 않는 임시 파일 제외)

모든 조건 충족 시 <promise>COMMIT DONE</promise> 출력.
