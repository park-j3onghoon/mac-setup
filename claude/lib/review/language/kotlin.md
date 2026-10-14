## null safety
- nullable 값은 `!!` 대신 `?.let`·`?:`·`requireNotNull`로 다룬다.
- data class는 `val` 필드로 두고, 바꿀 때는 `copy()`로 새 값을 만든다.
- 필드 검증 어노테이션은 use-site target을 붙여 쓴다(`@field:NotBlank`).
- 정해진 종류로 나뉘는 타입은 sealed class·interface로 두고 `when`으로 분기한다.
