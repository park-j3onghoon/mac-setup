`~/.claude/lib/coding/db.md`를 Read하고 계획의 스키마·쿼리를 그 규칙에 대어 본다. 계획이 리포지토리를 새로 만들거나 바꾸면 `~/.claude/lib/coding/repositories.md`와 `~/.claude/lib/coding/architecture.md`도 Read해 대어 본다.

## 체크리스트

### 스키마 설계
- 정규화 수준 선택 근거
- 필드 타입 (금액 → Decimal, 수량 → PositiveIntegerField)
- nullable 필드의 비즈니스 근거 (None = "미입력"인지 "해당없음"인지)
- 엔티티 vs 값 객체 구분: `~/.claude/lib/coding/domain.md`를 Read하고 Entities and values 절로 판단한다

### 마이그레이션
- 마이그레이션은 별도 PR
- 마이그레이션 파일 존재 여부
- 하위 호환 배포 가능 (스키마 먼저 → 코드 배포 순서)
- 대규모 테이블 ALTER 시 온라인 DDL / pt-online-schema-change 사용 여부
- 데이터 마이그레이션과 스키마 마이그레이션 분리

### 쿼리 최적화
- 필요한 컬럼만 조회 (values/values_list, only/defer)
- JOIN 순서, GROUP BY/DISTINCT 정확성. 1:N JOIN 위의 카운팅은 중복 집계를 확인
- 서브쿼리 vs JOIN 선택 근거
- EXPLAIN 확인 필요한 복잡 쿼리 식별
- ORM annotate ↔ dataclass 필드명, SELECT ↔ INSERT 컬럼 동기화

### 인덱싱
- 새 WHERE/ORDER BY 조건에 인덱스 존재 여부
- 복합 인덱스 컬럼 순서 (카디널리티 높은 것 먼저)
- 불필요한 인덱스 식별 (조회 쿼리가 쓰지 않는 인덱스)

## 예시

```python
# 잘된 예시: ORM annotate ↔ dataclass 동기화
class CampaignStats(DataTransferObject):
    campaign_id: int
    impression_count: int  # annotate 필드와 1:1 대응
    click_count: int

qs = Campaign.objects.annotate(
    impression_count=Count("impressions"),  # dataclass 필드와 이름 일치
    campaign_id=F("id"),
    click_count=Count("clicks"),
).values("campaign_id", "impression_count", "click_count")
```
