# Security Review Reference

## Core Principles

- **Defense in depth** — 단일 보호 계층 실패 시 다음 계층이 방어. 인증 + 인가 + 입력 검증 + 출력 인코딩.
- **Least privilege** — 각 컴포넌트는 필요한 최소 권한만. DB 사용자, API 키, 파일 접근 모두 해당.
- **공격자처럼 생각, 보안 극장 금지** — 현실적 공격 경로 없으면 지적하지 않는다.
- 심층 보안 감사는 `/cso` 스킬로 위임. 여기서는 계획 레벨 점검만.

## Checklist

### OWASP Top 10 (계획 레벨)
- **A01 접근 제어**: 새 엔드포인트에 인증 데코레이터/미들웨어 있는지. IDOR (다른 사용자 데이터 접근).
- **A03 인젝션**: raw SQL에 사용자 입력 보간. ORM 쿼리로 대체 가능한지.
- **A05 보안 설정 오류**: CORS 와일드카드, DEBUG=True 프로덕션 노출.
- **A07 인증 실패**: JWT 만료 설정, 세션 관리 방식.
- **A10 SSRF**: 사용자 입력으로 URL 구성하여 내부 서비스 호출.

### 인증/인가
- 새 API 엔드포인트마다 인증 확인 (permission_classes, @login_required)
- 역할 기반 접근 제어(RBAC) 일관성 — 기존 패턴과 다르면 왜?
- 토큰 만료/갱신 메커니즘 존재 여부

### 입력 검증
- 사용자 입력 sanitization (HTML escape, SQL 파라미터 바인딩)
- 파일 업로드 검증 (타입, 크기, 내용)
- 경로 순회(path traversal) 방지 — os.path.join에 사용자 입력 직접 사용 금지

### 시크릿 관리
- 하드코딩된 시크릿, API 키 없는지
- .env가 .gitignore에 포함되어 있는지
- 에러 메시지에 내부 정보 노출 금지 (`str(e)` → 고정 문자열)

## Examples

```python
# 잘된 예시: 인증 + 입력 검증 + 안전한 에러
@login_required
@permission_required("campaign.edit")
def update_campaign(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id, owner=request.user)  # IDOR 방지
    serializer = CampaignSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)  # 입력 검증
    try:
        ...
    except Exception:
        logger.exception("campaign update failed")
        return Response({"error": "Internal Server Error"}, status=500)  # str(e) 노출 안 함
```

## User Preferences
- `except` 블록에서 `str(e)` 클라이언트 노출 금지
- 보안 극장 금지 — 실제 열린 문만 지적
