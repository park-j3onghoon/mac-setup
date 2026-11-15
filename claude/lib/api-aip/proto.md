## 형태

- 리소스 메시지: 식별 필드는 relative resource name을 담는 `name` 하나, 사람용 이름은 `display_name`, 시간은 `create_time`/`update_time`(`OUTPUT_ONLY`), 낙관적 동시성은 `etag`(`~/.claude/lib/api-aip/aip/154.md`). `google.api.resource` 옵션에 `type`·`pattern`·`singular`·`plural`.
- 모든 RPC에 반드시 `google.api.http`로 HTTP 메서드·경로를 정의한다; 양방향 스트리밍만 예외로 `google.api.http`를 달지 않고(권장) 스트리밍 없는 대체 RPC를 둔다(권장).
- 동사는 `get`·`post`·`patch`·`delete`만, `put`·`custom`은 쓰지 않는다(권장); 표준 메서드는 정해진 동사가 반드시, 커스텀 메서드는 권장.
- URI 변수는 반드시 `{field=pattern}` 문법이고 리소스 이름은 반드시 ID만이 아니라 전체를 받는다(`{name=publishers/*/books/*}`); 중첩 필드 변수(`{book.name=...}`)도 된다.
- ID 자리는 반드시 `*`(`/`를 뺀 URL-safe 문자에 매칭); `/`까지 받아야 하면 마지막 세그먼트에 `**`를 써도 된다.
- `body`는 HTTP 본문이 될 최상위 필드 하나(`"*"`면 요청 메시지 전체)다; `GET`·`DELETE`는 반드시 `body` 없음, Create·Update는 반드시 정해진 body(리소스 필드), 커스텀 메서드는 정해진 body(권장).
- `body` 필드는 반드시 중첩 필드(`.`)가 아니고, URI 변수와 같은 필드가 아니며, repeated가 아니다.
- URI·body에 없는 필드는 쿼리 파라미터가 되고, 클라이언트는 필드 이름을 camelCase로 보낸다.
- `json_name`으로 JSON 이름을 바꾸지 않는다(권장, 하위 호환 목적만 예외).
- `additional_bindings`는 몇 개든 둬도 되지만 그 안에 다시 중첩하지 않고(반드시) `body`는 최상위와 반드시 같다.
- 필드는 `snake_case`, repeated는 복수형. enum 0번 값은 `~/.claude/lib/coding/api-proto.md`를 Read하고 그 Enum zero value를 따른다.
- enum은 한 메시지에서만 쓰면 그 메시지 안에 중첩하고 0번을 뺀 값은 `CREATE`처럼 값 이름만 쓴다. 여러 메시지에서 쓰면 패키지 레벨에 두고 값마다 `OPERATION_CREATE`처럼 enum 이름 접두어를 붙인다.
- 정확한 메시지 골격은 `~/.claude/lib/api-aip/aip/131-135.md`를 Read하고 메서드마다 그 뼈대를 따른다. List면 `~/.claude/lib/api-aip/aip/158.md`도 Read하고 따른다.

## 작성 후 체크

- [ ] 새로 쓰는 google proto import(`google/api/resource.proto` 등)를 빌드가 찾는다(못 찾으면 그 proto를 추가하는 선행 PR을 먼저 낸다)
- [ ] 리소스에 `google.api.resource` 옵션 + `name` 필드
- [ ] 모든 동작이 표준 메서드이거나, 커스텀 메서드 `:verb`에 정당화 한 줄이 붙었다
- [ ] 요청에 쓰이는 메시지(리소스 포함)의 모든 필드에 `field_behavior`(`~/.claude/lib/api-aip/aip/203.md`) 명시
- [ ] `~/.claude/lib/api-aip/index.md` 적용/보류 정책 절의 커서/offset 혼용 기준으로 List 페이지네이션 방식을 골랐고, 커서면 `page_size`/`page_token`/`next_page_token`
- [ ] 리소스 스키마가 Get/Create/Update/List에서 동일
- [ ] 기존 필드번호·타입·의미가 그대로다. additive-only
- [ ] `buf lint` 경고가 없거나, 남은 경고가 전부 AIP와 부딪히는 규칙(중첩 enum 값의 `ENUM_VALUE_PREFIX` 등)에서 난다
