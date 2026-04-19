---
name: guard
version: 1.0.0
description: 안전 모드. 위험 명령어 경고 + 디렉토리 편집 제한. 프로덕션 작업, 라이브 디버깅 시 사용. "안전 모드", "조심해서", "guard" 등으로 트리거.
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
---

# /guard — 안전 모드

위험 명령어 경고 + 디렉토리 편집 제한을 활성화한다.

## 활성화

AskUserQuestion으로 편집 제한 디렉토리를 물어본다:
"편집을 제한할 디렉토리를 지정해주세요. 이 경로 외부 파일의 Edit/Write가 차단됩니다."

## 위험 명령어 경고 (careful)

아래 패턴이 Bash에서 실행되기 전에 **반드시 사용자에게 경고**:

| 패턴 | 예시 | 위험 |
|---|---|---|
| `rm -rf` / `rm -r` | `rm -rf /var/data` | 재귀 삭제 |
| `DROP TABLE` / `DROP DATABASE` | `DROP TABLE users;` | 데이터 손실 |
| `TRUNCATE` | `TRUNCATE orders;` | 데이터 손실 |
| `git push --force` / `-f` | `git push -f origin main` | 이력 덮어쓰기 |
| `git reset --hard` | `git reset --hard HEAD~3` | 커밋 안 된 작업 손실 |
| `git checkout .` / `git restore .` | `git checkout .` | 변경 손실 |
| `kubectl delete` | `kubectl delete pod` | 프로덕션 영향 |
| `docker system prune` | `docker system prune -a` | 컨테이너/이미지 손실 |

### 안전 예외
경고 없이 허용:
- `rm -rf node_modules` / `.next` / `dist` / `__pycache__` / `.cache` / `build` / `coverage`

## 디렉토리 편집 제한 (freeze)

사용자가 지정한 디렉토리 외부의 파일에 대해 Edit/Write 시도 시 **반드시 사용자에게 확인**:
"이 파일은 제한 디렉토리 외부입니다: [path]. 수정하시겠습니까?"

### 제한 규칙
- Read, Grep, Glob, Bash는 제한 없음 — Edit/Write만 제한
- 디렉토리 경로 끝에 `/` 추가하여 `/src`가 `/src-old`와 매칭되지 않도록

## 해제
`/unfreeze`를 실행하거나 세션을 종료하면 편집 제한이 해제된다.

위험 명령어 경고는 세션 종료 시까지 유지된다.

## 활성화 메시지
```
Guard 모드 활성화:
1. 위험 명령어 경고 — rm -rf, DROP TABLE, force-push 등 실행 전 경고
2. 편집 제한 — [path]/ 외부 파일 Edit/Write 시 확인 필요
해제: /unfreeze (편집 제한만) 또는 세션 종료 (전체)
```
