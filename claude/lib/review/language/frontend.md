## React
- useEffect 의존성 배열 누락 → Maximum update depth 에러
- 폼 값을 폼 라이브러리 밖의 `useState`에 따로 들고 있으면 지적하고 폼 값에서 읽게 한다.
- 폼 훅은 `defaultValues`와 `onSubmit`을 옵션으로 받아 `useAppForm(...)` 결과를 바로 돌려주게 한다.
- 폼 값 일부만 그리는 곳에서 `useStore`로 폼 상태 전체를 구독하면 지적하고 `form.Subscribe`로 그 값만 구독하게 한다.

## Vue
- 새 Vue 컴포넌트는 Composition API (script setup)
- `this.$nextTick` 대신 `import { nextTick } from "vue"`로 가져와 쓰게 한다.
- 여러 컴포넌트에 같은 반응형 로직이 있으면 composable(`use*` 함수)로 뽑게 한다.

## 안전성
- sessionStorage/localStorage: SSR 환경에서 접근 가능한지
- API 실패 시 UI 상태: finally 블록에서 서버 실패와 불일치 가능
- `localStorage`·`sessionStorage`를 키 문자열로 바로 읽고 쓰면 지적하고, 키·스키마·기본값을 묶은 항목을 거쳐 읽을 때 스키마로 검증하게 한다.
- 같은 자원에 쓰는 요청(upsert)을 `Promise.all`로 동시에 보내면 지적하고, 차례로 보내거나 한 번에 묶어 보내게 한다.
- 라이브러리 내부 DOM 속성(`[data-radix-portal]`)으로 요소를 찾으면 지적한다.

## 값 검사
- `a && b`나 `a || 기본값`이 0·빈 문자열 같은 올바른 값을 거르면 지적하고 `??`나 null 검사로 바꾸게 한다.
- `==`·`!=` 비교는 지적하고 `===`·`!==`로 바꾸게 한다. null·undefined 검사는 프로젝트가 쓰는 검사 함수 하나로 하게 한다.
- 값이 빌 수 없는 배열에 `.filter(Boolean)`을 붙이면 지적한다.

## 타입
- `as` 캐스팅으로 타입을 좁히면 지적하고 type predicate(`.filter((v): v is string => Boolean(v))`)를 쓰게 한다.
- API·도메인의 값 목록은 string union 대신 `enum`으로 쓰고, 이름은 PascalCase에 `Enum`을 붙이게 한다(`OrderStatusEnum`).
- 키·값 객체 타입은 인덱스 시그니처(`{ [key: string]: T }`) 대신 `Record<K, T>`로 쓰게 한다.
- 한 타입 안에서 camelCase와 snake_case 필드 이름이 섞이면 지적한다.
- 요청·응답 타입에 화면이 쓰지 않는 필드가 있으면 지적하고 지우게 한다.

## 컨벤션
- 한 파일만 변경하면 UI 일관성이 깨지는 경우 별도 이슈 제안
- 한 화면의 필터 가운데 일부만 URL 쿼리에 두면 지적하고 그 화면의 필터를 모두 URL에 두게 한다.
- 목 데이터는 프로젝트가 정한 목 파일 한 곳에 두게 한다.
- 받은 `onError`를 그대로 부르기만 하는 콜백을 따로 만들면 지적하고 `...options`로 넘기게 한다.
- `console.log`가 남아 있으면 지적한다.

## 화면
- 컴포넌트 핸들러(열기, 클릭)에 금액 계산·판정 같은 업무 로직이 있으면 지적하고 서버로 옮기게 한다.
- 자식에게 props를 그대로 넘기기만 하는 wrapper 컴포넌트는 지적하고 부르는 쪽에 인라인하게 한다.
- 작성 중인 화면을 떠날 때 뜨는 확인 창은 다른 화면이 쓰는 확인 함수와 버튼 구성(취소 포함)을 따르게 한다.
- 고정 너비(px)를 새로 쓰면 320px 너비 화면에서 넘치는지 보고, 넘치면 지적하고 rem이나 유동 너비로 바꾸게 한다.
- PR 본문에 디자인 시안이 있으면 아이콘, 메뉴 순서, hover 동작이 시안과 같은지 보고, 시안에 없는 동작을 더했으면 지적한다.
- `wheel`·`scroll` 이벤트마다 스타일을 바꾸는 처리(blur 적용)를 하면 지적하고 throttle을 걸게 한다.

## Import 경로
- 절대 경로 우선: 프로젝트에 path alias가 있으면 상대 경로 대신 alias 경로 사용
- 파일 이동 시 상대 경로 깨짐 주의: diff에서 파일 이동(`rename`)이 감지되면, 해당 파일 내 상대 경로 import가 전부 유효한지 확인
