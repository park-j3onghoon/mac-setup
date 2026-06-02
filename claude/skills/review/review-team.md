# 팀 리뷰어 시뮬레이션 기준

diff 를 팀 리뷰어들이 실제 PR 리뷰에서 지적하는 **코드 관점**으로 검증한다.
최근 1년(2025-05-21 이후) buzzvil 레포 PR review + commits 에서 추출. 업데이트 시점 2026-05-21.

## 매핑

| ID | 이름 | username | 도메인 |
|---|---|---|---|
| R1 | Frank | `frank-koh` | Ad Management |
| R2 | Zune | `SeoJueun` | CTO |
| R3 | Wynn | `wynnbuzzvil` | Backend EM |
| R4 | BK | `KangBK0120` | Ad Platform / Go·Python |
| R5 | Lucas | `320Hwany` | Ad Platform |
| R6 | Edan | `Hansanghyun-github` | Platform Backend (정산) |
| R7 | Nike | `MiJey` | Platform Backend |
| R8 | Jed | `jeon-jihyeon` | Platform Backend |
| R9 | Dane | `donggoolosori` | Platform Backend |
| R10 | David | `Jin5823` | Ad Management |
| R11 | Scott | `dc7303` | Head of BE / Go |
| R12 | Brice | `ybbarng` | Frontend |
| R13 | Thomas | `Tommybro` | ML |
| R14 | isac322 | `isac322` | Python |
| R15 | Miles | `minjaeleedev` | Ad Expansion |
| R16 | Roha | `Roha-Lee` | Ad Expansion FE |
| R17 | Allan | `allan-kim-buzzvil` | Ad Spark FE |
| R18 | Justin | `justinjeong5` | Ad Expansion FE |
| R19 | Elric | `hugehoo` | Backend |
| R20 | Dean | `cms5380` | Backend |
| R21 | Edward | `C0deWave` | DevOps / Infra |
| R22 | Bale-do | `Bale-do` | Go / 인프라 |
| R23 | jzakka | `jzakka` | Go / Python |
| R24 | glenn4105 | `glenn4105` | Go / AdTech |

---

## 패턴 카테고리

### C1. 권한·인증·보안
- 새 엔드포인트 인증/인가 누락 — R1, R15
- 권한 escalation (외부 클라이언트 ID 주입으로 우회) — R15
- 인증 미들웨어 적용 범위 (어드민 API 에만, multipart 우회 가능성) — R8
- 권한 최소화: `pull-requests: write`, 넓은 GITHUB_TOKEN 권한 — R21
- 공유 캐시/락 의도 (다수 사용자 같은 계정), 세션 캐시 활용 — R11, R19
- 외부 정책 사전 확인 (exelbid 등 파트너) — R22
- SQL injection: `f"...{user_input}..."`, `strings.ReplaceAll` 보간 → strptime/regex/포맷 검증 — R15, R23
- XSS: v-b-popover.html modifier 전역 적용 금지, html 필요한 곳만 객체 `{ content, html: true }` — R16
- GitHub Actions 보안: PAT → GitHub App token, SHA pin, vault — R21
- 외부 시스템 contract 일관성 (SF prefix `[광고센터-자동]`) — R10

### C2. silent 동작 / 기본값 함정
- try/except 후 None 반환 거부 (exception 발생하게 두는 게 자연스러운 경우) — R1, R2
- Sentry 폭증 방지: error message 변동값은 `extra` 분리 — R2
- 무용한 방어코드 제거: 순수 함수 try/except → silent 위험 — R2
- silent default 버그: 클라이언트 필드 누락 → 1 로 초기화 — R2
- silent drop: 컬럼 deprecate 시 기존 적재 데이터 조회 경로 보정 누락 (`cost_event += cost_wel + cost_ref`) — R6
- silent fallback/early_success: 데이터 누락과 mismatch 를 모두 False 로 묶음 → 일시 누락 시 전환 차단 = 매출 손실. matched/mismatched/skipped enum 또는 (bool, reason) — R15
- Liveness 신뢰: handling 추가하지 말고 exception → liveness probe 자연 복구 — R2
- 빈 selector / 빈 문자열 / 0 falsy 엣지: `ppu && dppu`, `[""]`, `rewardType=""` validation 통과, `ratioMin=ratioMax` 동일 값 5번 중복 쿼리 — R16, R20

### C3. 트랜잭션·동시성·원자성
- 트랜잭션 범위: `with uow` 조회만 하는 구간이면 제거 — R6
- 동시성/멱등성: non-idempotent 이중 실행, timeout 파라미터화 — R4
- dual-write: secondary 는 primary 성공 시에만? best-effort? 명시 — R4, R15
- `transaction.on_commit` 안 RPC 실패 시 응답 200 → 운영자 인지 불가. orphan 리소스 → 보상 삭제/outbox — R15
- Promise.all upsert 동시 실행 시 일부 누락 — R9
- SELECT-then-DELETE race condition — R15
- 비결정성: `next(iter(...))`, `interactions[0]`, `ORDER BY event_time` 단독 → ROW_NUMBER + 보조 키 — R15
- Go 루프 변수 함정 (Go 1.21 gotcha): `&p` 슬라이스 원소 포인터 캡처 → 마지막 원소만 가리킴. Goroutine 안 캡처도 동일 — R3, R23

### C4. 정산·금액·시간
- DB 타입: Decimal vs int, PositiveIntegerField 비즈니스 매칭 — R6
- 정산/금액: 소수점·반올림·통화. 환율 변경 시 recalculate 호출 순서/필요성 — R6
- DB 컬럼 타입 한계: `PositiveSmallIntegerField` (max 65535) 에 외부 ID 직접 저장 — R15
- 타임존 명시성: `date.today()` / `datetime.now().date()` 암묵 UTC → `timezone.localdate()` 또는 `ZoneInfo('Asia/Seoul')`. KST 자정~9시 1일 어긋남. Go: `time.Now().UTC()`, 반환값 TZ 함수명 반영 — R13, R15, R16, R22
- KST 윈도우 (00:00 ~ 23:45) 도메인 규칙이 인라인 복제되면 entity classmethod 캡슐화 — R15

### C5. 명명·명시성
- 함수명 = 비즈니스 역할 + 동작 직접 드러나는 이름: 구현 세부 (async/thread) 노출 금지. `FullMissionUpdateUseCase` → `CombineMissionUpdater` — R1, R19
- 컨텍스트 드러나는 이름: "end date" → "가장 나중의 end date" — R4
- boolean 네이밍 (`isRemovable`), 모호한 값 (0/1, win-lose) → 의미 명확하게 — R12
- 도메인 용어 충돌: `Segment` 가 유저 세그먼트로 이미 사용, `experimentGroup` 도메인 prefix — R8, R16
- 매직 값/넘버 → 상수/enum: `-99` 같은 sentinel 어색, `20`/`5`/`60000` 같은 매직 넘버 상수화 — R10, R18, R20, R23
- 이름 변경 최소화: 의미 변경 없으면 안 바꿈 — R24
- 인프라 비독립 네이밍: repository `Set` (redis 의식) → `MarkRewarded` (저장소 무관) — R20
- opinionated user-facing 메시지 경계 — R1
- 에러 메시지 정보성: "failed to ..." 만으로 부족 — R8

> 에러 wrapping/`failed to` prefix 회피 → C14 Go 패턴 참조

### C6. 추상화·레이어·구조
- 과도한 추상화 견제: 한 곳에서만 쓰는 클래스 인라인, factory 패턴 인터페이스 안 되면 코드 분리 — R14
- 외부 라이브러리 설정을 직접 옮기지 말고 "지금은 너무 많은 추상화 피하고 그대로 두자" — R11
- facade 분리, 구조체 vs string 분리 필요성 견제 — R3
- 단순함 우선: 복잡하지 않으면 외부 라이브러리/함수화 굳이 필요 없음 — R20
- 다형성 필요성 검증: 단일 구현이면 인터페이스 분리 불필요 — R24
- 레이어 의존성 방향: domain 이 라이브러리 종속 X, application use case 가 ORM 직접 호출 X. `adscenter/CLAUDE.md` onion — R14, R15
- DDD: dynamo 에러를 controller 직접 노출 X → usecase 에러 변환 — R3
- Django base table 상속 회피 (pk/migration 누락) — R2
- 레이어 배치: `slack_sdk` 의존만 있으면 `adapters/` 이동. dash 로직을 `dash_api_views.py` 같은 잘못된 위치에 작성한 이유 — R5, R6

> 컴포넌트 책임 분리·분리 vs 인라인 균형 → C13 Frontend 참조

### C7. 기존 코드 재사용 / DRY
- 기존 헬퍼/인터페이스/함수 재사용: 새 플래그 대신 기존 진입점, 이미 만들어둔 인터페이스/구조, `invoice.is_draft()`/`GetUserMissionProgressByESID` 같은 도메인 메서드 — R4, R5, R11, R24
- 2곳 이상 중복 → 모델/유틸/composable 추출. 두 main 파일 동일 코드는 헬퍼. 도메인 간 동일 코드는 composable — R8, R16
- 사용처 없는 함수/필드 제거: deprecate 없이 바로 — R4, R13
- 무관한 변경 분리: 이번 PR 과 무관하면 별도 후속 PR. 컨벤션 충돌도 별도 리팩토링 PR — R5, R10, R20
- 이름만 바꾸기 자제: 의미 변경 없으면 — R24
- 검증 로직 중복: 한쪽에서만 — R19
- 다중 반환값 컨벤션: `value, exists := getter()` — R24

### C8. DB·스키마·쿼리
- DynamoDB 함정: Limit+Filter (Limit 가 Filter 전 적용 → 빈 결과), `TransactWriteItems.CancellationReasons`. `result_bytes`/`estimated_page_count` 는 Filter 후 응답 크기 → 비용 과소 추정 → `consumed_capacity` — R4, R8, R11
- N+1: 즉시 식별 + 페이지네이션 안전 가드. 이번 PR 은 N+1 만 분리 원칙 — R4, R6, R11
- 일괄 적용 누락: A/B/C 라인 → D 추가 시 A/B/C 업데이트 전파 누락 — R4
- 인덱스 적합성: 복합 인덱스를 단일 컬럼 조회로 안 탈 가능성 (R8). 카디널리티 낮은 컬럼 선행 비효율 (R5). hash/range key 명시·음수 가능성 (R3)
- DB ORM connection 설정 변경 신중 (전체 API 영향, 1Q 검증) — R2
- chunk 단위 삭제 — R2
- Django `bulk_create(update_conflicts=True)` 는 `Model.save()` 미경유 → `auto_now` 동작 X. 수동 `timezone.now()` + `update_fields` + 테스트 — R7
- JSON 스키마: dict 직접 노출 금지, typed schema. **Union 금지** (DB 분석 어려움). OG 패턴 일관 — R10
- enum/sentinel 명시 (DB 레벨) — R10, R23
- Nullable 정책: 비즈니스 필수면 Non-Nullable — R10
- DB ID 재배정 추적 — R4
- 마이그레이션 누락: 새 enum 값, 코드만 변경 vs db 변경 구분 — R19, R20
- ES mapping JSON 문법 검증: 닫는 중괄호/쉼표 누락 줄 번호로 정확히 — R23

### C9. AI 생성 코드 가드
- `# type: ignore` 추가/타입힌트 약화는 의도 확인 — R4
- AI/Claude 생성 spec/migration/code 무비판 수용 거부. follow-up PR 로 정리 — R11
- AGENTS.md/CLAUDE.md 협업 문서에서 위험 명령 제거 — R11
- AI 생성 PR 본문이 기계적이면 "실제 의도" 작성 요구 — R10
- AI 가 못 잡는 비즈니스 로직은 한글 주석 강화 — R7
- stock template (`openspec init --tools claude`) byte-identical 유지 (patch 시 다음 update 회귀) — R15

### C10. 운영·관측성·배포
- 에러 로그 레벨: info → error/warn — R3
- 에러 컨텍스트: 식별자 (`ifa`, `device_id`, `unit`, `appid`) 포함 — R3, R7
- 운영 진단성: `KeyError` 대신 `unit_id`/`month` 포함 `ValueError` — R7
- Stale 주석 제거 — R3
- production 로그 노이즈: 라인아이템마다 debug 로그 머지 전 제거 — R23
- 로그 레벨 일관성: Info 에 `[DEBUG]` prefix 가 테스트 전용인지 — R8
- 로그 샘플링: 새 위치에 기존 규칙 적용 — R20
- 로그 구조화: 분할보다 단일 라인 필드 묶음, correlation_id — R24
- 메트릭 명명 일관성: candidate vs lineitem 통일, 카운터 순서 (Daily-Total) — R4
- 메트릭 확장: 새 로직에 custom metric (exchange + item type 카디널리티) — R4
- 메트릭 중복/목적 모호 — R8
- 변경 영향 추적: 미사용 코드 제거 PR 에서 추가/제거 PR 모두 코멘트 — R2
- 점진 적용/% 분할: 전체 revenue type 동시 변경 위험 시 — R4
- 다중 서비스 배포 누락: campaign-indexer/indexing-verification 함께 — R24
- 배포 환경 태그 확인: biddersvc 뿐인지 — R24
- 배포 순서 명시 (BE 먼저 → gateway → FE) — R1, R11, R15
- buzzapis/grpc spec 버전 일치: requirements 변경 시 buzzapis 동시 PR, deploy 알림 — R1

### C11. DevOps / Infra
- Atlantis plan diff 에 의도하지 않은 리소스 추가 차단 — R21
- 태그/네이밍 표준화: `terraform.env` 태그 ops/dev/staging/prod — R21
- 권한 분리 환경별: dev/prod IAM — R21
- Recreate/Drift 사전 경고: terraform plan 에서 recreate 명시 — R21
- 데이터 트래픽 기반 판단: HPA 축소 같은 영향 큰 변경 — R21
- 재시도/백오프 일관성: 최대 4회, 1s/2s/4s/8s — R21
- 인프라/배포 영향 범위: helm values, virtual service, mesh forwarding. canary 적용 가능성 — R22
- 환경 의존 설정: 하드코딩이 env 따라 달라져야 하는지, 미사용 ENV 제거 — R22
- 인프라 설정 디테일: ServiceMonitor port, extraServicePorts, helm chart — R20
- 안 쓰는 좀비 step 제거: `snok/install-poetry` 등 — R7
- 린트/CI 자동화 비용 (`go run` 매 커밋 컴파일, CODEOWNERS 매핑) — R19

### C12. 테스트
- 회귀 가드: 빈 source padding, monthly aggregate 합산 누락 — R7
- 테스트 의도-검증 일치: docstring 약속을 실제 assertion 수행하는지. `assert_called_once()` 만 끝나면 계산 결과 누락 — R7
- mock 충실성: `side_effect` vs `return_value` 불일치, monthly 분기 합산 누락 — R7
- side effect 외부 주입: 현재 시간도 side effect, TimeProvider 주입 (영업일/공휴일 flaky 제거) — R14, R20
- 표준 라이브러리: `AsyncMock`, `aioresponses` — R14
- 테스트 가독성: 인덱스 직접 접근 대신 `adnetwork_id`/`unit_id` 명시. parametrize 보다 분리 — R6
- Given/When/Then 일관성. lazy import 금지. `faker.unique` 누적 상태 — R15
- 테스트 컨벤션 일관성 vs 강요: per-function vs table-driven 일관되면 강요 X — R4
- 테스트 커버리지 + API 스펙 일관성 — R11
- Top-K/임계값 의도: `actual_ranked_segments` 가 top_k 이상인 것만 평가 — R13

### C13. Frontend (Vue/React)
- Composition API + script setup, `import { nextTick } from "vue"` 직접 import. dash-next 컨벤션 — R16
- 컴포넌트 책임 분리: open 핸들러에 비즈니스 로직 금지 — R16
- 컴포넌트 분리 vs 인라인 균형: 단순 wrapper 는 별도 X, 길어진 렌더링은 분리 — R17
- form 상태 동기화: form 내부 값으로, 별도 useState 시 동기화 깨질 우려 (`cpas-ad-set.form.ts.isAutoDailyBudget`) — R17
- form Hook Options 일관성: `defaultValues + onSubmit` 패턴, useAppForm 즉시 return — R17
- 타입 안전성 (literal union/type predicate): `as` 캐스팅 대신 `.filter((v): v is string => Boolean(v))`. 리터럴 유니온/enum — R16
- 느슨한 비교 지양: 형변환 위험. 일관된 null/undefined 체크 헬퍼 — R16
- API/도메인 enum: string union 대신 enum, PascalCase + `-Enum` — R17
- BE/FE 미사용 필드 제거. camelCase/snake_case 일관성 — R17
- 공통 컴포넌트/유틸 재사용 (`formatNumberWithCommas`, `IconState`, `Header`, `stringSchema()`) — R17
- 웹 스토리지 SafeStorage 패턴 — R17
- 내비게이션 가드: 취소 + showConfirm (라이브커머스/협력광고 일관) — R17
- 데이터 모킹 위치: 전부 mocks.ts — R17
- subscribe vs useStore: `form.Subscribe` 로 불필요 리렌더링 방지 — R17
- Watch 가독성: named method 추출 — R16
- Vue 관용: `?? `, `Record<>`, composable 추출 (`useDocumentTitle`) — R9
- URL state vs local state 일관성: 다른 필터가 URL 이면 동일하게 — R16
- Radix 내부 selector 의존 경계: `portalRef.closest("[data-radix-portal]")` 라이브러리 업데이트 시 깨질 수 있음 — R16
- 불필요한 onError 패스스루: `options?.onError?.(...args)` 만 호출 → `...options` spread — R16
- viewport overflow / responsive: rem 변환 + px 단위 검증 (320px viewport overflow 등) — R18
- Figma 디자인 일치 검증: 사이드바 아이콘/메뉴 순서/hover 애니메이션. 디자인에 없는 동작 (사이드바 숨김 등) 제거 — R17
- 타입명 간결화: `DisplayCampaignRequestDetail` → `DisplayCampaignDetail`, `displaycamId` → `campaignId` — R17

### C14. Go 패턴
- 에러 래핑: `fmt.Errorf("...: %w", err)`. Uber Go style. `failed to` prefix 회피 (내부 컨벤션). sentinel + 컨텍스트: `fmt.Errorf("%w: flagID is empty", ErrInvalidConfig)` — R11, R19, R23
- nil/panic 가드: 타입 단언, 인덱스 경계, `MustGet` panic 가능성 — R4, R19, R22
- panic 대신 error 리턴: 비즈니스 로직 panic 던지면 프로세스 그대로 뻗어버림 — R19
- ctx 전파: `context.Background()` 새로 만들기보다 상위 ctx — R19
- 구체 타입 vs `interface{}`: 동적 타입 노출 회피, 제네릭 — R11
- Private 가시성: 패키지 내부 사용은 private — R11
- HTTP status code 추론: `ErrEmailVerificationNotFound` → 404 — R11
- early return / 깊은 중첩 줄이기 — R20, R24
- 불필요 루프 invariant 제거: 루프 밖으로 — R24
- Go for-range 복사 비용: 큰 struct → `for i := range slice` + `&slice[i]` 인덱스 (validate hot path) — R20
- 불필요 슬라이스 캐스팅: `[]string{}` vs nil slice + append — R19
- 함수 visibility: private 이 외부 3곳+ 호출되면 public 승격 — R19
- 불필요 임베딩: 작업자 외 이해 어려운 구조 — R19
- proto/toolchain 버전 다운그레이드 사이드이펙트, 직렬화 번호 점프 이유 — R22, R23, R24
- Kafka: consumer lag, micro-batch, confluent — R22, R24

> 다형성 검증 → C6 추상화·레이어·구조 참조

### C15. Python 패턴
- Python typing: `Optional[]` 누락, `ClassVar` 명시, abstract method 시그니처 — R14
- Optional: 빈 컬렉션 가능하면 Optional 불필요 — R14, R23
- enum (Python 관용): char/string 대신, classmethod vs staticmethod — R23
- 관용구: defaultdict vs setdefault, list vs set — R4
- asyncio 정석: `asyncio.run`/`asyncio.gather`, 수동 event loop 지양. aiohttp connector 공유 — R14
- Redis cluster: slot 제약, TTL. pattern 후 추가 필터링 중복, pipeline 중복 제거 — R2, R22
- 시간 계산: off-by-one, async blocking — R22
- `TOKEN_MANAGER` 같은 UPPER_SNAKE 를 인스턴스 변수에 쓰지 않기 — R3
- private 속성 접근: 외부에서 꺼내 쓰는 패턴 → public 접근자/생성자 주입 — R23
- dependency 분류: 테스트 전용은 `dev.in` — R14
- 하드코딩 만료/정리 계획 주석 (캠페인 ID allowlist 같은 일회성 데이터) — R23
- 하드코딩 vs 설정: 비즈니스 값을 환경변수로 — R19, R23

> 타입 힌트 약화 → C9 AI 생성 코드 가드 참조

### C16. 데이터·ML·쿼리
- SQL 쿼리 논리 정합성: JOIN 순서, GROUP BY/DISTINCT, 1:N 카운팅 — R13
- 데이터 정의 검증: 쿼리 결과가 비즈니스 정의와 일치 — R13
- 피처 일관성 (Python ↔ SQL): MULTIMAP_AGG/REDUCE 같은 비용 큰 시퀀스 피처 잔존 — R13
- 비용 절감: Athena/Trino 파티션 프루닝 — R13
- 모델 식별자: None/"None" 혼용 → enum — R13
- 임베딩/캐시 키 적용 범위: 부분 적용 시 전체 입력 시작 부분 일괄 — R13
- 하드코딩 결정 근거 기록 — R13

### C17. 코드 위생·잔여물
- 코드 주석 처리 대신 삭제 — R12
- console.log, 미사용 주석/코드 — R9
- gitignore 누락 (`.playwright-mcp` 등 도구 산출물) — R9
- 미사용 import / 변수 / props
- 불필요한 `.filter(Boolean)` / dead code
- master 에 이미 추가된 권한 코드라면 PR 에서 제거 — R9
- 불필요 어노테이션 정리 (chart configmap spinnaker 잔재) — R21

### C18. 성능
- 성능 임계점 사전 경고: in-memory sort 5천건, 24시간 redis range 등 데이터 규모 기반 질문 — R1
- ROAS 무거운 연산 페이지네이션마다 재계산 → BE 한 번에, FE 클라이언트 필터 — R10
- wheel 이벤트마다 blur 성능 영향 — R9

> 점진 적용/% 분할 (revenue type 전체 동시 변경 위험) → C10 운영 참조

---

## 출력 형식

리뷰어별로 이슈 있으면 `### R{N} ({이름}): N건` + `- [CRITICAL/INFO] file:line — 설명 (카테고리: C{N})`, 없으면 `### R{N} ({이름}): PASS`. 작업은 R{N}로 하고 **최종 보고 시에만** 이름으로 변환. C{N} 패턴은 본 문서로 확인. 각 리뷰어의 전문 도메인은 매핑표 참조 — 해당 리뷰어가 강조하는 카테고리 위주로 점검한다.
