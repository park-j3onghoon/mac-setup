# 언어별 공통 리뷰 기준

diff의 변경된 파일 언어를 감지하여 해당 언어의 관용구, 안전성, 플랫폼 특화 이슈를 검증한다.
**해당 언어 파일이 diff에 없으면 해당 섹션을 건너뛴다.**

---

## Python

### 타입 안전성
- 타입 힌트가 약해지지 않았는지 (`Any` 추가, 구체 타입 → Union 등)
- `dict` 대신 `dataclass`, `NamedTuple` 사용 권장
- `# type: ignore` 추가 시 이유가 명확한지
- `Optional` 남용: 기본값으로 빈 컬렉션 사용 가능하면 Optional 불필요
- enum: char/string 필드보다 enum으로 잘못된 입력 방지
- `classmethod` vs `staticmethod` 구분 (클래스 연관성 기준)
- 신규 `.py` 는 `from __future__ import annotations` 선언 — 런타임 타입 평가 회피 + forward reference 단순화

### 관용구
- `defaultdict` vs `setdefault` 적절한 선택
- `list` 대신 `set` (집합 연산 시)
- 팩토리 메서드는 `from_*` 패턴 선호
- Forward Reference (따옴표 타입힌트) 이유 이해

### 리소스/안전성
- cursor.close() 누락, context manager 오용
- 에러 타입: None 반환 vs ValueError — 호출자 디버깅 용이성
- Redis cluster mode에서 서로 다른 slot 조회 불가 → hashtag 또는 단일 key
- Redis TTL 설정 누락
- 시간 계산 off-by-one: `floor`/`shift` 경계값 오류
- async wrapping으로 commit blocking 방지

### Django 특화
- ORM `.annotate()` 에 새 필드 추가 시, 결과 dict 키와 dataclass 필드 일치 확인
- migration 파일 누락 / 순서 오류
- `PositiveIntegerField` vs `BigIntegerField` 등 타입 적절성
- `.iterator()` 는 결과를 즉시 `list()` 로 materialize 하면 이득 없음(스트림 소비를 안 하므로). 무거운 엔티티 대량 스캔에서 queryset `_result_cache` 중복 보유를 피하는 용도이고, 청크로 바운드된 가벼운 projection(`values_list`)을 list 화하는 경우엔 불필요 — `list(qs.iterator())` 를 관성적으로 붙이지 말 것

### 스타일 / 복잡도
- early return 으로 중첩 해소 — 함수 내 들여쓰기 3단계 이내
- 함수당 분기 5개 이하 — 초과 시 헬퍼로 분리
- `os.path` 대신 `pathlib`
- bare `except:` 금지 — 구체 예외만 catch
- 1회성 로직에 ABC/Protocol 도입 지양 (과도한 추상화)

---

## Go

### 에러 핸들링
- 레이어 경계에서 `fmt.Errorf("...: %w", err)` 패턴 사용
- **다중 에러 체인은 `fmt.Errorf("%w: %w", e1, e2)` 또는 `errors.Join(...)`** — silent discard 금지. 재시도 제어가 필요하면 `skipRetry` 등 제어용 에러를 join.
- **비핵심 I/O(postback·enrichment 등) 에러를 `log.Warnf`로 기록하고 계속 진행하는 패턴은 silent discard가 아님** — 메인 흐름을 막지 않는 의도적 설계. 이를 "에러 무시"로 오flag하지 말 것.
- `failed to` prefix 불필요 중복
- 에러 체크 일관성

### 안전성
- 타입 단언(`ret.Get(0).(*Type)`) 시 nil 체크
- 인덱스 경계 검사 (`tokens length check`)
- 형변환 실패 시 panic 가능성
- `*int32` vs `int32`, `optional` proto field로 nil/zero-value 명확 구분
- 컴파일 타임 인터페이스 검증: `var _ Interface = (*Impl)(nil)`
- **방어 코드 제거**: 빌드타임에 보장되는 nil 체크·생성자가 보장하는 invariant·도달 불가 경로의 방어 코드는 잉여 → 제거. (cf. SKILL 5a — 방어 코드 *추가* 는 ASK, *제거* 는 품질 개선. `sync.Once`+`init()` 동시 사용도 중복 방어)
- `&slice[i]` 등 슬라이스 원소 직접 참조(aliasing) 지양 — append/재할당 시 stale 포인터.

### 관용구
- context 기반 logger 사용
- interface 분리 (ISP)
- 파라미터가 많으면 struct로 관리
- `time.Now().UTC()` 명시 — `time.Now()` 사용 시 TZ 불명확
- 함수 반환값의 TZ가 함수명에서 드러나지 않으면 경고
- **mapper 대신 생성자(`NewXxx(...)`)**: entity 변환은 생성자로 — 필드 추가 시 컴파일타임에 누락 검출(struct literal/mapper 는 silent zero-value).
- worker/handler 같은 메커니즘 이름보다 usecase 목적을 드러내는 이름 선호.

### 패키지/구조
- 패키지 간 import 방향 — 순환참조 여부
- 불필요한 패키지 분리보다 단순 구조 선호
- 기존 코드/라이브러리 재사용 — 이미 구현된 클라이언트 있는지 확인

### 인프라 특화
- Kafka consumer/producer: consumer lag, micro-batch, confluent 라이브러리, `read_committed` 필요성
- DynamoDB `Limit + FilterExpression`: Limit가 Filter 적용 전에 동작 → 빈 결과 가능
- proto 하위호환성: gen-go 버전 불일치, 직렬화 번호 변경

### 테스트 (Go)
- **mock은 mockgen 생성물** — hand-rolled stub 지양. 생성자 정식 경로(`NewXxx(..., dep)`)로 주입하고, 테스트에서 unexported 필드 직접 세팅 금지(생성자 우회는 미래 필드 변경 시 깨짐).
- **테스트 상수/구조체는 alias 선언 + helper 로 생성** — 프로덕션 상수를 테스트에서 직접 참조 금지. 테스트 전용 리터럴이라야 정책 변경 시 회귀를 독립적으로 감지.
- **`gomock.Any()` 남용 금지** — 검증 대상 필드는 명시적으로 매칭.
- give-when-then 순서. DI 불필요한 domain/entity/util 은 suite 없이 단순 테스트로 충분(최상위 pkg, 무의존).

---

## Java

### Kafka
- `linger.ms`, `batch.size` 등 batching 설정 적정성
- 모니터링 기반 점진적 접근 권장

### 설정
- 하드코딩된 설정값은 환경변수로 관리

---

## Kotlin / Spring Boot

### null safety
- `!!` 사용 금지, `?.let` / `?:` / `requireNotNull` 활용
- data class 불변성, copy() 활용
- `@field:NotBlank` 등 어노테이션 정확한 target 지정
- sealed class/interface로 타입 안전 분기

---

## Frontend (JavaScript/TypeScript/Vue/React)

### React
- useEffect 의존성 배열 누락 → Maximum update depth 에러
- 상태 업데이트 batching 이해

### 안전성
- sessionStorage/localStorage: SSR 환경에서 접근 가능한지
- dateRange 검증: start_date/end_date 중 하나만 있을 때 엣지케이스
- API 실패 시 UI 상태: finally 블록에서 서버 실패와 불일치 가능

### 컨벤션
- 한 파일만 변경하면 UI 일관성이 깨지는 경우 별도 이슈 제안
- 새 Vue 컴포넌트는 Composition API (script setup)
- **Zod 문자열 스키마**: `z.string().min().max().refine()` 수동 체이닝 대신 `stringSchema()`/`urlSchema()`/`emailSchema()` (`@/schemas/common`) 사용 여부 확인
- **form 훅 경량화**: `useFooForm` 훅이 `return useAppForm(...)` 단일 반환인지 확인. mutation/업로드/에러 처리가 훅 내부에 있으면 지적
- **form hook Options 패턴**: Options 타입은 `{ defaultValues?: Partial<Input>; onSubmit: (values: Values) => Promise<void> | void }` 형태 사용. 개별 필드를 각각 optional param으로 나열하지 않음 (`create-catalog.form.ts`, `cpas-ad-set.form.ts` 등 기존 패턴 참조)
- **form 관련 상태는 form 내부에서 관리**: UI 토글(일 예산 표시 여부 등)을 `useState`로 별도 관리하면 form 상태와 동기화가 깨질 수 있음. form 스키마에 boolean 필드(`showDailyBudget` 등)로 추가하여 form 내부에서 관리 (cpas `isAutoDailyBudget` 패턴 참조)
- **웹 스토리지는 SafeStorage 패턴 사용**: `localStorage.getItem/setItem` 직접 사용 대신 `SafeStorage` config(`constants/storage.ts`)를 정의하고 `safeStorage.get/set`(`utils/safe-storage.ts`)을 사용. 키 중앙 관리 + Zod 파싱 + 에러 핸들링
- **내비게이션 가드는 취소 버튼 showConfirm**: `beforeunload` 대신 취소 버튼 클릭 시 `useConfirm`으로 isDirty 체크 (라이브커머스/협력광고 패턴). 추가적인 내비게이션 가드가 필요하면 라이브러리 도입 검토

### TypeScript 타입 안전성
- **Zod `z.input` vs `z.infer` drift**: form onSubmit은 Values를 주는데 컴포넌트 `defaultValues` prop이 Input을 기대한다면, Values를 직접 넘기는지 확인. 현재 transform이 "nullable → non-null"만이라 구조적 타이핑으로 통과하지만, 향후 `string → Date` 같은 타입 변환이 transform에 추가되면 런타임 에러 위험. 변환 헬퍼(`valuesToInput()`)로 캡슐화 권장.
- **Discriminated union 사용 여부**: 함수 반환값에 "action별로 같이 다니는 필드"가 있는데 `"create" | "update" | "skip"` 같은 단순 union이면, caller에서 `as number` 단언이 발생하기 쉽다. 반환을 `{ action, campaignId? }` discriminated union으로 바꿔 invariant를 타입 시스템 레벨로 올리는 리팩터 제안.
- **`as unknown as T` 이중 캐스트**: 일반적으로 회피 권장이나 Zod pre/post-transform 왕복 등 type predicate로 표현 불가한 케이스에서 단일 헬퍼로 국소화되어 있으면 허용.

### URL-driven 페이지 렌더 플로우
- **딥링크/새로고침 빈 화면 flash**: `?step=X` 같은 URL query 기반 step 전환 페이지에서, state가 비어있는 채로 딥링크 진입 시 `useEffect` router.replace만으로는 한 프레임 빈 화면이 노출된다. 렌더 시점에 즉시 교정되는 effective 값(`const effectiveStep = ...`)을 계산하고 JSX에서 이를 쓰는지 확인. useEffect는 URL 교정 용도로만.

### API payload 정합성
- **Update payload에서 create-only 필드 명시 제외**: 불변 필드(revenueType 같은)가 `...body` spread에 실려 나가는지 확인. `const { revenueType: _revenueType, ...updateBody } = body` destructure로 명시 제외하는 패턴 권장. 타입 스펙(`Omit<CreateRequest, "revenueType">`)과 payload 구성이 일치해야 함.

### Import 경로
- **절대 경로 우선**: 프로젝트에 path alias(`lib/`, `modules/` 등)가 있으면 상대 경로(`./`, `../`) 대신 절대 경로 사용
- **파일 이동 시 상대 경로 깨짐 주의**: diff에서 파일 이동(`rename`)이 감지되면, 해당 파일 내 상대 경로 import가 전부 유효한지 확인. 이동 후 경로가 바뀌면 즉시 빌드 실패 가능
- **빌드 검증 필수**: 파일 이동이나 import 경로 변경이 있으면 `npm run build`로 로컬 검증 후 push. 테스트만 통과하고 빌드 실패하는 경우 존재 (jest는 모듈 resolution이 관대)

---

## 출력 형식

```
### [언어]: [PASS / N건 발견]
- [CRITICAL/INFO] file:line — 설명
```
해당 언어 파일이 diff에 없으면: `[언어]: 해당 없음 (변경된 파일 없음)`
