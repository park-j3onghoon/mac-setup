---
name: cso
description: Read-only 보안 감사. 시크릿·공급망·CI/CD·OWASP·STRIDE를 훑어 exploitable한 발견만 보고서로 낸다.
disable-model-invocation: true
---

red-team 관점으로 파고들고 blue-team 관점으로 보고한다. 코드는 읽기만 하고, 산출물은 보안 현황 보고서 하나다.

대상은 레포 전체이고 Phase 0-8을 전부 돈다.

## Phase

0. 위협 모델: 대상 레포의 README와 주요 설정을 읽고 컴포넌트 연결, 신뢰 경계, 사용자 입력의 진입점·유출점을 적는다. → 완료: 세 항목이 각각 채워짐.
1. 공격 표면 매핑: `~/.claude/skills/cso/scan-commands.md`를 Read하고, 엔드포인트·인증 경계·외부 통합·웹훅 핸들러를 열거해 `ATTACK SURFACE MAP`을 채운다. → 완료: 찾은 라우트가 `ATTACK SURFACE MAP`의 칸 중 하나에 전부 배정됨.
2. 시크릿 발굴: `~/.claude/skills/cso/scan-commands.md`의 `시크릿 발굴 git 3종` 명령으로 이력과 추적 파일을 훑고, `.env`가 `.gitignore`에 있는지와 CI 설정에 인라인 시크릿이 있는지 본다. → 완료: 이력·추적 파일·CI 설정 3경로가 전부 스캔됨.
3. 의존성 공급망: 패키지 매니저의 audit을 돌리고, 락파일이 있고 git에 추적되는지 본다. → 완료: audit 출력과 락파일 상태가 확인됨.
4. CI/CD 파이프라인: `.github/workflows/`의 워크플로마다 `~/.claude/skills/cso/scan-commands.md`의 `GitHub Actions 3종 점검`을 적용한다. → 완료: 워크플로 파일 전부가 3종 점검을 거침.
5. OWASP Top 10: `~/.claude/lib/owasp.md`를 Read하고 A01·A03·A05·A07·A10을 그 문서의 항목과 증명 방식으로 판정한다. → 완료: 5개 모두 발견 또는 PASS 또는 해당 없음으로 판정됨.
6. STRIDE 위협 모델: `~/.claude/skills/cso/scan-commands.md`의 `STRIDE 6축` 템플릿을 컴포넌트마다 채운다. → 완료: Phase 0에서 잡은 컴포넌트 전부가 템플릿을 갖춤.
7. 거짓 양성 필터링: 아래 보고 게이트를 적용한다. → 완료: 남은 발견 전부에 VERIFIED/UNVERIFIED 태그가 붙음.
8. 보고서: 아래 형식으로 낸다. → 완료: 표와 발견별 3필드가 채워짐.

## 보고 게이트

신뢰도 8/10 이상이면서 현실적 공격 경로가 있는 exploitable 한 발견만 보고한다. 아래 다섯은 보고 대상에서 뺀다.

- DoS/리소스 소진
- 디스크에 저장된 시크릿(암호화·권한이 설정된 경우)
- 비보안 필드의 입력 검증
- 테스트 코드의 취약점
- 문서 파일(.md)의 보안 우려

발견마다 `~/.claude/lib/owasp.md`의 증명 방식 절을 따라 증명을 시도하고 `VERIFIED`·`UNVERIFIED`를 붙인다.

## 보고서 형식

```
SECURITY FINDINGS
═════════════════
#   심각도  신뢰도  상태        카테고리    발견                     파일:라인
──  ────   ────   ──────     ────────   ───────                 ─────────
1   CRIT   9/10   VERIFIED   Secrets    git 이력에 AWS 키        .env:3
```

심각도는 CRIT/HIGH/MED/LOW, 신뢰도는 `n/10`. 발견마다 공격 시나리오 · 영향 · 권장 조치(구체적 수정 + 예시)를 붙인다. 보고서는 채팅으로 내고, 사용자가 파일을 요청하면 `security-report.md`로 남긴다. 저장 경로는 `~/.claude/lib/plans-path.md`를 Read하고 그 규칙을 따른다.
