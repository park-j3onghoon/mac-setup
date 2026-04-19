# Performance Review Reference

## Core Principles

- **측정 없이 최적화하지 않는다** — 잘못된 병목에 시간 낭비 방지. 단, N+1은 무조건 잡는다.
- **캐싱은 일관성 비용을 동반한다** — stale data 버그, invalidation 복잡도를 사전에 식별.
- **O(n) 이하를 기본으로** — O(n²) 이상은 데이터 증가 시 급격히 악화.

## Checklist

### 쿼리 패턴
- N+1 쿼리: select_related/prefetch_related(Django), JOIN FETCH(JPA) 누락
- 루프 안 DB 호출 → 배치 조회로 전환
- 불필요한 쿼리 (같은 데이터 중복 조회)
- 새 WHERE/ORDER BY에 인덱스 존재 여부

### 메모리/CPU
- 대량 데이터 한번에 로드 (iterator/pagination 필요)
- 불필요한 리스트 변환 (list → set → list)
- 대량 객체 생성 (루프 안 ORM create → bulk_create)

### 알고리즘
- O(n²) 이상 중첩 루프 탐지
- 자료구조 선택 (list 순회 검색 → set/dict)
- 정렬이 필요한 곳에 정렬 안 된 자료구조 사용

### 비동기/배치
- 직렬 외부 API 호출 → asyncio.gather / 병렬화
- 대량 직렬 처리 → 배치 처리 (chunk)
- 캐싱 기회 (반복 조회, 변경 빈도 낮은 데이터)

### 동시성
- 레이스 컨디션: 여러 요청이 같은 레코드를 동시 수정 → select_for_update / optimistic lock
- 데드락: 트랜잭션 내 락 순서 일관성
- 트랜잭션 격리 수준: READ COMMITTED vs REPEATABLE READ 선택 근거
- Kotlin 코루틴 / Django async: 공유 상태 접근 시 동기화 메커니즘

## Examples

```python
# 잘된 예시: N+1 방지 + 배치 처리
campaigns = (
    Campaign.objects
    .select_related("advertiser")      # FK → JOIN
    .prefetch_related("creatives")     # M2M → 별도 쿼리 1회
    .filter(status="active")
)

# 잘된 예시: 레이스 컨디션 방지
with transaction.atomic():
    campaign = Campaign.objects.select_for_update().get(id=campaign_id)
    campaign.budget -= amount
    campaign.save()
```

## User Preferences
- 엣지 케이스 더 많이 처리
- 명시적 > 영리한
