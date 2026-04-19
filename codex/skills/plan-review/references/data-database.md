# Data/Database Review Reference

## Core Principles

- **스키마는 비즈니스 규칙의 마지막 방어선** — NOT NULL, UNIQUE, CHECK 제약으로 잘못된 데이터 진입 차단.
- **마이그레이션은 별도 PR** — 스키마 변경과 코드 변경의 롤백 독립성 확보.
- **인덱스는 쿼리 패턴을 따른다** — 잘못된 인덱스는 쓰기 성능 저하. 실제 WHERE/ORDER BY 기준으로 설계.

## Checklist

### 스키마 설계
- 정규화 수준 적절성 (과도한 정규화 → JOIN 폭발, 부족 → 갱신 이상)
- 필드 타입 적절성 (금액 → Decimal, 수량 → PositiveIntegerField)
- nullable 필드의 비즈니스 근거 (None = "미입력"인지 "해당없음"인지)
- 모델 필드명 = DB 컬럼명 일치
- DDD 엔티티(identity + lifecycle) vs 값 객체(equality by value) 구분

### 마이그레이션
- 마이그레이션 파일 존재 여부
- 하위 호환 배포 가능 (스키마 먼저 → 코드 배포 순서)
- 대규모 테이블 ALTER 시 온라인 DDL / pt-online-schema-change 고려
- 데이터 마이그레이션과 스키마 마이그레이션 분리

### 쿼리 최적화
- SELECT * 금지 → 필요한 컬럼만 (values/values_list, only/defer)
- JOIN 순서, GROUP BY/DISTINCT 정확성
- 서브쿼리 vs JOIN 선택 근거
- EXPLAIN 확인 필요한 복잡 쿼리 식별

### 인덱싱
- 새 WHERE/ORDER BY 조건에 인덱스 존재 여부
- 복합 인덱스 컬럼 순서 (카디널리티 높은 것 먼저)
- 불필요한 인덱스 식별 (거의 안 쓰는 인덱스 → 쓰기 부담)

## Examples

```python
# 잘된 예시: ORM annotate ↔ dataclass 동기화
class CampaignStats(DataTransferObject):
    campaign_id: int
    impression_count: int  # annotate 필드와 1:1 대응
    click_count: int

qs = Campaign.objects.annotate(
    impression_count=Count("impressions"),  # dataclass 필드와 이름 일치
    click_count=Count("clicks"),
).values("id", "impression_count", "click_count")
```

## User Preferences
- ORM annotate ↔ dataclass 필드 동기화 확인
- SELECT ↔ INSERT 컬럼 동기화
- 1:N 카운팅 중복 주의
