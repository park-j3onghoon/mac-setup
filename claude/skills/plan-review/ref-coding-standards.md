# Coding Standards Review Reference

관용구·타입 안전·네이밍, import 위치, 불필요한 default, 컬렉션 파라미터, boolean 대신 enum(boolean trap), DRY와 Rule of Three는 `~/.claude/coding-rules.md` §2 Module · §3 Class/Object · §4 Function · §5 Naming · §9 Simple Design에 있다. 아래는 계획 리뷰에서 반복해 걸린 지점.

## Checklist

### Python / Django
- 타입 힌트 약화 여부 (Any 추가, Optional 남용)
- dataclass > dict, Enum > string 상수
- 계획이 새 boolean 파라미터를 도입하면 그 값이 답하는 축을 적는다 — 종류·상태·모드면 2-값이어도 enum

### Kotlin / Spring Boot
- data class 불변성, copy() 활용
- null 처리는 `?.let` / `?:` / `requireNotNull`
- `@field:NotBlank` 등 어노테이션 정확한 target 지정
- sealed class/interface로 타입 안전 분기

### Frontend
- 새 Vue 컴포넌트는 Composition API (script setup)
- Zod 스키마: `stringSchema()` 등 `@/schemas/common` 공유 유틸 우선
- watch handler는 named method를 호출한다 (구현 디테일은 그 메서드 안에)
- bootstrap-vue `v-b-popover`는 `.html` modifier 대신 `{ content, html: true }` 객체 형태
- flex 스크롤 컨테이너(`flex:1; overflow-y:auto`)를 grid area로 옮길 때: 부모 `grid-row`를 고정/제한 높이로 주고 flex 체인 전체에 `min-height:0`을 명시한다. `auto` row는 콘텐츠 누적 시 무한 성장하고, `min-height:0` 누락은 자동스크롤을 silent하게 깬다.

## Examples

```kotlin
// 잘된 예시: null safety
fun findCampaign(id: Long): Campaign =
    campaignRepository.findByIdOrNull(id)
        ?: throw CampaignNotFoundException(id)  // !! 대신 명시적 예외
```
