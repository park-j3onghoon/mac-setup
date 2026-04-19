# Vue + Buzzvil 메인 프로젝트 코딩 규칙

`coding-rules.md` 코어 + `coding-rules-frontend.md` 와 함께 적용한다.
대상: Buzzvil ads-center, dash 등 Vue 3 기반 모듈.

---

## 컴포넌트 / 반응성

- **새 Vue 컴포넌트는 Composition API (`<script setup>`)**.
- **`watch` handler에 구현 디테일 인라인 금지**. named method로 추출.
- **`form.Field`로 감싸야 리렌더링 구독**. `form.state.values.foo` 직접 접근은 UI 업데이트 안 됨. boolean 토글 등 form 상태 기반 조건부 렌더링은 반드시 `<form.Field name="foo">` 로 래핑.

## 스키마 / 검증

- **Zod 문자열 스키마는 `stringSchema()` 사용**. `z.string().min().max().refine()` 수동 체이닝 금지. `@/schemas/common`의 공유 유틸(`stringSchema`, `urlSchema`, `emailSchema`)을 우선 사용.

## UI 컴포넌트

- **`v-b-popover`에 `.html` modifier 전역 적용 금지**. `{ content, html: true }` 객체 형태 사용.
- **아이콘은 color prop 포함**. `color = "currentColor"` 기본값 + `fill={color}` 패턴. 하드코딩 `fill="currentColor"` 금지.

## 라우팅

- **라우트는 `routes` 객체 사용**. `router.push("/ads/display")` 대신 `router.push(routes.ads.display.path)`. 하드코딩 경로 금지.

## Enum 네이밍 (display 모듈)

- **모델 Enum: Type 접미어 없음**. 도메인 Enum: Type 접미어 있음.

## 공유 파일 범위

- **`src/components/shared/` 하위 hooks/helpers도 공통 컴포넌트**. 무단 수정 금지. 해당 파일을 건드려야 하면 사용자 동의 후 진행.
