# Security 리뷰 기준

## 체크리스트

- Least privilege: 각 컴포넌트는 필요한 최소 권한만. DB 사용자, API 키, 파일 접근 모두 해당.
- 공격자처럼 생각한다: 현실적 공격 경로가 있는 것만 지적한다.
- 여기서는 계획 레벨 점검만 한다.

### OWASP Top 10
- `~/.claude/lib/owasp.md`를 Read하고 A01·A03·A05·A07·A10 항목을 계획이 새로 만드는 엔드포인트·쿼리·설정·인증·외부 호출에 대어 본다.

### 인증/인가
- RBAC 일관성. 기존 패턴과 다르면 왜?
- 토큰 만료/갱신 메커니즘 존재 여부

### 입력 검증
- 사용자 입력 sanitization (HTML escape, SQL 파라미터 바인딩)
- 파일 업로드 검증 (타입, 크기, 내용)
- 사용자 입력으로 만든 경로는 정규화 후 base 디렉토리 안인지 확인

### 시크릿 관리
- 하드코딩된 시크릿, API 키 없는지
- .env가 .gitignore에 포함되어 있는지

## 예시

```python
# 잘된 예시: 인증 + 입력 검증 + 안전한 에러
@login_required
@permission_required("book.edit")
def update_book(request, book_id):
    book = get_object_or_404(Book, id=book_id, owner=request.user)  # IDOR 방지
    serializer = BookSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)  # 입력 검증
    try:
        ...
    except Exception:
        logger.exception("book update failed")
        return Response({"error": "Internal Server Error"}, status=500)  # str(e) 노출 안 함
```
