# Performance Review Reference

타임아웃·락 유지 범위·배치 실패 집계는 `~/.claude/coding-rules.md` §1 Architecture · §6 Errors에 있다. 아래는 계획 리뷰에서 반복해 걸린 지점.

## Core Principles

- 최적화는 측정된 병목에만: N+1은 측정 없이도 잡는다.
- 캐싱은 일관성 비용을 동반한다: stale data 버그, invalidation 복잡도를 사전에 식별.
- O(n) 이하를 기본으로: O(n²) 이상은 데이터 증가 시 급격히 악화.

## Checklist

### 쿼리 패턴
- N+1 쿼리: select_related/prefetch_related(Django), JOIN FETCH(JPA) 누락
- 루프 안 DB 호출 → 배치 조회로 전환
- 불필요한 쿼리 (같은 데이터 중복 조회)

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
- Read-after-write 전파 지연: 이벤트적 일관성 시스템(read replica, S3, 외부 거래소 포지션 API)은 write 성공 후에도 read가 옛 상태를 반환한다. write 응답값 자체를 source of truth 로 판정하고 후속 read는 보조 확인으로만 쓴다. 별도 read로 판정하면 "체결인데 미체결" 같은 오판이 blast radius 큰 분기에서 터진다.
- full-replace 쓰기 + 부분 수정 = lost-update 레이스: write API가 리소스를 전체 교체하면 한 필드만 바꾸려는 호출자가 read-modify-write를 하게 되고, 같은 레코드의 *다른* 필드를 동시 수정한 두 요청 중 나중 쓰기가 앞 변경을 덮는 silent lost-update 가 난다. 소유 서비스가 부분 업데이트(field-mask/PATCH) API를 제공해 각 수정이 자기 필드만 원자적으로 건드리게 한다.

### 멱등성 / dedup canonical 직렬화
- exact-string dedup 은 직렬화 결정성에 의존: 수신 측이 정규화 없이 `body == stored_body`로 중복을 거르면 송신 측 직렬화가 재호출마다 byte-동일해야 매칭된다. 안 맞으면 중복 레코드 → 머니패스면 더블 발송/결제.
- `json.dumps(sort_keys=True)`는 dict 키만 정렬하고 리스트 원소 순서는 그대로 둔다. 상위(DB/gRPC)가 `ORDER BY` 없이 리스트를 주면 호출마다 순서가 흔들려 같은 내용도 다른 문자열이 된다 → dedup miss. 모든 리스트 섹션을 안정 키로 명시 정렬한 뒤 직렬화하고, "상위 row 셔플 → 동일 문자열" 테스트로 고정한다. (숫자는 포맷 문자열/Decimal로 고정해 float drift도 제거.)

### 프론트엔드 데이터 캐시 (React Query / TanStack Query)
- queryKey는 구조 보존 배열 사용. 배열을 comma-join(`values.join(",")`)하면 `['a','b']`와 `['a,b']`가 충돌한다. `[path, ...primitives, array]` 형태로 배열 그대로 포함하면 React Query가 deep equality로 올바르게 구분.
- `refetchOnMount: "always"`는 staleTime을 사실상 무력화. staleTime을 설정해놓고도 `"always"`면 매 mount마다 stale 표시 + 백그라운드 fetch가 돌아 캐시 의미가 사라진다. `true`(stale일 때만 refetch)가 기본값으로 일관적.
- mutation onSuccess invalidation은 "모든 편집 경로"를 커버해야 유효. 훅 하나의 onSuccess만 invalidate하면 다른 훅/다른 탭/외부 경로 편집 후 목록이 stale. 목록 페이지가 네비게이션 허브인 경우 `refetchOnWindowFocus`도 고려.

## Examples

```python
# 잘된 예시: N+1 방지
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
