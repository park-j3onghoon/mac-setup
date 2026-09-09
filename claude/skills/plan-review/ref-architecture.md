# Architecture Review Reference

원칙(의존성 방향·SOLID·KISS/YAGNI·상태 저장·전이 다이어그램)은 `~/.claude/coding-rules.md` §1 Architecture · §2 Module · §3 Class/Object · §9 Simple Design에 있다. 아래는 계획 리뷰에서 반복해 걸린 지점.

## 의존성 방향

- 순환 의존 → critical 이슈
- 레이어 역방향 참조 (domain이 infrastructure 임포트)
- 패키지/모듈 간 숨은 결합 (공유 상태, 글로벌 변수)

## 컴포넌트 경계

- 새 서비스/모듈의 책임이 하나인지 (SRP)
- 기존 모듈에 추가하는 쪽이 더 적절한지
- 단일 장애점 존재 여부
- bounded context 경계가 비즈니스 도메인과 일치하는지

## API 계약 설계

- REST: 리소스 중심 URL, HTTP 메서드 의미 일치
- 버전관리: URL prefix(/v1/) 또는 헤더
- 하위호환: 필드 추가 OK, 삭제/타입변경은 deprecation 기간을 둔다
- 에러 응답 포맷 일관성 (status code + error body)
- 페이지네이션: cursor vs offset 선택 근거

## DDIA 원칙

- 데이터 모델 선택 적절성 (관계형 vs 문서 vs 그래프)
- 일관성 모델의 의도적 선택 (strong vs eventual)
- 읽기/쓰기 비율에 따른 설계 (read-heavy → 캐시/복제, write-heavy → 파티셔닝)

## FE 레이어 의존성

- **`routes.ts`/`lib/api/*` 같은 leaf 모듈은 UI 컴포넌트를 import하지 않는다** — UI 타입이 필요하면 도메인 타입 파일(`lib/api/{domain}/types/`)로 올려 양쪽이 그 타입을 import한다. "선례가 있으니 따른다"는 패턴 답습은 기술부채 확산.
- **"action 없는 interactable UI"는 UX 버그** — 스위치/버튼이 활성으로 보이는데 onChange가 noop이면 사용자 오조작을 유발한다. 전부 `disabled` + tooltip으로 두거나 컴포넌트 자체를 제거한다. "TODO 주석"은 사용자에게 전달되지 않는다.
- **UI 설계를 확정하기 전에 BE 필드 존재를 검증한다** — 응답에 있다고 가정한 필드가 없거나 다른 의미이면 전체 UI 재작업. plan 단계에 샘플 응답 확인 또는 타입 검증 단계를 명시한다.

## FE money-path async trigger (202 잡 트리거)

FE가 돈을 움직이거나 발송하는 **비동기 서버 잡(202 Accepted)**을 트리거하면, plan이 아래를 닫지 않을 때 provisional 단계에선 예뻐 보이고 staging 후 한꺼번에 깨진다:

- **Idempotency**: 트리거에 idempotency key(또는 서버가 "동일 (scope,date,action) 활성 run 반환") → 중복 발행 차단. "버튼 disabled"는 탭 1개만 막는다(새로고침/뒤로/두 운영자/retry/202 후 응답 유실엔 무력).
- **재진입 복원**: 진입·새로고침 시 서버 run 상태 조회로 현재 진행을 복원(로컬 상태만 믿지 않기).
- **상태 머신 표시**: `{total,completed}`만으로 부족 — PENDING/IN_PROGRESS/SUCCESS/**FAILED/PARTIAL/SKIPPED**, "메일 실패-발행 성공" 같은 분기를 UI에 노출. 202 생명주기 필드(runStatus/startedAt/finishedAt/refreshError).
- **Blast-radius 모달**: 확인 모달에 대상 범위(scope/건수/금액/이미 처리된 항목)를 노출. 확인 모달은 마지막 방어선이 아니다.
- **진행 필드는 소스가 채운 값만 중계한다**: BFF/relay가 하위 시스템의 `{total,completed}`를 노출할 때, 하위가 `total`을 **세팅하지 않는 경로**(예: 잡 종류별로 total 산정 시점이 다름)면 `0`이 아니라 **`null`(미정)**로 노출한다. `0`은 FE에서 "할 일 없음/완료" 또는 0-나눗셈으로 오독된다. relay는 하위 카운트를 재계산(도메인 규칙 복제)하지 말고 미정은 미정으로 정직하게 전달.
- **create-코호트 = consume-코호트 일치**: 트리거(BFF)가 레코드를 만들고 별도 배치/워커가 그걸 enumerate해 처리하면 **양쪽 코호트 산정 술어가 정확히 같아야** 한다. BFF가 배치가 보지 않을 레코드를 만들면 orphan(미처리→reap/FAILED, 머니패스면 누락 발송). 같은 술어를 두 곳에 복제하지 말고(단일 출처) 최소한 "BFF 코호트 쿼리 인자 == 배치 술어"를 테스트로 고정.
- **Contract drift는 path 한 줄이 아니다**: request/response/status/error/permission/idempotency를 각각 확정·미확정으로 추적하고, 미확정은 type+transform+fixture **한 곳**에 격리. mock test는 FE 기대만 고정(BE가 발산해도 초록) → fixture를 proto/OpenAPI 샘플에서 생성하거나 staging contract smoke를 merge blocker로.
- **미검증 BE 위 live 화면은 feature flag 뒤 새 컴포넌트로 만든다**: API mismatch(404/403/500)는 graceful 에러 상태로 받아 화면 자체가 깨지지 않게 하고, 구 컴포넌트를 보존해 롤백이 git revert에 의존하지 않게 한다.
- **"생략/빈 컬렉션 = 전체 스코프" 직렬화는 UI 경로 제거 시 repo 계층에서 non-empty 강제로 반전한다**: UI가 "전체 실행" 경로를 없앴다면 클라이언트 repo도 빈 배열→키 생략(전체 확대) 직렬화를 throw로 바꾼다(illegal state 표현 불가). 가드를 view 한 곳에만 두면 후속 리팩터·직접 호출·테스트 헬퍼가 우회한다.
- **UI 게이트가 참조하는 파생 카운트에는 stale 창이 있다(디바운스·비동기 재조회)**: 실행 직전 권위 소스(summary 등) 값으로 대상 0건이면 confirm 자체를 중단. 가드용 캐시 값(그룹 총원 등)은 컨텍스트 전환 시 즉시 unknown(null)으로 리셋 — 이전 컨텍스트의 0(허용값) 재사용이 fail-open 창이 된다. unknown은 fail-closed.
