---
name: cso
description: Read-only 보안 감사. 시크릿·공급망·CI/CD·OWASP·STRIDE를 훑어 exploitable한 발견만 보고서로 낸다.
disable-model-invocation: true
argument-hint: "[--diff]"
---

red-team 관점으로 파고들고 blue-team 관점으로 보고한다. Read-only 감사라 코드는 고치지 않고, 산출물은 보안 현황 보고서 하나다.

## 범위

- `/cso`: 레포 전체. Phase 0-8 전부.
- `/cso --diff`: 현재 브랜치 변경분만. 아래 목록이 감사 대상이다.

```bash
BASE=$(git merge-base HEAD origin/master 2>/dev/null || git merge-base HEAD origin/main)
git diff --name-only $BASE..HEAD
```

`--diff`에서 Phase 0·6은 이 파일들이 닿는 컴포넌트로 좁히고, Phase 2의 이력 스캔·Phase 3·Phase 4는 목록에 `.env*`·락파일·`.github/`가 있을 때만 돈다.

## Phase

0. **위협 모델**: 대상 레포의 README와 주요 설정을 읽고 컴포넌트 연결, 신뢰 경계, 사용자 입력의 진입점·유출점을 적는다. 완료 = 세 항목이 각각 채워짐.
1. **공격 표면 매핑**: `~/.claude/skills/cso/scan-commands.md`를 Read하고(Phase 1·2·4·6이 쓰는 명령과 출력 템플릿이 들어 있다), 엔드포인트·인증 경계·외부 통합·웹훅 핸들러를 열거해 `ATTACK SURFACE MAP`을 채운다. 완료 = 찾은 라우트가 5칸 중 하나에 전부 배정됨.
2. **시크릿 발굴**: `scan-commands.md`의 git 3종 명령으로 이력과 추적 파일을 훑고, `.env`가 `.gitignore`에 있는지와 CI 설정에 인라인 시크릿이 있는지 본다. 완료 = 이력·추적 파일·CI 설정 3경로가 전부 스캔됨.
3. **의존성 공급망**: 패키지 매니저의 audit을 돌리고, 락파일이 있고 git에 추적되는지 본다. 완료 = audit 출력과 락파일 상태가 확인됨.
4. **CI/CD 파이프라인**: `.github/workflows/`의 워크플로마다 `scan-commands.md`의 `GitHub Actions 3종 점검`을 적용한다. 완료 = 워크플로 파일 전부가 3종 점검을 거침.
5. **OWASP Top 10**: 아래 5개를 각각 판정한다. 완료 = 5개 모두 발견 또는 해당 없음으로 판정됨.
   - **A01 접근 제어**: 인증 누락 라우트, IDOR
   - **A03 인젝션**: raw SQL, command injection, template injection
   - **A05 보안 설정 오류**: CORS 와일드카드, 디버그 모드
   - **A07 인증 실패**: 세션 관리, JWT 만료
   - **A10 SSRF**: 사용자 입력으로 URL 구성
6. **STRIDE 위협 모델**: `scan-commands.md`의 `STRIDE 6축` 템플릿을 컴포넌트마다 채운다. 완료 = Phase 0에서 잡은 컴포넌트 전부가 템플릿을 갖춤.
7. **거짓 양성 필터링**: 아래 보고 게이트를 적용한다. 완료 = 남은 발견 전부에 VERIFIED/UNVERIFIED 태그가 붙음.
8. **보고서**: 아래 형식으로 낸다. 완료 = 표와 발견별 3필드가 채워짐.

## 보고 게이트

신뢰도 8/10 이상이면서 현실적 공격 경로를 코드로 보인 발견만 보고한다(exploitable-only). 아래 다섯은 보고 대상에서 뺀다.

- DoS/리소스 소진
- 디스크에 저장된 시크릿(암호화·권한이 설정된 경우)
- 비보안 필드의 입력 검증
- 테스트 코드의 취약점
- 문서 파일(.md)의 보안 우려

발견마다 source→sink 코드 추적으로 증명을 시도하고 결과를 태그한다. `VERIFIED`는 코드 추적으로 확인한 것, `UNVERIFIED`는 패턴 매칭까지만 한 것.

## 보고서 형식

```
SECURITY FINDINGS
═════════════════
#   심각도  신뢰도  상태        카테고리    발견                     파일:라인
──  ────   ────   ──────     ────────   ───────                 ─────────
1   CRIT   9/10   VERIFIED   Secrets    git 이력에 AWS 키        .env:3
```

심각도는 CRIT/HIGH/MED/LOW, 신뢰도는 `n/10`. 발견마다 **공격 시나리오** · **영향** · **권장 조치**(구체적 수정 + 예시)를 붙인다. 보고서는 채팅으로 내고, 파일로 남길 때만 `~/plans/{repo}/{작업명}/security-report.md`에 쓴다.
