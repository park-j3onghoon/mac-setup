# Frontend (JavaScript/TypeScript/Vue/React)

## React
- useEffect 의존성 배열 누락 → Maximum update depth 에러

## 안전성
- sessionStorage/localStorage: SSR 환경에서 접근 가능한지
- API 실패 시 UI 상태: finally 블록에서 서버 실패와 불일치 가능

## 컨벤션
- 한 파일만 변경하면 UI 일관성이 깨지는 경우 별도 이슈 제안
- 새 Vue 컴포넌트는 Composition API (script setup)

## Import 경로
- 절대 경로 우선: 프로젝트에 path alias가 있으면 상대 경로 대신 alias 경로 사용
- 파일 이동 시 상대 경로 깨짐 주의: diff에서 파일 이동(`rename`)이 감지되면, 해당 파일 내 상대 경로 import가 전부 유효한지 확인
