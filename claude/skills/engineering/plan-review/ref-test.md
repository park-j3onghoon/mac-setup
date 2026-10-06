# Test Coverage 리뷰 기준

TDD 사이클, 테스트 네이밍·구조, 프레임워크가 보장해 테스트 범위 밖인 대상, flaky 제거, fixture/`now` 주입은 `~/.claude/lib/coding/tests.md`, Django REST 테스트 함정은 `~/.claude/lib/coding/tests-python.md`에 있다.

## 체크리스트

- 회귀 테스트: 기존 동작 변경 + 기존 테스트 미커버 = 회귀 테스트 필수.
- 계획 단계에서 각 새 코드패스가 어느 등급까지 커버되는지 미리 못 박는다.

### 코드패스 추적
- 모든 분기 매핑 (if/else, switch, guard, try/catch)
- 데이터 흐름: 입력 → 변환 → 출력, 각 단계 실패 가능성
- 함수 호출 체인의 테스트 안 된 분기

### 커버리지 등급
- ★★★: 엣지 + 에러 경로까지 커버
- ★★: happy path 만
- ★: 스모크 (존재 확인만)
- expected 값은 비-기본값으로 고정한다 (전부 0/기본값이면 tautological test)

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

## 예시

```python
# 잘된 예시: 정상 + 경계값 + 에러 경로를 한 클래스에 모은 ★★★ 커버리지
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
