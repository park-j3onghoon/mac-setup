## 형태

- 리소스 메시지: 식별 필드는 relative resource name을 담는 `name` 하나, 사람용 이름은 `display_name`, 시간은 `create_time`/`update_time`(`OUTPUT_ONLY`), 낙관적 동시성은 `etag`(`~/.claude/lib/api-aip/aip/154.md`). `google.api.resource` 옵션에 `type`·`pattern`·`singular`·`plural`.
- RPC명 = `{Verb}{Resource}`, List만 복수(`ListBooks`). 표준 5개에 `google.api.http` 매핑을 붙이고, Custom은 `post: "/v1/{name=…}:archive"`.
- 요청/응답 필드: Get은 `name`. List는 `parent`+`page_size`+`page_token`+`filter`+`order_by` → 응답은 결과 repeated가 필드번호 1, 그다음 `next_page_token`, `total_size`(optional). Create는 `parent`+리소스+`{resource}_id`(optional). Update는 리소스+`update_mask`. Delete는 `name`+`etag`(optional)+`force`(optional, 자식까지 cascading).
- 응답은 리소스 자체를 반환한다.
- 필드는 `snake_case`, repeated는 복수형. enum 0번 값은 `~/.claude/lib/coding/api-proto.md`를 Read하고 그 Enum zero value를 따른다.
- enum은 한 메시지에서만 쓰면 그 메시지 안에 중첩하고 0번을 뺀 값은 `CREATE`처럼 값 이름만 쓴다. 여러 메시지에서 쓰면 패키지 레벨에 두고 값마다 `OPERATION_CREATE`처럼 enum 이름 접두어를 붙인다.
- field_behavior(`~/.claude/lib/api-aip/aip/203.md`)를 모든 필드에 명시한다: `REQUIRED`·`OPTIONAL`·`OUTPUT_ONLY`·`IMMUTABLE`·`INPUT_ONLY`.
- 정확한 메시지 골격은 메서드마다 그 파일을 Read하고 그 뼈대를 따른다: Get `~/.claude/lib/api-aip/aip/131.md`, List `~/.claude/lib/api-aip/aip/132.md`와 `~/.claude/lib/api-aip/aip/158.md`, Create `~/.claude/lib/api-aip/aip/133.md`, Update `~/.claude/lib/api-aip/aip/134.md`, Delete `~/.claude/lib/api-aip/aip/135.md`.

## LRO

즉시 끝나지 않는 작업(배치·대용량 생성)은 `google.longrunning.Operation`을 반환하고 `option (google.longrunning.operation_info) = { response_type: …, metadata_type: … }`를 붙인다. 세부는 `~/.claude/lib/api-aip/aip/151.md`를 Read하고 따른다.

## 작성 후 체크

- [ ] 새로 쓰는 google proto import(`google/api/resource.proto` 등)를 빌드가 찾는다(못 찾으면 그 proto를 추가하는 선행 PR을 먼저 낸다)
- [ ] 리소스에 `google.api.resource` 옵션 + `name` 필드
- [ ] 모든 동작이 표준 메서드이거나, Custom `:verb`에 정당화 한 줄이 붙었다
- [ ] 모든 필드에 `field_behavior` 명시
- [ ] `~/.claude/lib/api-aip/index.md`를 Read하고 적용/보류 정책 절의 커서/offset 혼용 기준으로 List 페이지네이션 방식을 골랐고, 커서면 `page_size`/`page_token`/`next_page_token`
- [ ] 리소스 스키마가 Get/Create/Update/List에서 동일
- [ ] 기존 필드번호·타입·의미가 그대로다. additive-only
- [ ] `buf lint` 경고가 없거나, 남은 경고가 전부 AIP와 부딪히는 규칙(중첩 enum 값의 `ENUM_VALUE_PREFIX` 등)에서 난다
