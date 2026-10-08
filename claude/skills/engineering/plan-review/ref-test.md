`~/.claude/lib/coding/tests.md`를 Read하고 계획의 테스트를 그 규칙에 대어 본다.

## 체크리스트

- 계획 단계에서 새 코드패스마다 테스트할 경로(정상, 경계값, 에러)를 미리 적는다.
- expected 값은 비-기본값으로 고정한다 (전부 0/기본값이면 tautological test)

### 코드패스 추적
- 모든 분기 매핑 (if/else, switch, guard, try/catch)
- 데이터 흐름: 입력 → 변환 → 출력, 각 단계 실패 가능성
- 함수 호출 체인의 테스트 안 된 분기

### 사용자 흐름
- 동시 요청, 중복 호출, 타임아웃, 세션 만료
- 경계값: 빈 결과, 대량 결과, 최소/최대 입력
- 에러 상태: 사용자에게 보이는 에러, 복구 가능 여부

### E2E 결정 매트릭스
- 3개 이상 컴포넌트/서비스 걸치는 흐름 → E2E
- 모킹이 실제 장애를 숨기는 통합 지점 → E2E
- 인증/결제/삭제 같은 위험 경로 → E2E
- 순수 함수, 단일 서비스 → 단위 테스트

## 예시

```python
# 잘된 예시: 정상 + 경계값 + 에러 경로를 한 클래스에 모은다
class TestCampaignActivation:
    def test_activate_valid_campaign(self):
        """정상 활성화"""

    def test_activate_already_active_raises(self):
        """이미 활성 상태면 도메인 예외"""

    def test_activate_expired_campaign_raises(self):
        """만료된 캠페인 활성화 시도 → 도메인 예외"""

    def test_activate_zero_budget_raises(self):
        """예산 0 캠페인 → 도메인 예외"""
```
