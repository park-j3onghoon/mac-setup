## React
- `useEffect`에는 의존성 배열을 넣는다(빠졌을 때 증상: `Maximum update depth exceeded`).
- 폼 값은 폼 라이브러리 밖 `useState`에 따로 두는 대신 폼 값에서 읽는다.
- 폼 훅은 `defaultValues`와 `onSubmit`을 옵션으로 받아 `useAppForm(...)` 결과를 바로 돌려준다.
- 폼 값 일부만 그리는 곳은 `useStore`로 폼 상태 전체를 구독하는 대신 `form.Subscribe`로 그 값만 구독한다.

## Vue
- 새 Vue 컴포넌트는 Composition API(`<script setup>`)로 쓴다.
- `this.$nextTick` 대신 `import { nextTick } from "vue"`로 가져와 쓴다.
- 여러 컴포넌트에 같은 반응형 로직이 있으면 composable(`use*` 함수)로 뽑는다.

## 안전성
- SSR에서도 도는 코드는 `sessionStorage`·`localStorage`를 브라우저에서만 읽는다(`typeof window` 검사).
- API 호출 결과로 바꾸는 UI 상태는 `finally` 대신 성공·실패 분기에서 각각 정한다.
- `localStorage`·`sessionStorage`는 키 문자열로 바로 읽고 쓰는 대신 키·스키마·기본값을 묶은 항목을 거쳐 읽고, 읽을 때 스키마로 검증한다.
- 같은 자원에 쓰는 요청(upsert)은 `Promise.all`로 동시에 보내는 대신 차례로 보내거나 한 번에 묶어 보낸다.
- 요소는 라이브러리 내부 DOM 속성(`[data-radix-portal]`) 대신 직접 단 ref나 라이브러리 공개 API로 찾는다.

## 값 검사
- 0·빈 문자열이 올바른 값인 변수는 `a && b`·`a || 기본값` 대신 `??`나 null 검사로 다룬다.
- 비교는 `==`·`!=` 대신 `===`·`!==`로 하고, null·undefined 검사는 프로젝트가 쓰는 검사 함수 하나로 한다.
- `.filter(Boolean)`은 빈 값이 섞일 수 있는 배열에만 쓴다.

## 타입
- 타입은 `as` 캐스팅 대신 type predicate(`.filter((v): v is string => Boolean(v))`)로 좁힌다.
- API·도메인의 값 목록은 string union 대신 `enum`으로 쓰고, 이름은 PascalCase에 `Enum`을 붙인다(`OrderStatusEnum`).
- 키·값 객체 타입은 인덱스 시그니처(`{ [key: string]: T }`) 대신 `Record<K, T>`로 쓴다.
- 한 타입 안의 필드 이름은 camelCase와 snake_case 가운데 하나로 쓴다.
- 요청·응답 타입에서 화면이 쓰지 않는 필드는 지운다.

## 컨벤션
- 같은 UI가 여러 파일에 있는데 한 파일만 바꾸면, 나머지 파일을 맞추는 일을 별도 이슈로 만든다.
- 한 화면의 필터는 일부만 URL 쿼리에 두는 대신 모두 URL에 둔다.
- 목 데이터는 프로젝트가 정한 목 파일 한 곳에 둔다.
- 받은 `onError`를 그대로 부르기만 하는 콜백을 따로 만드는 대신 `...options`로 넘긴다.
- `console.log`는 머지 전에 지운다.

## 화면
- 컴포넌트 핸들러(열기, 클릭)에 있는 금액 계산·판정 같은 업무 로직은 서버로 옮긴다.
- 자식에게 props를 그대로 넘기기만 하는 wrapper 컴포넌트는 부르는 쪽에 인라인한다.
- 작성 중인 화면을 떠날 때 뜨는 확인 창은 다른 화면이 쓰는 확인 함수와 버튼 구성(취소 포함)을 따른다.
- 새로 쓴 고정 너비(px)가 320px 너비 화면에서 넘치면 rem이나 유동 너비로 바꾼다.
- PR 본문에 디자인 시안이 있으면 아이콘, 메뉴 순서, hover 동작을 시안대로 맞추고, 시안에 없는 동작은 뺀다.
- `wheel`·`scroll` 이벤트마다 스타일을 바꾸는 처리(blur 적용)에는 throttle을 건다.

## Import 경로
- 프로젝트에 path alias가 있으면 import는 상대 경로 대신 alias 경로로 쓴다.
- 파일을 옮기면 그 파일 안의 상대 경로 import를 모두 새 위치에 맞게 고친다.
