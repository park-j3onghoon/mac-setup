---
name: guard
description: 이번 세션에 안전 모드를 건다 — 위험 명령 경고 + 지정 디렉토리 밖 편집 확인. `off` 로 편집 제한을 푼다.
disable-model-invocation: true
argument-hint: "[off]"
---

# /guard — 안전 모드

프로덕션 작업·라이브 디버깅처럼 되돌리기 어려운 실수가 비싼 세션에 **careful**(위험 명령 경고)과 **freeze**(디렉토리 편집 제한)를 건다. 인자가 `off` 면 3번만 수행한다.

## 1. 제한 디렉토리 확정

인자로 경로가 오면 그대로 쓰고, `/guard` 만 왔을 때 AskUserQuestion으로 묻는다 — "편집을 제한할 디렉토리를 지정해주세요. 이 경로 밖 파일의 Edit/Write는 확인 후 진행합니다." (현재 작업 디렉토리를 후보로 제시하고 직접 입력도 받는다. 여러 개면 목록으로 받는다.)

각 경로는 끝에 `/` 를 붙여 기억한다 — `/src/` 로 두면 `/src-old/` 가 안쪽으로 오인되지 않는다.

→ 완료: 슬래시로 끝나는 절대경로 목록이 확정됐다.

## 2. 활성화 선언

아래를 그대로 출력하고, 세션이 끝날 때까지 careful·freeze 를 적용한다.

```
Guard 모드 활성화:
1. 위험 명령어 경고 — rm -rf, DROP TABLE, force-push 등 실행 전 경고
2. 편집 제한 — [path]/ 외부 파일 Edit/Write 시 확인 필요
해제: /guard off (편집 제한만) 또는 세션 종료 (전체)
```

→ 완료: 메시지를 출력했고, 이후 모든 Bash·Edit·Write에 아래 두 규칙을 적용한다.

## 3. 해제 — `/guard off`

freeze 만 푼다. 출력: "편집 제한이 해제되었습니다. 모든 디렉토리에서 편집 가능합니다."

careful 은 세션 종료까지 남아 위험 명령 경고를 계속 낸다.

→ 완료: 해제 메시지를 냈고 모든 디렉토리에서 Edit/Write 가 열렸다.

## careful — 위험 명령 경고

Bash로 아래 패턴을 실행하기 전에 무엇이 왜 위험한지 알리고 사용자 승인을 받는다. CLAUDE.md 하드룰이 이미 금지한 명령(force push 등)은 승인이 나와도 절차만 안내한다 — 경고는 금지를 풀지 않는다.

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

**안전 예외** — 재생성 가능한 산출물 삭제는 경고 없이 실행한다: `rm -rf node_modules` / `.next` / `dist` / `__pycache__` / `.cache` / `build` / `coverage`.

## freeze — 디렉토리 편집 제한

제한 디렉토리 밖 파일을 Edit/Write 해야 하면 먼저 확인을 받는다 — "이 파일은 제한 디렉토리 외부입니다: [path]. 수정하시겠습니까?" 승인 후 편집한다.

Read·Grep·Glob·Bash 는 평소대로 쓴다. 확인이 필요한 것은 Edit/Write 뿐이다.
