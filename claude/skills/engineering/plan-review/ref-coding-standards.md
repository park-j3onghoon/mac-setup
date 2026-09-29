# Coding Standards Review Reference

관용구·타입 안전·네이밍, import 위치, 불필요한 default, 컬렉션 파라미터, boolean 대신 enum, DRY와 Rule of Three는 `~/.claude/lib/coding-rules.md` Module·Class / Object·Function·Naming·Simple Design & Refactoring 절에 있다.

## Checklist

### Python / Django
- 타입 힌트 약화 여부 (Any 추가, Optional 남용)
- dataclass > dict, Enum > string 상수

### Kotlin / Spring Boot
- data class 불변성, copy() 활용
- null 처리는 `?.let` / `?:` / `requireNotNull`
- `@field:NotBlank` 등 어노테이션 정확한 target 지정
- sealed class/interface로 타입 안전 분기

### Frontend
- 새 Vue 컴포넌트는 Composition API (script setup)
- Zod 스키마: `stringSchema()` 등 `@/schemas/common` 공유 유틸 우선
- watch handler는 named method를 호출한다 (구현 디테일은 그 메서드 안에)

## Examples

```kotlin
// 잘된 예시: null safety
fun findCampaign(id: Long): Campaign =
    campaignRepository.findByIdOrNull(id)
        ?: throw CampaignNotFoundException(id)  // !! 대신 명시적 예외
```
