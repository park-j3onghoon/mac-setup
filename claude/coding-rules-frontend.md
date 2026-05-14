# 프론트엔드 공통 코딩 규칙 (React / Vue)

`coding-rules.md` 코어와 함께 적용한다.
Vue + Buzzvil 메인 프로젝트는 `coding-rules-vue.md` 도 함께 읽는다.

---

## 테스트 연동

- **테스트 전용 속성(`data-testid` 등)은 실제 참조하는 테스트와 같은 PR에 묶는다**. 추가만 하고 테스트에서 쿼리하지 않으면 YAGNI 위반. 해당 PR에서 최소 한 곳이라도 `getByTestId` 등으로 사용해 정당화하거나, 추가 자체를 미룬다.

## URL Query를 single source of truth로 쓰는 페이지

- **쿼리 없는 bare URL 진입(`/path`)이 허용되는지 반드시 확인한다**. 북마크/새로고침/외부 링크 진입 시 쿼리가 없는데 `isValid=false`로 에러 화면을 띄우면 사용자 경험 regression. 기본 진입점을 쿼리 없는 상태에서도 resolve할 수 있도록 훅/파라미터 resolver에서 기본값을 둔다.
- **예시**: `const step = isValidStep(params.step) ? params.step : "settings";` — settings 단계를 기본 진입점으로.
- 체크 포인트: URL-driven 페이지로 전환하는 refactor에서 기존 `useState("...")` 같은 초깃값 동작을 훅 단에서 대체 보장.

## 배열 set equality 유틸

- **원소 유일성 전제로 작성한 set equality 유틸(`hasSameMembers` 등)은 함수 주석에 "입력 배열에 중복이 없다"를 명시한다**. 중복 허용 context에서 재사용하면 `[A,A,B]` vs `[A,B,B]`가 같다고 판정되는 false match 버그가 생긴다.
- 중복 허용 비교가 필요하면 multiset 비교(정렬 후 비교 또는 count-map)로 작성한다.

## async 이벤트 핸들러 내 throw는 unhandled rejection이 된다

- **Promise를 반환하는 onClick/핸들러 체인에서 throw하면 중간 wrapper가 await하지 않는 한 unhandled promise rejection으로 떠돈다**. React 이벤트 핸들러(`onClick`), 오버레이 라이브러리의 `onConfirm`, 비슷하게 "콜백을 호출만 하고 반환값은 버리는" 구조에서 재발한다. toast로 실패를 안내했더라도 rethrow 자체가 모니터링 노이즈와 global error handler 부작용을 만든다.
- **확인 전**: 체인의 각 레이어(`handleConfirm` → `Modal.BottomSheet onClick wrapper` → React onClick)에서 Promise를 `await`/`.catch`로 받는 곳이 있는지 Grep으로 추적. 없으면 throw 금지, catch에서 삼키고 toast 등 사용자 안내만 수행한다.
- **모달 유지/닫힘 제어 목적의 throw**는 쓰지 않는다. 모달 자동 닫힘을 허용하고 재시도 경로는 버튼 재진입으로 유도 (livecommerce 팀 관행과 일치).
- 기존 규칙(Mutation은 onError 콜백에서 처리)과 상충하지 않도록 — 확인 모달 분기 로직에 try/catch가 필요한 경우 `catch {}` (binding 생략) 허용.

## 프론트엔드 toast / 카피 문구

- **사용자 노출 카피는 전역 grep으로 관행을 교차 검증한 뒤 통일한다**. 예: "다시 시도해 주세요"(띄어쓰기) vs "다시 시도해주세요"(붙여쓰기) — 단일 모듈만 참고 말고 2~3개 모듈에서 빈도 확인.
- **Toast는 단일 문장 구조 관행 따르기**. `title="~에 실패했어요"` + `description="잠시 후 다시 시도해주세요"` 패턴이 지배적. description에 2문장 몰아넣지 말 것. 부가 정보(이미 저장됐음 등)는 한 문장에 자연스럽게 녹여 넣는다.
- **유저 멘탈 모델은 저장 관점 단일 화**. create/update가 내부 최적화 분기라도 유저에게는 "저장" 단일 개념. 실패 toast 문구에서 "수정 실패" 등 내부 분기를 드러내지 말 것.

## Zod 스키마 Input/Values 분리

- **`z.input`(transform 전)과 `z.infer`(transform 후)는 다른 타입이다**. form의 `defaultValues` prop은 Input 타입, onSubmit의 value는 Values 타입. 상태(state)에 Values를 저장해두고 재진입 시 defaultValues 자리에 넘기면 Values → Input 방향이 된다.
- **현재 transform이 "nullable → non-null + 검증"만이면 구조적 타이핑으로 지금은 통과**. 단, 향후 transform에 타입 변환(`string → Date` 등)이 추가되면 런타임 에러.
- **Values → Input 전달은 변환 헬퍼로 캡슐화한다**. 헬퍼를 한 지점에 두면 drift를 TS 컴파일이 그 헬퍼에서 잡아준다.
  ```ts
  function valuesToSettingsInput(v: Values): Partial<Input> {
    return v as unknown as Partial<Input>;
  }
  ```
- **이중 캐스트 `as unknown as T` 허용 기준**: 기본적으로 회피. 단 Zod pre/post-transform 왕복처럼 type predicate로 표현 불가한 경우, 헬퍼 함수로 국소화된 단일 지점에서만 허용.

## Discriminated union으로 caller 타입 단언 제거

- **함수 반환값에 "action별로 같이 다니는 필드"가 있으면 discriminated union으로 표현한다**. caller에서 `as number` 단언을 쓰지 않아도 되게 invariant를 타입 시스템 레벨로 올린다.
  ```ts
  // Before
  type NextAction = "create" | "update" | "skip";
  // caller: updateCampaign({ id: campaignId as number, ... })  ← 단언 필요
  
  // After
  type NextAction =
    | { action: "create" }
    | { action: "update"; campaignId: number }
    | { action: "skip"; campaignId: number };
  // caller: if (a.action === "update") updateCampaign({ id: a.campaignId, ... })  ← 단언 없이
  ```

## Update payload에서 변경 불가 필드 destructure 제외

- **create-only 필드(불변 필드)는 update payload에서 명시적으로 뺀다**. spread만 쓰면 TS excess property check가 안 걸려 잘못된 필드가 실려나간다.
  ```ts
  const { revenueType: _revenueType, ...updateBody } = body;
  await mutate({ id, ...updateBody });
  ```
- 타입 스펙(`UpdateRequest = Omit<CreateRequest, "revenueType"> & { id }`)과 payload 구성이 일치하도록 구현.

## 렌더 시점 교정 + URL 지연 교정 이중 메커니즘

- **URL Query 기반 step/탭 페이지에서 딥링크/새로고침 진입 시 `useEffect` router.replace만으로는 한 프레임 빈 화면이 보인다**. 렌더 첫 프레임에 아무 섹션도 매칭되지 않기 때문.
- **해결**: 렌더 시점에 즉시 교정된 effective 값을 계산하고, `useEffect`는 URL(주소창) 교정 용도로 따로 둔다.
  ```tsx
  const effectiveStep =
    step === "creative" && state === null ? "settings" : step;

  useEffect(() => {
    if (step === "creative" && state === null) {
      router.replace(settingsUrl);
    }
  }, [step, state, router]);

  // JSX에서 step 대신 effectiveStep을 사용
  ```
- 두 메커니즘의 역할 분리(렌더 즉시 교정 vs URL 지연 교정)를 주석으로 명시한다.
