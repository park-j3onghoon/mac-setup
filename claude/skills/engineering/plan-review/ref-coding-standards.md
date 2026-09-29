# Coding Standards Review Reference

네이밍은 `~/.claude/lib/coding/naming.md`, import 위치는 `~/.claude/lib/coding/file-layout.md`, 불필요한 default·컬렉션 파라미터는 `~/.claude/lib/coding/function.md`, boolean 대신 enum은 `~/.claude/lib/coding/ddd.md`, DRY와 Rule of Three는 `~/.claude/lib/coding/simple-design.md`, 관용구·타입 안전은 스택 파일(`~/.claude/lib/coding/python.md`·`~/.claude/lib/coding/frontend.md`)에 있다.

## Checklist

### Python / Django
- 타입 힌트 약화 여부 (Any 추가, Optional 남용)

### Kotlin / Spring Boot
- data class 불변성, copy() 활용
- null 처리는 `?.let` / `?:` / `requireNotNull`
- `@field:NotBlank` 등 어노테이션 정확한 target 지정
- sealed class/interface로 타입 안전 분기

## Examples

```kotlin
// 잘된 예시: null safety
fun findCampaign(id: Long): Campaign =
    campaignRepository.findByIdOrNull(id)
        ?: throw CampaignNotFoundException(id)  // !! 대신 명시적 예외
```
