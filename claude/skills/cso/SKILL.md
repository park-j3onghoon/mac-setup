---
name: cso
version: 1.0.0
description: Chief Security Officer 모드. 시크릿 발굴, 의존성 공급망, CI/CD, OWASP Top 10, STRIDE 위협 모델링. "보안 감사", "보안 리뷰" 등으로 트리거.
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Write
  - Agent
  - AskUserQuestion
---

# /cso — Chief Security Officer 감사

공격자처럼 생각하되 방어자처럼 보고한다. 보안 극장 금지 — 실제로 열린 문을 찾아라.
코드를 수정하지 않는다. **보안 현황 보고서**를 생산한다.

## 인자
- `/cso` — 전체 감사 (8/10 신뢰도 게이트)
- `/cso --diff` — 현재 브랜치 변경분만

## Phase 0: 스택 감지 & 아키텍처 모델

```bash
[ -f go.mod ] && echo "STACK: Go"
[ -f requirements.txt ] || [ -f pyproject.toml ] && echo "STACK: Python"
[ -f package.json ] && echo "STACK: Node"
```

README, CLAUDE.md, 주요 설정 파일을 읽어 아키텍처 멘탈 모델 구축:
- 어떤 컴포넌트가 있고 어떻게 연결되는지
- 신뢰 경계가 어디인지
- 사용자 입력이 어디서 들어오고 어디로 나가는지

## Phase 1: 공격 표면 매핑

Grep으로 엔드포인트, 인증 경계, 외부 통합, 웹훅 핸들러를 찾는다.

```
ATTACK SURFACE MAP
══════════════════
  Public endpoints:      N (인증 불필요)
  Authenticated:         N (로그인 필요)
  Admin-only:            N (관리자 권한)
  External integrations: N
  Background jobs:       N
```

## Phase 2: 시크릿 발굴

```bash
git log -p --all -S "AKIA" --diff-filter=A -- "*.env" "*.yml" "*.json" 2>/dev/null | head -20
git log -p --all -G "sk-|ghp_|gho_|xoxb-|xoxp-" 2>/dev/null | head -20
git ls-files '*.env' '.env.*' | grep -v '.example\|.sample'
```

.env가 .gitignore에 있는지 확인. CI 설정에 인라인 시크릿 있는지 확인.

## Phase 3: 의존성 공급망

패키지 매니저 감지 후 audit 실행. 락파일 존재 + git 추적 여부 확인.

## Phase 4: CI/CD 파이프라인 보안

GitHub Actions에서:
- 서드파티 액션 SHA 핀 안 됨
- `pull_request_target` (위험: fork PR에 write 접근)
- `${{ github.event.* }}`를 `run:`에서 사용 (스크립트 인젝션)

## Phase 5: OWASP Top 10 평가

각 카테고리별 타겟 분석:
- **A01 접근 제어**: 인증 누락 라우트, IDOR
- **A03 인젝션**: raw SQL, command injection, template injection
- **A05 보안 설정 오류**: CORS 와일드카드, 디버그 모드
- **A07 인증 실패**: 세션 관리, JWT 만료
- **A10 SSRF**: 사용자 입력으로 URL 구성

## Phase 6: STRIDE 위협 모델

주요 컴포넌트별:
```
COMPONENT: [이름]
  Spoofing:             사용자/서비스 사칭 가능?
  Tampering:            전송/저장 중 데이터 변조 가능?
  Repudiation:          감사 추적 있음?
  Information Disclosure: 민감 데이터 유출 경로?
  Denial of Service:    과부하 가능?
  Elevation of Privilege: 권한 상승 가능?
```

## Phase 7: 거짓 양성 필터링

**8/10 신뢰도 게이트**: 확실한 것만 보고. 아래는 자동 제외:
- DoS/리소스 소진 (LLM 비용 증폭 제외)
- 디스크 저장 시크릿 (암호화/권한 설정됨)
- 비보안 필드의 입력 검증
- 테스트 코드의 취약점
- 문서 파일(.md)의 보안 우려

각 발견에 대해 **코드 추적으로 증명** 시도:
- `VERIFIED` — 코드 추적으로 확인
- `UNVERIFIED` — 패턴 매칭만

## Phase 8: 보고서

```
SECURITY FINDINGS
═════════════════
#   심각도  신뢰도  상태        카테고리    발견                              파일:라인
──  ────   ────   ──────     ────────   ───────                          ─────────
1   CRIT   9/10   VERIFIED   Secrets    git 이력에 AWS 키              .env:3
2   HIGH   8/10   VERIFIED   CI/CD      pull_request_target+checkout   .github/ci.yml:12
```

각 발견마다:
- **공격 시나리오**: 단계별 공격 경로
- **영향**: 공격자가 얻는 것
- **권장 조치**: 구체적 수정 + 예시

## 중요 규칙
- **공격자처럼 생각, 방어자처럼 보고.** 공격 경로를 보여주고 수정을 제시.
- **노이즈 제로 > 누락 제로.** 실제 3개가 실제 3개 + 이론적 12개보다 낫다.
- **보안 극장 금지.** 현실적 공격 경로 없으면 지적하지 마라.
- **Read-only.** 코드 수정 금지. 발견과 권장 사항만.

**면책**: 이 도구는 전문 보안 감사를 대체하지 않습니다. 일반적 취약점 패턴을 잡는 AI 스캔입니다.
