## 트랙과 현행 컨벤션 확정

트랙을 고른다. proto 트랙 대상은 프로젝트의 `.proto` 파일, REST 트랙 대상은 OpenAPI 스펙 YAML이다.
그다음 손댈 모듈의 형제 스펙을 Grep해 네 가지를 확정한다: 응답 엔벨로프 · 페이지네이션 방식 · 에러 shape · 필드 케이스(snake/camel, 공통 컴포넌트 `$ref`).
→ 완료: 네 항목 모두 "이 모듈은 X를 쓴다"로 적혔다.

## 신규 API

1. 리소스 확정: 리소스 명사 · 컬렉션 복수형 이름 · `parent` 유무. → 완료: 세 값이 정해졌다.
2. 표준 메서드 매핑: `Get` `List` `Create` `Update` `Delete`로 먼저 표현하고, 남는 동작만 `POST /{name}:verb` Custom(`~/.claude/lib/api-aip/aip/136.md`)으로 만든다. → 완료: 모든 동작이 표준 메서드이거나, 왜 표준으로 안 되는지 정당화 한 줄이 붙은 Custom이다.
3. 트랙 파일 적용: proto면 `~/.claude/lib/api-aip/proto.md`, REST면 `~/.claude/lib/api-aip/rest.md`를 Read하고 그 파일의 작성 후 체크 절을 통과시킨다. → 완료: 체크 항목 전부 [x].

## 기존 API 수정

1. 깨는 변경 게이트: 이번 변경이 적용/보류 정책 절의 additive-only인지 판정한다. additive면 진행한다. 아니면 병행 추가 → 클라 이행 → deprecation 순서의 이행이나 `v2`를 별도 과제로 분리하고, 이번 PR엔 깨는 변경 없이 적용 가능한 항목만 남긴다. → 완료: 이번 PR 변경 목록이 전부 additive다.
2. 엔드포인트 하나만: 트랙과 현행 컨벤션 확정 절에서 고른 트랙 파일(`~/.claude/lib/api-aip/proto.md` 또는 `~/.claude/lib/api-aip/rest.md`)을 Read하고, 손대는 그 엔드포인트를 그 파일의 작성 후 체크 절로 훑는다. → 완료: AIP 격차 목록과 항목별 적용/보류 판정이 나왔다.

## 마무리

PR 설명에 "이번에 적용한 AIP 항목 / 보류한 항목과 이유" 한 줄을 남긴다. REST 트랙은 `~/.claude/lib/coding/api.md`를 Read하고 OpenAPI spec with every endpoint change 항목대로 OpenAPI YAML을 같은 PR에서 갱신한다. → 완료: 그 한 줄이 PR 설명에 있고, REST 트랙이면 그 항목대로 OpenAPI YAML이 갱신됐다.

## 적용/보류 정책

- 엔벨로프 유지: 모듈이 응답을 공통 성공 래퍼(`{code, msg}` 같은 엔벨로프)로 감싸고 있으면 그대로 쓰고 안쪽 페이로드만 AIP대로 만든다. 모든 메서드에서 리소스 스키마 동일(Get 반환 = Create 입력 = List 항목), List는 `items`+`next_page_token`+`total_size`. 제거는 팀 합의 후 일괄 전환한다.
- 커서/offset 혼용: 판단 기준은 AIP 준수가 아니라 데이터 규모 + 임의 페이지 점프 필요성이다. 수천~수만 건·안정적·페이지 번호 점프·"전체 N건" UI인 어드민·검색은 offset을 유지하고, 수십만 행 이상이거나 삽입·삭제가 잦은 피드·로그와 무한스크롤·더보기 UI는 커서를 쓴다. 보류 대상은 offset→커서 전환이다.
- 커서 계약: `page_size`(기본 50, 1000 초과는 상한으로 coerce) + opaque URL-safe `page_token` → `next_page_token`이 비면 마지막 페이지, `total_size`는 optional. `page_size` 외 파라미터를 페이지 중간에 바꾸면 `INVALID_ARGUMENT`(400).
- 에러 shape 게이트: 프레임워크가 자동 생성하는 에러(401/403)를 바꿀 수 있는지 확인 → 못 바꾸면 형제 컨벤션을 Grep → 그 컨벤션으로 통일하고 AIP 에러 shape는 보류한다.
- 권한 > 존재: 권한을 존재 여부보다 먼저 확인한다. 권한이 없으면 리소스가 있든 없든 403 `PERMISSION_DENIED`, 권한이 있고 리소스가 없을 때만 404 `NOT_FOUND`다.
- additive-only(`~/.claude/lib/api-aip/aip/180.md`): 배포된 API에 더할 수 있는 건 새 optional 필드·새 엔드포인트·새 정렬 옵션이다. 필드 제거·이름/타입/의미 변경, URL·HTTP 메서드 변경(기존 URL은 그대로 두고 신규 경로에만 적용), proto 필드번호·타입·의미 변경은 깨는 변경이다.
- 적용 우선순위:
  1. AIP 에러 shape(에러 shape 게이트를 통과할 때)
  2. 리소스 네이밍·URL·표준 메서드(신규부터)
  3. field behavior·하위호환(전체 습관화)
  4. 커서 페이지네이션(신규 List + FE 합의되는 곳)
  5. 엔벨로프 제거(팀 합의 후 일괄)

## AIP 세부

설계가 아래 항목에 걸리면 그 파일을 Read하고 따른다. 파일 안의 반드시는 must, 권장은 should, 해도 된다는 may다.

- 리소스 계층·스키마: `~/.claude/lib/api-aip/aip/121.md`
- 리소스 이름·ID·참조 필드: `~/.claude/lib/api-aip/aip/122.md`
- HTTP 경로·본문 매핑: `~/.claude/lib/api-aip/aip/127.md`
- declarative-friendly 인터페이스: `~/.claude/lib/api-aip/aip/128.md`
- Get: `~/.claude/lib/api-aip/aip/131.md`
- List: `~/.claude/lib/api-aip/aip/132.md`
- Create: `~/.claude/lib/api-aip/aip/133.md`
- Update: `~/.claude/lib/api-aip/aip/134.md`
- Delete: `~/.claude/lib/api-aip/aip/135.md`
- 커스텀 메서드: `~/.claude/lib/api-aip/aip/136.md`
- 필드 이름: `~/.claude/lib/api-aip/aip/140.md`
- 표준 필드: `~/.claude/lib/api-aip/aip/148.md`
- 장기 실행 작업(LRO): `~/.claude/lib/api-aip/aip/151.md`
- etag: `~/.claude/lib/api-aip/aip/154.md`
- singleton 리소스: `~/.claude/lib/api-aip/aip/156.md`
- 부분 응답(필드 마스크·view): `~/.claude/lib/api-aip/aip/157.md`
- 페이지네이션: `~/.claude/lib/api-aip/aip/158.md`
- 필터링: `~/.claude/lib/api-aip/aip/160.md`
- 리소스 revision 이력: `~/.claude/lib/api-aip/aip/162.md`
- soft delete·복구·영구 삭제: `~/.claude/lib/api-aip/aip/164.md`
- 하위 호환성: `~/.claude/lib/api-aip/aip/180.md`
- 오류: `~/.claude/lib/api-aip/aip/193.md`
- 클라이언트 자동 재시도: `~/.claude/lib/api-aip/aip/194.md`
- 필드 형식(`field_info`): `~/.claude/lib/api-aip/aip/202.md`
- field_behavior: `~/.claude/lib/api-aip/aip/203.md`
- 유니코드 길이·정규화: `~/.claude/lib/api-aip/aip/210.md`
- 리소스 만료 시각·TTL: `~/.claude/lib/api-aip/aip/214.md`
- 상태 enum: `~/.claude/lib/api-aip/aip/216.md`

목록에 없는 AIP가 필요하면 원문을 조사해 같은 꼴의 파일을 `~/.claude/lib/api-aip/aip/{번호}.md`로 더하고, 이 목록에 한 줄을 더한 뒤 따른다.
