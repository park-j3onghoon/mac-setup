# 리뷰 관점

diff를 아래 카테고리의 관점으로 검증한다.

## 패턴 카테고리

### 권한·인증·보안
- 새 엔드포인트 인증/인가 누락
- 권한 escalation (외부 클라이언트 ID 주입으로 우회)
- 인증 미들웨어 적용 범위 (어드민 API 에만, multipart 우회 가능성)
- 권한 최소화: `pull-requests: write`, 넓은 GITHUB_TOKEN 권한
- 공유 캐시/락 의도 (다수 사용자 같은 계정), 세션 캐시 활용
- 외부 파트너 정책 사전 확인
- SQL injection: `f"...{user_input}..."`, `strings.ReplaceAll` 보간 → strptime/regex/포맷 검증
- GitHub Actions 보안: PAT → GitHub App token, SHA pin, vault
- 외부 시스템 contract 일관성 (외부 시스템에 남기는 레코드의 접두어 같은 약속)

### silent 동작 / 기본값 함정
- try/except 후 None 반환은 지적 (exception 발생하게 두는 게 자연스러운 경우)
- Sentry 폭증 방지: error message 변동값은 `extra` 분리
- 무용한 방어코드 제거: 순수 함수 try/except → silent 위험
- silent default 버그: 클라이언트 필드 누락 → 1 로 초기화
- silent drop: 컬럼 deprecate 시 기존 적재 데이터 조회 경로 보정 누락 (`total += old_a + old_b`처럼 옛 컬럼 값을 합치는 경로)
- silent fallback/early_success: 데이터 누락과 mismatch 를 모두 False 로 묶음 → 일시 누락 시 전환 차단. matched/mismatched/skipped enum 또는 (bool, reason)
- Liveness 신뢰: liveness probe 로 자연 복구되는 경우 handling 추가 대신 exception
- 빈 selector / 빈 문자열 / 0 falsy 엣지: `a && b`가 0을 거짓으로 거름, `[""]`, 빈 문자열 enum 값의 validation 통과, 최솟값과 최댓값이 같을 때 같은 쿼리 중복

### 트랜잭션·동시성·원자성
- 트랜잭션 범위: `with uow` 조회만 하는 구간이면 제거
- 동시성/멱등성: non-idempotent 이중 실행, timeout 파라미터화
- dual-write: secondary 는 primary 성공 시에만? best-effort? 명시
- `transaction.on_commit` 안 RPC 실패 시 응답 200 → 운영자 인지 불가. orphan 리소스 → 보상 삭제/outbox
- Promise.all upsert 동시 실행 시 일부 누락
- SELECT-then-DELETE race condition
- 비결정성: `next(iter(...))`, `items[0]`, `ORDER BY event_time` 단독 → ROW_NUMBER + 보조 키
- Go 1.21 이하 루프 변수 함정: `&p` 슬라이스 원소 포인터 캡처 → 마지막 원소만 가리킴. Goroutine 안 캡처도 동일

### 정산·금액·시간
- 정산/금액: 소수점·반올림·통화. 환율 변경 시 재계산 호출 순서/필요성
- DB 컬럼 타입 한계: `PositiveSmallIntegerField` (max 65535) 에 외부 ID 직접 저장
- 타임존 명시성: `date.today()` / `datetime.now().date()` 암묵 UTC → `timezone.localdate()` 또는 `ZoneInfo('Asia/Seoul')`. KST 자정~9시 1일 어긋남. Go: `time.Now().UTC()`, 반환값 TZ 함수명 반영
- KST 시간 창 같은 도메인 규칙이 인라인 복제되면 entity classmethod 캡슐화

### 명명·명시성
- 함수명 = 비즈니스 역할 + 동작 직접 드러나는 이름: 구현 세부 (async/thread) 를 드러낸 이름은 지적. `AsyncOrderUpdateThread` → `OrderUpdater`
- 컨텍스트 드러나는 이름: "end date" → "가장 나중의 end date"
- boolean 네이밍 (`isRemovable`), 모호한 값 (0/1, win-lose) → 의미 명확하게
- 도메인 용어 충돌: `Segment` 가 유저 세그먼트로 이미 사용, `experimentGroup` 도메인 prefix
- 매직 값/넘버 → 상수/enum: `-99` 같은 sentinel 어색, `20`/`5`/`60000` 같은 매직 넘버 상수화
- 이름 변경 최소화: 의미 변경 없으면 기존 이름 유지
- 인프라 비독립 네이밍: repository `Set` (redis 의식) → `MarkProcessed` (저장소 무관)
- opinionated user-facing 메시지 경계
- 에러 메시지 정보성: "failed to ..." 만으로 부족

### 추상화·레이어·구조
- 과도한 추상화는 지적: 한 곳에서만 쓰는 클래스 인라인, factory 패턴 인터페이스 안 되면 코드 분리
- 외부 라이브러리 설정을 직접 옮기는 대신 "지금은 너무 많은 추상화 피하고 그대로 두자"
- facade 분리, 구조체 vs string 분리는 필요한지 묻는다
- 단순함 우선: 복잡하지 않은 코드에 들인 외부 라이브러리·함수화는 지적
- 다형성 필요성 검증: 구현이 하나뿐인 인터페이스 분리는 지적
- 레이어 의존성 방향: domain 의 라이브러리 종속과 application use case 의 ORM 직접 호출은 지적. 레포 `CLAUDE.md`가 정한 onion 구조
- DDD: dynamo 에러는 controller 직접 노출 대신 usecase 에러로 변환
- Django base table 상속은 지적 (pk/migration 누락)
- 레이어 배치: `slack_sdk` 의존만 있으면 `adapters/` 이동. 화면 하나에만 쓰는 로직을 공용 view 파일 같은 잘못된 위치에 작성한 이유

### 기존 코드 재사용 / DRY
- 기존 유틸/인터페이스/함수 재사용: 새 플래그 대신 기존 진입점, 이미 만들어둔 인터페이스/구조, `order.is_draft()` 같은 도메인 메서드
- 2곳 이상 중복 → 모델/유틸/composable 추출. 두 main 파일 동일 코드는 추출한 함수. 도메인 간 동일 코드는 composable
- 사용처 없는 함수/필드 제거: deprecate 없이 바로
- 무관한 변경 분리: 이번 PR 과 무관하면 별도 후속 PR. 컨벤션 충돌도 별도 리팩토링 PR
- 검증 로직 중복: 한쪽에서만
- 다중 반환값 컨벤션: `value, exists := getter()`

### DB·스키마·쿼리
- DynamoDB 함정: Limit+Filter (Limit 가 Filter 전 적용 → 빈 결과), `TransactWriteItems.CancellationReasons`. `result_bytes`/`estimated_page_count` 는 Filter 후 응답 크기 → 비용 과소 추정 → `consumed_capacity`
- N+1: 즉시 식별 + 페이지네이션 안전 가드. 이번 PR 은 N+1 만 분리 원칙
- 일괄 적용 누락: A/B/C 라인 → D 추가 시 A/B/C 업데이트 전파 누락
- 인덱스 적합성: 복합 인덱스를 단일 컬럼 조회로 안 탈 가능성. 카디널리티 낮은 컬럼 선행 비효율. hash/range key 명시·음수 가능성
- DB ORM connection 설정 변경은 지적 (전체 API 영향, 1Q 검증)
- chunk 단위 삭제
- Django `bulk_create(update_conflicts=True)` 는 `Model.save()` 미경유 → `auto_now` 동작 X. 수동 `timezone.now()` + `update_fields` + 테스트
- JSON 스키마: dict 직접 노출 대신 typed schema. Union 은 지적. OG 패턴 일관
- enum/sentinel 명시 (DB 레벨)
- Nullable 정책: 비즈니스 필수면 Non-Nullable
- DB ID 재배정 추적
- 마이그레이션 누락: 새 enum 값, 코드만 변경 vs db 변경 구분
- ES mapping JSON 문법 검증: 닫는 중괄호/쉼표 누락 줄 번호로 정확히

### AI 생성 코드 가드
- `# type: ignore` 추가/타입힌트 약화는 의도 확인
- AI/Claude가 만든 spec/migration/code를 검토 없이 받아들인 것은 지적. follow-up PR 로 정리
- AGENTS.md/CLAUDE.md 협업 문서에서 위험 명령 제거
- AI 생성 PR 본문이 기계적이면 실제 의도 작성 요구
- AI 가 못 잡는 비즈니스 로직은 한글 주석 강화
- stock template (`openspec init --tools claude`) byte-identical 유지 (patch 시 다음 update 회귀)

### 운영·관측성·배포
- 에러 로그 레벨: info → error/warn
- 에러 컨텍스트: 식별자 (사용자·기기·대상 리소스 id) 포함
- 운영 진단성: `KeyError` 대신 대상 id·기간을 담은 `ValueError`
- Stale 주석 제거
- production 로그 노이즈: 항목마다 찍는 debug 로그 머지 전 제거
- 로그 레벨 일관성: Info 에 `[DEBUG]` prefix 가 테스트 전용인지
- 로그 샘플링: 새 위치에 기존 규칙 적용
- 로그 구조화: 분할보다 단일 라인 필드 묶음, correlation_id
- 메트릭 명명 일관성: 같은 대상은 한 이름으로 통일, 카운터 순서 (Daily-Total)
- 메트릭 확장: 새 로직에 custom metric (라벨 카디널리티)
- 메트릭 중복/목적 모호
- 변경 영향 추적: 미사용 코드 제거 PR 에서 추가/제거 PR 모두 코멘트
- 점진 적용/% 분할: 전체 유형 동시 변경 위험 시
- 다중 서비스 배포 누락: 같이 배포해야 하는 서비스
- 배포 환경 태그 확인: 배포 대상 서비스가 맞는지
- 배포 순서 명시 (BE 먼저 → gateway → FE)
- 공유 API 스펙 버전 일치: requirements 변경 시 스펙 저장소 동시 PR, deploy 알림

### DevOps / Infra
- Atlantis plan diff 에 의도하지 않은 리소스 추가 차단
- 태그/네이밍 표준화: `terraform.env` 태그 ops/dev/staging/prod
- 권한 분리 환경별: dev/prod IAM
- Recreate/Drift 사전 경고: terraform plan 에서 recreate 명시
- 데이터 트래픽 기반 판단: HPA 축소 같은 영향 큰 변경
- 재시도/백오프 일관성: 최대 4회, 1s/2s/4s/8s
- 인프라/배포 영향 범위: helm values, virtual service, mesh forwarding. canary 적용 가능성
- 환경 의존 설정: 하드코딩이 env 따라 달라져야 하는지, 미사용 ENV 제거
- 인프라 설정 디테일: ServiceMonitor port, extraServicePorts, helm chart
- 안 쓰는 좀비 step 제거: `snok/install-poetry` 등
- 린트/CI 자동화 비용 (`go run` 매 커밋 컴파일, CODEOWNERS 매핑)

### 테스트
- 회귀 가드: 빈 source padding, monthly aggregate 합산 누락
- 테스트 의도-검증 일치: docstring 약속을 실제 assertion 수행하는지. `assert_called_once()` 만 끝나면 계산 결과 누락
- mock 충실성: `side_effect` vs `return_value` 불일치, monthly 분기 합산 누락
- side effect 외부 주입: TimeProvider 주입 (영업일/공휴일 flaky 제거)
- 표준 라이브러리: `AsyncMock`, `aioresponses`
- 테스트 가독성: 인덱스 직접 접근 대신 id 필드 명시. parametrize 보다 분리
- Given/When/Then 일관성. lazy import 는 지적. `faker.unique` 누적 상태
- 테스트 컨벤션 일관성 vs 강요: per-function vs table-driven 일관되면 그대로 둔다
- 테스트 커버리지 + API 스펙 일관성
- Top-K/임계값 의도: 평가 대상이 top_k 이상인 것만인지

### Frontend (Vue/React)
- Composition API + script setup, `import { nextTick } from "vue"` 직접 import
- 컴포넌트 책임 분리: open 핸들러에 든 비즈니스 로직은 지적
- 컴포넌트 분리 vs 인라인 균형: 단순 wrapper 는 인라인, 길어진 렌더링은 분리
- form 상태 동기화: form 내부 값으로, 별도 useState 시 동기화 깨질 우려
- form Hook Options 일관성: `defaultValues + onSubmit` 패턴, useAppForm 즉시 return
- 타입 안전성 (literal union/type predicate): `as` 캐스팅 대신 `.filter((v): v is string => Boolean(v))`. 리터럴 유니온/enum
- 느슨한 비교는 지적: 형변환 위험. 일관된 null/undefined 체크 유틸
- API/도메인 enum: string union 대신 enum, PascalCase + `-Enum`
- BE/FE 미사용 필드 제거. camelCase/snake_case 일관성
- 공통 컴포넌트/유틸 재사용 (이미 있는 포맷 함수·아이콘·헤더·스키마 함수)
- 웹 스토리지 SafeStorage 패턴
- 내비게이션 가드: 취소 + showConfirm (화면 간 일관)
- 데이터 모킹 위치: 전부 mocks.ts
- subscribe vs useStore: `form.Subscribe` 로 불필요 리렌더링 방지
- Watch 가독성: named method 추출
- Vue 관용: `?? `, `Record<>`, composable 추출 (`useDocumentTitle`)
- URL state vs local state 일관성: 다른 필터가 URL 이면 동일하게
- Radix 내부 selector 의존 경계: `portalRef.closest("[data-radix-portal]")` 라이브러리 업데이트 시 깨질 수 있음
- 불필요한 onError 패스스루: `options?.onError?.(...args)` 만 호출 → `...options` spread
- viewport overflow / responsive: rem 변환 + px 단위 검증 (320px viewport overflow 등)
- Figma 디자인 일치 검증: 사이드바 아이콘/메뉴 순서/hover 애니메이션. 디자인에 없는 동작 (사이드바 숨김 등) 제거
- 타입명 간결화: `OrderRequestDetail` → `OrderDetail`, `ordId` → `orderId`

### Go 패턴
- 에러 래핑: `fmt.Errorf("...: %w", err)`. Uber Go style. `failed to` prefix 는 지적. sentinel + 컨텍스트: `fmt.Errorf("%w: flagID is empty", ErrInvalidConfig)`
- nil/panic 가드: 타입 단언, 인덱스 경계, `MustGet` panic 가능성
- panic 대신 error 리턴: 비즈니스 로직 panic 던지면 프로세스 그대로 뻗어버림
- ctx 전파: `context.Background()` 새로 만들기보다 상위 ctx
- 구체 타입 vs `interface{}`: 동적 타입 노출은 지적, 제네릭
- Private 가시성: 패키지 내부 사용은 private
- HTTP status code 추론: `ErrEmailVerificationNotFound` → 404
- early return / 깊은 중첩 줄이기
- 불필요 루프 invariant 제거: 루프 밖으로
- Go for-range 복사 비용: 큰 struct → `for i := range slice` + `&slice[i]` 인덱스 (validate hot path)
- 불필요 슬라이스 캐스팅: `[]string{}` vs nil slice + append
- 함수 visibility: private 이 외부 3곳+ 호출되면 public 승격
- 불필요 임베딩: 작업자 외 이해 어려운 구조
- proto/toolchain 버전 다운그레이드 사이드이펙트, 직렬화 번호 점프 이유

### Python 패턴
- Python typing: `Optional[]` 누락, `ClassVar` 명시, abstract method 시그니처
- asyncio 정석: 수동 event loop 대신 `asyncio.run`/`asyncio.gather`. aiohttp connector 공유
- Redis cluster: slot 제약, TTL. pattern 후 추가 필터링 중복, pipeline 중복 제거
- 인스턴스 변수에 쓴 `TOKEN_MANAGER` 같은 UPPER_SNAKE 는 지적
- private 속성 접근: 외부에서 꺼내 쓰는 패턴 → public 접근자/생성자 주입
- dependency 분류: 테스트 전용은 `dev.in`
- 하드코딩 만료/정리 계획 주석 (id allowlist 같은 일회성 데이터)
- 하드코딩 vs 설정: 비즈니스 값을 환경변수로

### 데이터·ML·쿼리
- 피처 일관성 (Python ↔ SQL): MULTIMAP_AGG/REDUCE 같은 비용 큰 시퀀스 피처 잔존
- 비용 절감: Athena/Trino 파티션 프루닝
- 모델 식별자: None/"None" 혼용 → enum
- 임베딩/캐시 키 적용 범위: 부분 적용 시 전체 입력 시작 부분 일괄
- 하드코딩 결정 근거 기록

### 코드 위생·잔여물
- 코드 주석 처리 대신 삭제
- console.log, 미사용 주석/코드
- gitignore 누락 (`.playwright-mcp` 등 도구 산출물)
- 미사용 import / 변수 / props
- 불필요한 `.filter(Boolean)` / dead code
- master 에 이미 추가된 권한 코드라면 PR 에서 제거
- 불필요 어노테이션 정리 (chart configmap spinnaker 잔재)

### 성능
- 성능 임계점 사전 경고: in-memory sort 5천건, 24시간 redis range 등 데이터 규모 기반 질문
- ROAS 같은 무거운 지표 연산을 페이지네이션마다 재계산 → BE 한 번에, FE 클라이언트 필터
- wheel 이벤트마다 blur 성능 영향

### 변경 이력·과거 리뷰

- 변경된 줄의 원래 의도를 `git blame`과 `git log -L <시작>,<끝>:<파일>`로 거슬러 확인한다. 이번 변경이 그 의도를 되돌리거나 예전에 고친 버그를 다시 들이면 지적한다. 근거는 그 커밋의 해시와 제목이다.
- 같은 파일을 건드린 최근 PR을 `git log -n 10 --format='%h %s' -- <파일>`로 찾는다(커밋 제목의 `(#번호)`). 그 PR의 리뷰 코멘트를 `gh pr view <번호> --comments`와 `gh api repos/{owner}/{repo}/pulls/<번호>/comments`로 읽고, 그때 지적된 문제가 이번 diff에도 해당하면 그 PR 링크와 함께 지적한다.

## 출력 형식

카테고리마다 발견이 있으면 `### {카테고리}: N건`과 `- [CRITICAL/INFO] file:line · 설명`을, 발견이 없으면 `### {카테고리}: PASS`나 `### {카테고리}: 해당 없음`을 쓴다.
