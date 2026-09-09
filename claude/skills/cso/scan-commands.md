# 스캔 명령·출력 템플릿

명령은 대상 레포 루트에서 실행한다.

## ATTACK SURFACE MAP

```
ATTACK SURFACE MAP
══════════════════
  Public endpoints:      N (인증 불필요)
  Authenticated:         N (로그인 필요)
  Admin-only:            N (관리자 권한)
  External integrations: N
  Background jobs:       N
```

## 시크릿 발굴 git 3종

```bash
git log -p --all -S "AKIA" --diff-filter=A -- "*.env" "*.yml" "*.json" 2>/dev/null | head -20
git log -p --all -G "sk-|ghp_|gho_|xoxb-|xoxp-" 2>/dev/null | head -20
git ls-files '*.env' '.env.*' | grep -v '.example\|.sample'
```

토큰 접두어 `AKIA`·`sk-`·`ghp_`·`gho_`·`xoxb-`·`xoxp-`가 이 스캔이 걸러내는 대상이다. 첫 명령은 새로 추가된 3개 확장자만 보고 `head -20`은 패치 앞부분만 보여주므로, 히트가 하나라도 나오면 그 커밋·파일을 직접 열어 범위를 넓힌다.

## GitHub Actions 3종 점검

- 서드파티 액션이 SHA로 핀되지 않음(태그·브랜치 참조)
- `pull_request_target` — fork PR에 write 접근이 붙는다(pwn request)
- `${{ github.event.* }}`를 `run:` 안에서 사용(스크립트 인젝션)

## STRIDE 6축

```
COMPONENT: [이름]
  Spoofing:               사용자/서비스 사칭 가능?
  Tampering:              전송/저장 중 데이터 변조 가능?
  Repudiation:            감사 추적 있음?
  Information Disclosure: 민감 데이터 유출 경로?
  Denial of Service:      과부하 가능?
  Elevation of Privilege: 권한 상승 가능?
```
