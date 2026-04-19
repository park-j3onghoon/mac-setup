# Architecture Review Reference

## Core Principles

- **단방향 의존성** — A→B이면 B→A 금지. 순환이 되면 분리한 의미가 없다. domain ← application ← infrastructure.
- **SOLID** — SRP(변경 이유 1개), OCP(확장 열림, 수정 닫힘), DIP(구체가 아닌 추상에 의존). LSP/ISP는 위반 시에만 지적.
- **KISS / YAGNI** — 예측이 아닌 현재 요구사항에 집중. 한 번만 쓰는 코드에 과도한 추상화 금지.
- **상태는 resolve가 아니라 저장** — 이벤트 기반 동작은 다른 필드에서 계산 불가. 상태 전이 다이어그램과 종결 조건을 초기에 확정.

## Checklist

### 의존성 방향
- 순환 의존 → critical 이슈
- 레이어 역방향 참조 (domain이 infrastructure 임포트)
- 패키지/모듈 간 숨겨진 결합 (공유 상태, 글로벌 변수)

### 컴포넌트 경계
- 새 서비스/모듈의 책임이 명확한지 (SRP)
- 기존 모듈에 추가하는 게 더 적절한지
- 단일 장애점 존재 여부
- bounded context 경계가 비즈니스 도메인과 일치하는지

### API 계약 설계
- REST: 리소스 중심 URL, HTTP 메서드 의미 일치
- 버전관리: URL prefix(/v1/) 또는 헤더
- 하위호환: 필드 추가 OK, 삭제/타입변경 시 deprecation 기간
- 에러 응답 포맷 일관성 (status code + error body)
- 페이지네이션: cursor vs offset 선택 근거

### DDIA 원칙
- 데이터 모델 선택 적절성 (관계형 vs 문서 vs 그래프)
- 일관성 모델의 의도적 선택 (strong vs eventual)
- 읽기/쓰기 비율에 따른 설계 (read-heavy → 캐시/복제, write-heavy → 파티셔닝)

## Examples

```python
# 잘된 예시: 레이어 의존성이 올바른 구조
# domain/ — 외부 의존 없음
class Campaign:
    def can_activate(self) -> bool: ...

# application/ — domain만 참조
class ActivateCampaignUseCase:
    def __init__(self, repo: CampaignRepository): ...  # DIP: 추상에 의존

# infrastructure/ — application, domain 참조
class DjangoCampaignRepository(CampaignRepository): ...
```

## User Preferences
- 최소 diff, boring by default, incremental > revolutionary
- 상태 설계가 구현보다 선행
- essential vs accidental complexity 구분
