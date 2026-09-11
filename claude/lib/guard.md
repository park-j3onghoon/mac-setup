# 안전 모드 규칙 (careful · freeze)

세션에 걸어 두는 두 가지 보호 장치다. 한 번 걸면 세션이 끝날 때까지 유지한다.

## careful: 위험 명령 경고

Bash로 아래 패턴을 실행하기 전에 사용자에게 먼저 경고하고 승인을 받는다.

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

**안전 예외**: 재생성 가능한 산출물 삭제는 경고 없이 실행한다: `rm -rf node_modules` / `.next` / `dist` / `__pycache__` / `.cache` / `build` / `coverage`.

경고는 금지를 풀지 않는다. force push처럼 CLAUDE.md가 하드룰로 막은 명령은 경고 대상이 아니라 실행 대상이 아니다.

## freeze: 디렉토리 편집 제한

제한 디렉토리 목록은 끝에 `/`를 붙여 기억한다. `/src/`로 두면 `/src-old/`가 안쪽으로 오인되지 않는다.

그 밖의 파일을 Edit/Write 해야 하면 먼저 확인을 받는다. "이 파일은 제한 디렉토리 외부입니다: [path]. 수정하시겠습니까?" 승인 후 편집한다.

Read·Grep·Glob·Bash는 평소대로 쓴다. 확인이 필요한 것은 Edit/Write뿐이다.

## 활성화 메시지

```
Guard 모드 활성화:
1. 위험 명령어 경고: rm -rf, DROP TABLE, force-push 등 실행 전 경고
2. 편집 제한: [path]/ 외부 파일 Edit/Write 시 확인 필요
해제: /guard off (편집 제한만) 또는 세션 종료 (전체)
```

## 해제

freeze만 푼다. 출력: "편집 제한이 해제되었습니다. 모든 디렉토리에서 편집 가능합니다." careful은 세션 종료 시까지 유지된다.
