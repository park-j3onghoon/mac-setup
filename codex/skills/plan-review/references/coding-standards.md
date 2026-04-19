# Coding Standards Review Reference

## Core Principles

- **언어별 관용구 준수** — 팀원이 읽기 쉽고 도구(linter, formatter)가 잘 지원한다.
- **타입 안전성 강화** — 런타임 에러를 컴파일/분석 시점으로 옮긴다. Any, !!, as 캐스팅 최소화.
- **네이밍 일관성** — 코드베이스 기존 용어와 일치. 같은 개념에 다른 단어 사용 금지.

## Checklist

### Python / Django
- 타입 힌트 약화 여부 (Any 추가, Optional 남용)
- import 최상단 배치 (함수 내부 import 금지, circular은 모듈 구조로 해결)
- dataclass > dict, Enum > string 상수
- Django ORM annotate ↔ dataclass 필드명 동기화

### Kotlin / Spring Boot
- data class 불변성, copy() 활용
- null safety: `!!` 사용 금지, `?.let` / `?:` / `requireNotNull` 활용
- `@field:NotBlank` 등 어노테이션 정확한 target 지정
- sealed class/interface로 타입 안전 분기

### 공통
- 매직 넘버 → 상수 추출 (의미 있는 이름)
- 2곳 이상 반복 로직 → 함수 추출 (DRY)
- 불필요한 default 값 제거 (모든 callsite가 명시 전달하면 default 불필요)
- 컬렉션 파라미터 non-nullable (`list[str] = []`, `None` 금지)
- 함수명 = 비즈니스 역할 (구현 세부사항 노출 금지)

### Frontend (Coding Standards에 흡수)
- 새 Vue 컴포넌트는 Composition API (script setup)
- Zod 스키마: `stringSchema()` 등 `@/schemas/common` 공유 유틸 우선
- watch handler에 구현 디테일 인라인 금지 → named method 추출
- v-b-popover .html modifier → `{ content, html: true }` 객체 형태

## Examples

```python
# 잘된 예시: non-nullable 컬렉션 + DRY
def filter_campaigns(
    statuses: list[str] = [],      # None 대신 빈 리스트 = "필터 없음"
    advertiser_ids: list[int] = [],
) -> list[Campaign]:
    qs = Campaign.objects.all()
    if statuses:
        qs = qs.filter(status__in=statuses)
    if advertiser_ids:
        qs = qs.filter(advertiser_id__in=advertiser_ids)
    return list(qs)
```

```kotlin
// 잘된 예시: null safety
fun findCampaign(id: Long): Campaign =
    campaignRepository.findByIdOrNull(id)
        ?: throw CampaignNotFoundException(id)  // !! 대신 명시적 예외
```

## User Preferences
- 인라인 가능하면 인라인, 100~110자 초과 시 변수 분리
- `__init__.py`에 불필요한 docstring 금지 (빈 파일)
- `**kwargs` spread 뒤에 명시적 파라미터 배치 (override 보장)
