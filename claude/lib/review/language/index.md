diff에 있는 언어마다 아래 모듈을 Read해 이 기준에 더한다.

- `.py` 파일이 있으면 `~/.claude/lib/review/language/python.md`
- `.go` 파일이 있으면 `~/.claude/lib/review/language/go.md`
- `.kt`·`.kts` 파일이 있으면 `~/.claude/lib/review/language/kotlin.md`
- `.js`·`.jsx`·`.ts`·`.tsx`·`.vue` 파일이 있으면 `~/.claude/lib/review/language/frontend.md`

## 출력 형식

```
### [언어]: [PASS / N건 발견]
- [CRITICAL/INFO] file:line · 설명
```
해당 언어 파일이 diff에 없으면: `[언어]: 해당 없음 (변경된 파일 없음)`
