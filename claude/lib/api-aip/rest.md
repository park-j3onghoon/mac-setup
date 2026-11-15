## 형태

- URL에는 명사만 둔다. 컬렉션은 복수형(`/books`), 리소스는 컬렉션 + ID(`/books/{book_id}`), 부모가 있으면 중첩한다(`/publishers/{publisher_id}/books/{book_id}`).
- List는 `GET /{컬렉션}`, 본문 없음, 응답은 페이지네이션 절의 방식대로.
- Get은 `GET /{컬렉션}/{id}`, 본문 없음, 응답은 리소스.
- Create는 `POST /{컬렉션}`, 본문은 리소스, 응답은 만든 리소스.
- Update는 `PATCH /{컬렉션}/{id}`, 본문은 바꿀 필드만 담은 리소스, 응답은 갱신된 리소스.
- Delete는 `DELETE /{컬렉션}/{id}`, 본문 없음, 응답은 204(soft delete면 리소스).
- OpenAPI `operationId`는 표준 동사 + 리소스로 짓는다: `listBooks`·`getBook`·`createBook`·`updateBook`·`deleteBook`, 커스텀 메서드는 `archiveBook`.
- 에러 형식은 `{ "error": { "code", "message", "status", "details" } }`이다. `code`는 HTTP 상태 코드, `status`는 canonical 코드 이름(`NOT_FOUND`·`INVALID_ARGUMENT`·`PERMISSION_DENIED`·`ALREADY_EXISTS`·`FAILED_PRECONDITION`·`RESOURCE_EXHAUSTED`), `details[].reason`은 63자 이하 `UPPER_SNAKE_CASE`, `domain`은 서비스 식별자다.

## 페이지네이션

`~/.claude/lib/api-aip/index.md` 적용/보류 정책 절의 커서/offset 혼용 항목으로 방식을 고른다.

- 커서: 요청 `page_size`·`page_token`(직전 응답의 `next_page_token`을 그대로)·`order_by`(`"create_time desc"`), 응답 `{ items, next_page_token, total_size }`.
- offset: 요청 `page`(1부터)·`page_size`, 응답 `{ items, total_size }`.
- 필터는 `filter` 하나로 받는다.

## 작성 후 체크

- [ ] URL이 복수형 컬렉션 + ID이고, 동작은 HTTP 메서드나 `:verb`로 표현됐다
- [ ] List 페이지네이션 방식이 페이지네이션 절의 기준에 맞고, 고른 방식의 파라미터와 응답이 짝을 이룬다
- [ ] 에러 응답이 형태 절의 에러 형식 하나다
- [ ] 리소스 스키마가 Get/Create/Update/List에서 같다
