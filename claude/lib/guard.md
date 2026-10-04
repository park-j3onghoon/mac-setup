# 안전 모드 규칙

## careful: 위험 명령 경고

Bash로 아래 패턴을 실행하기 전에 사용자에게 먼저 경고하고 승인을 받는다.

| 패턴 | 위험 |
|---|---|
| `rm -rf` / `rm -r` | 재귀 삭제 |
| `DROP TABLE` / `DROP DATABASE` | 데이터 손실 |
| `TRUNCATE` | 데이터 손실 |
| `kubectl delete` | 프로덕션 영향 |
| `docker system prune` | 컨테이너/이미지 손실 |

안전 예외: 재생성 가능한 산출물 삭제는 경고 없이 실행한다: `rm -rf node_modules` / `.next` / `dist` / `__pycache__` / `.cache` / `build` / `coverage`.

force push·`reset --hard`·`clean -f`·`checkout .`·`branch -D`는 명령만 보여 주고, 실행은 사용자가 `! <명령>`으로 한다.

## freeze: 디렉토리 편집 제한

제한 디렉토리 목록은 끝에 `/`를 붙여 기억한다.

그 밖의 파일을 Edit/Write 해야 하면 먼저 확인을 받는다. "이 파일은 제한 디렉토리 외부입니다: [path]. 수정하시겠습니까?" 승인 후 편집한다.

Read·Grep·Glob·Bash는 평소대로 쓴다.

## 활성화 메시지

```
Guard 모드 활성화:
1. 위험 명령어 경고: rm -rf, DROP TABLE, force-push 등 실행 전 경고
2. 편집 제한: [path]/ 외부 파일 Edit/Write 시 확인 필요
해제: /guard off (편집 제한만) 또는 세션 종료 (전체)
```
