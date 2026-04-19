# 팀 리뷰어 시뮬레이션 기준

diff를 **팀 리뷰어들이 실제 PR 리뷰에서 지적하는 패턴**으로 검증한다.
각 리뷰어의 관점은 실제 PR 리뷰 이력에서 추출한 것이다.

---

## 리뷰어별 관점

### Frank (Ad Management)
- **명시성 우선**: default 값으로 버그가 silent하게 성공하지 않는지. `or None` 같은 불필요한 코드.
- **함수명 = 비즈니스 역할**: 함수명에 구현 세부사항(async, thread) 노출 금지.
- **필드 명시적 나열**: 동적 탐색보다 target_* 필드 하드코딩 (향후 필드 추가 시 의도치 않은 포함 방지).
- **모델-테이블 컬럼명 일치**: 디버깅 용이성.
- **환경 설정 explicit**: `IS_PROD_ENV=False` 대신 실행 가능 환경 명시 나열.

### Zune (CTO)
- **레플리카/마스터 분리**: DB 쿼리가 올바른 DB 사용. 레플리카 fallback이 마스터를 죽일 수 있는지.
- **고트래픽 테이블 비대화**: 빈번 조회 테이블에 불필요한 컬럼/데이터 추가.
- **장애 전파 방지**: 일괄 적용 로직이 추후 맥락 모르는 사람이 작업 시 문제 가능성.

### Wynn (Backend EM)
- **에러 로그 레벨**: error vs warn vs info 적절성.
- **에러 메시지 컨텍스트**: 에러 로그에 event_id, user_id 등 디버깅 정보 포함.
- **에러 wrapping**: `fmt.Errorf("... %w", err)` 패턴.
- **API 설계**: boolean 과다 시 filter 구조체 통합, 중복 API.

### BK (Ad Platform)
- **DynamoDB Limit+Filter**: Limit는 Filter 적용 전에 동작 → 빈 결과 반환 가능.
- **에러 wrapping 패턴**: `failed to` prefix 불필요 중복.
- **동시성**: non-idempotent 연산의 이중 실행 방지, 타임아웃.

### Lucas (Ad Platform)
- **Go 관용 패턴**: context logger, error wrapping, interface 분리.
- **nil 체크**: mock에서 `ret.Get(0).(*Type)` 직접 단언 시 nil 체크.
- **파라미터 구조체**: 파라미터 많으면 struct 관리.

### Edan (Platform Backend)
- **트랜잭션 범위**: 불필요하게 넓지 않은지. 읽기/쓰기 분리.
- **DB 타입 적절성**: Decimal vs int, PositiveIntegerField 등 비즈니스 매칭.
- **정산/금액 정확성**: 소수점, 반올림, 통화 처리.

### David (Ad Management)
- **FE-BE 데이터 정합성**: 데이터 포맷 prefix 중복, 타입 불일치.
- **API 실패 시 UI 상태**: finally에서 서버 실패와 불일치.
- **프로젝트 컨벤션 일관성**: 한 파일만 변경하면 UI 일관성 깨지는 경우.

### Scott (Head of BE)
- **네이밍 명확성**: "end date"보다 "latest end date among line items".
- **중복 로직 추출**: 유사 패턴 반복 → 함수 추출.
- **설계 의도 일치**: secondary write가 primary 성공과 무관하게 실행되어야 하는지.

### Brice (Frontend)
- **useEffect 의존성**: 배열 누락 → Maximum update depth 에러.
- **조건 분기 불일치**: dateRange start/end 중 하나만 있을 때.
- **sessionStorage/localStorage**: SSR 환경 접근 가능성.

### Thomas (ML)
- **SQL 쿼리 논리 정합성**: JOIN 순서, GROUP BY/DISTINCT, 1:N 카운팅 중복.
- **데이터 정의 검증**: 쿼리 결과가 비즈니스 정의와 일치하는지.

### isac322 (Python)
- **Python typing**: `typing.overload`, mypy 호환 힌트, 기본값/annotation 일치.
- **리소스 정리**: cursor.close() 누락, context manager 오용.
- **에러 타입**: None vs ValueError — 호출자 디버깅 용이성.

### Miles (Ad Expansion)
- **설계 패턴 적용**: gateway 패턴 등 이론적 근거.
- **타입 안전성**: Any 대신 구체 타입 (boto3 stub 등).

### Roha (Ad Expansion Frontend)
- **타입 안전성**: `as` 캐스팅 대신 type predicate(`.filter((v): v is string => Boolean(v))`)로 컴파일러가 타입을 좁히게 하기. 느슨한 비교(`!=`) 대신 명시적 null/undefined 체크.
- **엣지 케이스 방어**: 값이 0일 때 falsy로 빠지는 조건문, 빈 문자열 배열(`[""]`), 기존 데이터의 null 필드 등 경계값 처리.
- **컴포넌트 책임 분리**: UI 컴포넌트의 open 핸들러에 비즈니스 로직 금지. composable/hook으로 재사용 가능한 로직 추출. 하위 컴포넌트에 전달하는 데이터 범위 최소화.
- **네이밍/도메인 용어 충돌**: 기존 코드베이스에서 이미 사용 중인 용어와의 충돌 방지 (예: "Segment"가 유저 세그먼트로 이미 사용 중).
- **Vue 컨벤션**: 새 컴포넌트는 Composition API (script setup) 사용. `nextTick` 직접 import. 팀 컨벤션 문서 링크와 함께 지적.
- **운영 영향**: 기존 데이터 마이그레이션 필요성, 복제 케이스 고려, API 실패 시 의도치 않은 성공 방지.
- **코드 위생**: 불필요한 파일 제거, 포매팅 설정 불일치, 중복 import, `<br>` 대신 CSS 간격.
- **XSS/보안**: `v-b-popover.html` 같은 HTML 렌더링 modifier를 전역 적용하지 말 것. HTML이 필요한 곳에서만 객체 형태 `{ content, html: true }` 사용하여 범위 최소화. escapeHtml 누락 시 즉시 XSS 취약.
- **DRY 강조**: 2곳 이상 반복되는 로직은 공유 유틸리티 또는 모델 메서드로 추출. 같은 로직이 다른 이름으로 존재하면 일관된 네이밍도 함께 지적.
- **Watch 가독성**: watch handler에 구현 디테일이 인라인되면 "추상화 레벨을 올려라" 지적. named method/function으로 추출하여 handler 이름만으로 역할 파악 가능해야 함.

### Allan (Ad Spark Frontend)
- **과도한 컴포넌트 분리 지양**: 단순한 구조(h1+버튼 등)는 별도 파일 불필요, 인라인 또는 기존 공유 컴포넌트 사용 권장.
- **파일 역할 경계 엄격**: `env.ts`는 환경변수 wrapping 전용. 비즈니스 맥락 상수는 사용처 가까이에 정의. `!IS_PROD`처럼 단순 표현으로 충분하면 별도 상수 만들지 않기.
- **Figma 디자인 일치 검증**: 사이드바 메뉴 순서, 아이콘, 레이아웃이 Figma와 정확히 일치하는지 확인. 디자인에 없는 동작(사이드바 숨김 등) 추가 금지.
- **아이콘은 UI Kit에서 실제 SVG 추출**: 추측으로 만들지 말고 Figma UI Kit에서 `exportAsync`로 추출. 하드코딩 색상 아이콘은 `currentColor` 치환하지 않음.
- **Layout/Page 관심사 분리**: Layout은 metadata + children만. 스타일링 wrapper(`MainContent` 등)는 각 Page에서 감싸기.
- **불필요한 Fragment 제거**: `<>{children}</>` 대신 `return children`.
- **API/도메인 타입은 enum**: 컴포넌트 props는 string union OK, API/도메인 레이어 타입은 enum 사용 지향. 프로젝트 패턴: `UserRoleEnum`, `CoverageTypeEnum` 참조. 키는 PascalCase, 접미사 `-Enum`.
- **타입명 간결하게**: `DisplayCampaignRequestDetail` → `DisplayCampaignDetail`. 불필요한 단어 제거.
- **form hook Options 일관성**: 훅 Options가 기존 form들(`create-catalog.form.ts`, `cpas-ad-set.form.ts` 등)과 동일한 `defaultValues + onSubmit` 패턴인지 확인. 개별 필드 나열 방식 지적.
- **비표준 축약어 금지**: `displaycamId` 같은 불명확한 축약 대신 `campaignId`처럼 의미 명확하게.
- **프론트 미사용 필드 제거**: BE 응답에 있더라도 프론트에서 쓰지 않는 필드는 타입에서 빼기. 다른 도메인과의 네이밍 일관성도 확인 (snake_case 등).
- **기존 타입과 비교**: 새 타입 추가 시 유사한 기존 타입(live-commerce 등)과 비교하여 재사용 가능 여부 확인.
- **form 상태 동기화 엄격**: form에서 쓰이는 상태는 form 내부 값으로 관리. 별도 `useState`로 관리하면 동기화 깨질 우려. `cpas-ad-set.form.ts`의 `isAutoDailyBudget`처럼 form 스키마에 boolean 필드로 추가.
- **웹 스토리지 SafeStorage 패턴**: `localStorage` 직접 사용 대신 `SafeStorage` config + `safeStorage` 유틸 사용 권장.
- **내비게이션 가드 패턴**: `beforeunload` 대신 취소 버튼 `showConfirm`으로 확인 (라이브커머스/협력광고 일관성). 추가 내비게이션 가드 필요 시 라이브러리 도입 검토.
- **리뷰 스타일**: 구체적 대안 제시 ("Header 컴포넌트 사용", "!IS_PROD로 충분"). Figma 스크린샷 첨부하여 시각적 근거 제공. suggestion 코드 블록 적극 활용.

### Justin (Ad Expansion Frontend)
- **매직 넘버 상수화**: 하드코딩 값 발견 시 환경변수/상수 추출 권유 (NIT 수준).
- **프레임워크 문법 정확성**: Vue `::v-deep` → `deep()` 변경, 파일명 PascalCase 등 프레임워크 컨벤션 확인.
- **설계/아키텍처 (RFC)**: 패키지 경계 설계, 모니터링 인프라 선행 조건, A/B 테스트 baseline 메트릭·Go/No-Go 기준 수립. RFC 리뷰에서 가장 상세한 피드백.
- **낙관적 설계**: UX 레이아웃 시프트 방지를 위한 optimistic 패턴 (로딩 중에도 표시).
- **근본 원인 해결**: 단순 수정보다 리팩토링 PR을 직접 만들어 의존성 역전·중복 로직 제거.
- **리뷰 스타일**: 85% LGTM 빠른 승인. 지적 시 "닛픽킹입니다" 톤. CHANGES_REQUESTED 0건, 항상 선 APPROVE.

---

## 언어별 리뷰어 관점

리뷰어: Bale-do(junhodo), dc7303(Scott), jzakka, glenn4105, KangBK0120.

### 공통 (언어 무관)
- **도메인/비즈니스 로직 정합성** (glenn, KangBK, jzakka): 코드가 실제 비즈니스 규칙 반영. 하드코딩 값이 합의된 것인지.
- **네이밍 = 도메인 의미** (Bale-do, KangBK, jzakka): verbose하더라도 목적이 드러나는 이름. 사용처와 불일치 지적.
- **운영 안전성** (Bale-do, glenn, KangBK): staging 검증, 배포 모니터링, 마이그레이션 누락.
- **불필요한 코드 제거** (Bale-do, jzakka): 쓸모없는 if문/로그, indent 변경 노이즈.
- **관측성 유지** (Bale-do, KangBK): sentry 제거 시 대안, 공통 instrument 패턴.
- **설계 적절성** (KangBK, glenn, dc7303): 과도한 추상화 vs 실용적 단순성.
- **에러 처리 계층** (Bale-do, jzakka, KangBK): infra vs usecase layer, 내결함성 TC.
- **하위 호환성** (Bale-do, glenn): proto 하위호환성, 다른 팀 승인 필요성.

### Go 전문 리뷰어
- **에러 래핑** (dc7303): `%w` 패턴, `failed to` 중복 (거의 매 PR 지적)
- **nil/panic 방지** (Bale-do, KangBK): 타입 단언 nil 체크, 인덱스 경계
- **기존 코드 재사용** (dc7303): BA 클라이언트 등 이미 구현된 것 활용
- **Optional/nil 구분** (jzakka): `*int32` vs `int32`, 컴파일타임 인터페이스 검증
- **타임존 명시성** (Bale-do): `time.Now().UTC()`, 반환값 TZ 함수명 반영
- **패키지 구조** (jzakka, KangBK): 순환참조 체크
- **Kafka** (Bale-do, glenn): consumer lag, micro-batch, confluent 라이브러리
- **DynamoDB** (dc7303): Limit+Filter 함정
- **proto** (glenn, Bale-do): gen-go 버전, 직렬화 번호 변경

### Python 전문 리뷰어
- **타입 안전성** (KangBK, jzakka): 타입 힌트 약화, `# type: ignore`, AI 생성 코드 가드
- **enum** (jzakka): char/string 대신 enum, classmethod vs staticmethod
- **Optional** (jzakka): 빈 컬렉션 가능하면 Optional 불필요, `from_*` 패턴
- **관용구** (KangBK, Bale-do): defaultdict vs setdefault, list vs set
- **Redis cluster** (Bale-do): slot 제약, TTL
- **시간 계산** (Bale-do): off-by-one, async blocking

### Java 전문 리뷰어
- **Kafka Producer** (dc7303): linger.ms, batch.size 점진적 튜닝
- **설정값** (dc7303): 하드코딩 → 환경변수

---

## 출력 형식

각 리뷰어별로 해당하는 이슈가 있으면:
```
### [리뷰어명] 관점: [N건 발견]
- [CRITICAL/INFO] file:line — 설명
```
해당 없으면: `### [리뷰어명] 관점: PASS`
