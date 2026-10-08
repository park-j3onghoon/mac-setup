## URL과 메서드

- URL에는 명사만 둔다. 컬렉션은 복수형(`/books`), 리소스는 컬렉션 + ID(`/books/{book_id}`), 부모가 있으면 중첩한다(`/publishers/{publisher_id}/books/{book_id}`).
- 동작은 HTTP 메서드로 표현하고, 표준 메서드로 안 되는 동작만 커스텀 메서드 `POST /{리소스}:{동사}`(`/books/{book_id}:archive`)로 만든다.
- List는 `GET /{컬렉션}`, 본문 없음, 응답 `{ items, next_page_token, total_size }`(`total_size`는 선택).
- Get은 `GET /{컬렉션}/{id}`, 본문 없음, 응답은 리소스.
- Create는 `POST /{컬렉션}`, 본문은 리소스, 응답은 만든 리소스.
- Update는 `PATCH /{컬렉션}/{id}`, 본문은 바꿀 필드만 담은 리소스, 응답은 갱신된 리소스.
- Delete는 `DELETE /{컬렉션}/{id}`, 본문 없음, 응답은 204(soft delete면 리소스).
- 리소스 스키마는 Get 응답·Create 본문·Update 응답·List 항목에서 같다.
- OpenAPI `operationId`는 표준 동사 + 리소스로 짓는다: `listBooks`·`getBook`·`createBook`·`updateBook`·`deleteBook`, 커스텀 메서드는 `archiveBook`.
- 시간·이름 같은 표준 필드는 `~/.claude/lib/api-aip/aip/148.md`를 Read하고 따른다(`create_time`·`update_time`·`display_name`).

## 페이지네이션

`~/.claude/lib/api-aip/index.md` 적용/보류 정책 절의 커서/offset 혼용 항목으로 방식을 고른다.

- 커서: 요청 `page_size`(기본 50, 최대 1000)·`page_token`(직전 응답의 `next_page_token`을 그대로)·`order_by`(`"create_time desc"`), 응답 `{ items, next_page_token, total_size }`. 세부는 `~/.claude/lib/api-aip/aip/158.md`를 Read하고 따른다.
- offset: 요청 `page`(1부터)·`page_size`, 응답 `{ items, total_size }`.
- 필터는 `filter` 하나로 받는다. 문법은 `~/.claude/lib/api-aip/aip/160.md`를 Read하고 따른다.

## 에러

- 형식은 `{ "error": { "code", "message", "status", "details" } }`이다. `code`는 HTTP 상태 코드, `status`는 canonical 코드 이름(`NOT_FOUND`·`INVALID_ARGUMENT`·`PERMISSION_DENIED`·`ALREADY_EXISTS`·`FAILED_PRECONDITION`·`RESOURCE_EXHAUSTED`), `details[].reason`은 63자 이하 `UPPER_SNAKE_CASE`, `domain`은 서비스 식별자다.
- 코드마다 쓰는 경우와 HTTP 상태는 `~/.claude/lib/api-aip/aip/193.md`를 Read하고 따른다.

## 작성 후 체크

- [ ] URL이 복수형 컬렉션 + ID이고, 동작은 HTTP 메서드나 `:verb`로 표현됐다
- [ ] List 페이지네이션 방식이 페이지네이션 절의 기준에 맞고, 고른 방식의 파라미터와 응답이 짝을 이룬다
- [ ] 에러 응답이 에러 절의 형식 하나다
- [ ] 리소스 스키마가 Get/Create/Update/List에서 같다
