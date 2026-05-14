# Test Coverage Review Reference

## Core Principles

- **TDD: 테스트 먼저, 구현은 테스트를 통과시키는 최소 코드** — AI 보조 코딩에서 테스트가 계약 역할.
- **회귀 테스트 IRON RULE** — 기존 동작 변경 + 기존 테스트 미커버 = 회귀 테스트 필수 (non-negotiable).
- **커스텀 로직만 테스트** — "이 테스트가 검증하는 건 우리 코드인가, 프레임워크인가?" 자문.

## Checklist

### 코드패스 추적
- 모든 분기 매핑 (if/else, switch, guard, try/catch)
- 데이터 흐름: 입력 → 변환 → 출력, 각 단계 실패 가능성
- 함수 호출 체인의 테스트 안 된 분기

### 커버리지 등급
- ★★★: 엣지 + 에러 경로까지 커버
- ★★: 정상 경로(happy path)만
- ★: 스모크 (존재 확인만)
- 형식적 검증 (expected 전부 0/기본값) 금지

### 사용자 흐름
- 동시 요청, 중복 호출, 타임아웃, 세션 만료
- 경계값: 빈 결과, 대량 결과, 최소/최대 입력
- 에러 상태: 사용자에게 보이는 에러, 복구 가능 여부

### E2E 결정 매트릭스
- 3개 이상 컴포넌트/서비스 걸치는 흐름 → E2E
- 모킹이 실제 장애를 숨기는 통합 지점 → E2E
- 인증/결제/삭제 같은 위험 경로 → E2E
- 순수 함수, 단일 서비스 → 단위 테스트

### ASCII 커버리지 다이어그램
```
[입력]─┬─[정상]──[변환]──[출력] ★★★
       ├─[빈 입력]──[빈 응답]    ★★
       ├─[잘못된 입력]──[에러]    ★★★
       └─[권한 없음]──[403]      ★★
```

### 테스트 금지 대상
- 프레임워크 빌트인 (Pydantic Field(gt=0), Enum 검증)
- 순수 데이터 객체 단독 테스트 (UseCase/Service에서 자연스럽게 검증)
- 스냅샷 테스트 (private dict 복붙 비교)
- 단순 조합 UseCase (필드 세팅만, 비즈니스 로직 없음) → View 통합테스트로 커버

### Django REST 테스트 함정
- **APIRequestFactory 는 URL resolve 를 거치지 않는다**: `api_rf.patch('/foo/1/bar', ...)` + `MyView.as_view()(request, ...)` 패턴은 view 함수를 직접 호출하므로 urls.py 의 path 문자열 오타가 404 이전엔 드러나지 않는다. URL 변경이 포함된 PR 에서는 `from django.urls import resolve` + `resolve('/actual/url').func.view_class is MyView` 스모크 1줄로 URL path ↔ view binding 을 잠근다.

## Examples

```python
# 잘된 예시: 경계값 + 에러 경로 커버
class TestCampaignActivation:
    def test_activate_valid_campaign(self):
        """정상 활성화"""
        ...

    def test_activate_already_active_raises(self):
        """이미 활성 상태면 도메인 예외"""
        with pytest.raises(CampaignAlreadyActiveError):
            ...

    def test_activate_expired_campaign_raises(self):
        """만료된 캠페인 활성화 시도 → 도메인 예외"""
        ...

    def test_activate_zero_budget_raises(self):
        """예산 0 캠페인 → 도메인 예외"""
        ...
```

## User Preferences

상세는 `~/.claude/coding-rules.md` 참조 (테스트 메서드명 영어, 중복 통합, 무효 케이스 전수 검증 불필요 등).
