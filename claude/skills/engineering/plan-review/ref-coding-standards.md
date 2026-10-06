# Coding Standards 리뷰 기준

네이밍은 `~/.claude/lib/coding/naming.md`, import 위치는 `~/.claude/lib/coding/file-layout.md`, 불필요한 default·컬렉션 파라미터는 `~/.claude/lib/coding/functions.md`, boolean 대신 enum과 타입 안전은 `~/.claude/lib/coding/types.md`, DRY와 Rule of Three는 `~/.claude/lib/coding/design.md`에 있다. 스택별 관용구는 각 모듈 첫머리가 가리키는 스택 파일(`*-python.md`·`*-frontend.md`)에 있다.

## 체크리스트

### Python / Django
- 타입 힌트 약화 여부 (Any 추가, 구체 타입 → Optional)

### Kotlin / Spring Boot
- data class 불변성, copy() 활용
- null 처리는 `?.let` / `?:` / `requireNotNull`
- `@field:NotBlank` 등 어노테이션 정확한 target 지정
- sealed class/interface로 타입 안전 분기

## 예시

```kotlin
// 잘된 예시: null safety
fun findBook(id: Long): Book =
    bookRepository.findByIdOrNull(id)
        ?: throw BookNotFoundException(id)  // !! 대신 명시적 예외
```
