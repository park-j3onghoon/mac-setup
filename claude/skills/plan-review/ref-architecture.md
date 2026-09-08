# Architecture Review Reference

## Core Principles

- **단방향 의존성** — A→B이면 B→A 금지. 순환이 되면 분리한 의미가 없다. domain ← application ← infrastructure.
- **SOLID** — SRP(변경 이유 1개), OCP(확장 열림, 수정 닫힘), DIP(구체가 아닌 추상에 의존). LSP/ISP는 위반 시에만 지적.
- **KISS / YAGNI** — 예측이 아닌 현재 요구사항에 집중. 한 번만 쓰는 코드에 과도한 추상화 금지.
- **상태는 resolve가 아니라 저장** — 이벤트 기반 동작은 다른 필드에서 계산 불가. 상태 전이 다이어그램과 종결 조건을 초기에 확정.

## Checklist

### 의존성 방향
- 순환 의존 → critical 이슈
- 레이어 역방향 참조 (domain이 infrastructure 임포트)
- 패키지/모듈 간 숨겨진 결합 (공유 상태, 글로벌 변수)

### 컴포넌트 경계
- 새 서비스/모듈의 책임이 명확한지 (SRP)
- 기존 모듈에 추가하는 게 더 적절한지
- 단일 장애점 존재 여부
- bounded context 경계가 비즈니스 도메인과 일치하는지

### API 계약 설계
- REST: 리소스 중심 URL, HTTP 메서드 의미 일치
- 버전관리: URL prefix(/v1/) 또는 헤더
- 하위호환: 필드 추가 OK, 삭제/타입변경 시 deprecation 기간
- 에러 응답 포맷 일관성 (status code + error body)
- 페이지네이션: cursor vs offset 선택 근거

### DDIA 원칙
- 데이터 모델 선택 적절성 (관계형 vs 문서 vs 그래프)
- 일관성 모델의 의도적 선택 (strong vs eventual)
- 읽기/쓰기 비율에 따른 설계 (read-heavy → 캐시/복제, write-heavy → 파티셔닝)

### FE 레이어 의존성
- **`routes.ts`/`lib/api/*` 같은 leaf 모듈이 UI 컴포넌트 파일을 import하면 역방향 의존**. UI 타입이 필요하면 도메인 타입 파일(`lib/api/{domain}/types/`)로 올려서 양쪽이 그 타입을 import하게 한다. "선례가 있으니 따른다"는 패턴 답습은 기술부채 확산.
- **"action 없는 interactable UI"는 UX 버그**. 스위치/버튼이 활성 상태로 보이는데 onChange가 noop이면 사용자 오조작을 유발. 해결: 전부 `disabled` + tooltip, 또는 컴포넌트 자체 제거. "TODO 주석"은 사용자에게 전달되지 않는다.
- **BE 필드 존재 미검증 상태로 UI 설계 확정 금지**. 응답에 있다고 가정한 필드가 실제로는 없거나 다른 의미이면 전체 UI 재작업. plan 단계에서 샘플 응답 확인 또는 타입 검증 단계를 명시.

### FE money-path async trigger (202 잡 트리거)
FE가 돈을 움직이거나 발송하는 **비동기 서버 잡(202 Accepted)**을 트리거하면, plan이 아래를 닫지 않으면 provisional 단계에선 예뻐 보이고 staging 후 한꺼번에 깨진다:
- **Idempotency**: 트리거에 idempotency key(또는 서버가 "동일 (scope,date,action) 활성 run 반환") → 중복 발행 차단. "버튼 disabled"는 탭 1개만 막는다(새로고침/뒤로/두 운영자/retry/202 후 응답 유실엔 무력).
- **재진입 복원**: 진입·새로고침 시 서버 run 상태 조회로 현재 진행을 복원(로컬 상태만 믿지 않기).
- **상태 머신 표시**: `{total,completed}`만으로 부족 — PENDING/IN_PROGRESS/SUCCESS/**FAILED/PARTIAL/SKIPPED**, "메일 실패-발행 성공" 같은 분기를 UI에 노출. 202 생명주기 필드(runStatus/startedAt/finishedAt/refreshError).
- **Blast-radius 모달**: 확인 모달에 대상 범위(scope/건수/금액/이미 처리된 항목)를 노출. 확인 모달은 마지막 방어선이 아니다.
- **소스가 채우지 않는 진행 필드를 중계하지 말 것**: BFF/relay 가 하위 시스템의 `{total,completed}` 를 그대로 노출할 때, 하위가 `total` 을 **세팅하지 않는 경로**(예: 비동기 잡 종류별로 total 산정 시점이 다름)면 `0` 이 아니라 **`null`(미정)** 로 노출한다. `0` 은 FE 에서 "할 일 없음/완료" 또는 0-나눗셈으로 오독된다. relay 는 하위 카운트를 재계산(도메인 규칙 복제)하지 말고, 미정은 미정으로 정직하게 전달.
- **create-코호트 = consume-코호트 일치**: 트리거(BFF)가 레코드를 만들고 별도 배치/워커가 그걸 enumerate 해 처리하면, **양쪽 코호트 산정 술어가 정확히 같아야** 한다. BFF 가 배치가 보지 않을 레코드를 만들면 orphan(미처리→reap/FAILED, 머니패스면 누락 발송). 같은 술어를 두 곳에 복제하지 말고(단일 출처) 최소한 "BFF 코호트 쿼리 인자 == 배치 술어" 를 테스트로 고정.
- **Contract drift는 path 한 줄이 아니다**: request/response/status/error/permission/idempotency를 각각 확정·미확정으로 추적, 미확정은 type+transform+fixture **한 곳**에 격리. mock test는 FE 기대만 고정(BE 발산해도 초록) → fixture를 proto/OpenAPI 샘플에서 생성하거나 staging contract smoke를 merge blocker로.
- **미검증 BE 위 live 화면 in-place 재작성 금지**: feature flag로 게이트, API mismatch(404/403/500)는 graceful 에러 상태로(화면 자체가 깨지지 않게), 구 컴포넌트 보존으로 롤백을 git revert에 의존하지 않기.

## Examples

```python
# 잘된 예시: 레이어 의존성이 올바른 구조
# domain/ — 외부 의존 없음
class Campaign:
    def can_activate(self) -> bool: ...

# application/ — domain만 참조
class ActivateCampaignUseCase:
    def __init__(self, repo: CampaignRepository): ...  # DIP: 추상에 의존

# infrastructure/ — application, domain 참조
class DjangoCampaignRepository(CampaignRepository): ...
```

## User Preferences
- 최소 diff, boring by default, incremental > revolutionary
- 상태 설계가 구현보다 선행
- essential vs accidental complexity 구분

### FE money-path 추가 체크 (ISSUE-000 UI polish Codex 검증에서)
- **"생략/빈 컬렉션 = 전체 스코프" 직렬화는 UI 경로 제거 시 repo 계층에서 non-empty 강제로 반전**: UI가 "전체 실행" 경로를 없앴다면 클라이언트 repo도 빈 배열→키 생략(전체 확대) 직렬화를 throw 로 바꾼다(illegal state 표현 불가). 가드를 view 한 곳에 두면 후속 리팩터·직접 호출·테스트 헬퍼가 우회한다.
- **UI 게이트가 참조하는 파생 카운트에는 stale 창이 있다(디바운스·비동기 재조회)**: 실행 직전 권위 소스(summary 등) 값으로 대상 0건이면 confirm 자체를 중단. 가드용 캐시 값(그룹 총원 등)은 컨텍스트 전환 시 즉시 unknown(null) 리셋 — 이전 컨텍스트의 0(허용값) 재사용이 fail-open 창이 된다. unknown 은 fail-closed.
