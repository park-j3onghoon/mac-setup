diff의 변경된 파일 언어를 감지하여 해당 언어의 관용구, 안전성, 플랫폼 특화 이슈를 검증한다.
diff에 Python·프론트엔드·DB·proto 파일이 있으면 `~/.claude/lib/coding/index.md`를 Read하고 그 목록에서 diff가 닿는 모듈을 Read하고, 그 모듈 첫머리가 가리키는 스택 파일 중 diff 언어의 것(`*-python.md`·`*-frontend.md`·`*-proto.md`)을 이 기준에 더한다. 프론트엔드 화면이면 `~/.claude/lib/coding/ui.md`, DB면 `~/.claude/lib/coding/db.md`도 Read해 더한다.

diff에 있는 언어마다 아래 모듈을 Read해 이 기준에 더한다.

- `.py` 파일이 있으면 `~/.claude/lib/review/language/python.md`
- `.go` 파일이 있으면 `~/.claude/lib/review/language/go.md`
- `.java` 파일이 있으면 `~/.claude/lib/review/language/java.md`
- `.kt`·`.kts` 파일이 있으면 `~/.claude/lib/review/language/kotlin.md`
- `.js`·`.jsx`·`.ts`·`.tsx`·`.vue` 파일이 있으면 `~/.claude/lib/review/language/frontend.md`

## 출력 형식

```
### [언어]: [PASS / N건 발견]
- [CRITICAL/INFO] file:line · 설명
```
해당 언어 파일이 diff에 없으면: `[언어]: 해당 없음 (변경된 파일 없음)`
