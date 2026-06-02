# 리뷰 스킬 자가 개선 (review Step 9 상세)

리뷰 완료 후, 이번 리뷰에서 내린 결정/발견한 패턴 중 스킬 파일에 없는 내용을 반영한다.

## 9a: 신규 지식 추출
이번 리뷰에서 아래 중 새로운 것을 식별한다:
- ASK 항목에 대한 사용자의 결정
- 반복 발견된 코드 패턴/안티패턴
- 새로 적용된 리뷰 기준

## 9b: 양방향 반영 — 리뷰 스킬 + 코딩 규칙

발견한 신규 지식을 **두 곳에** 반영한다:

**① 리뷰 체크리스트** (다음 리뷰에서 더 잘 잡기 위해):
`review-code.md`, `review-language.md`, `review-team.md`를 읽어 이미 포함된 내용인지 확인.
없는 내용만 적절한 파일에 추가:
- 코드 공통 규칙 → `review-code.md`
- 언어 특화 규칙 → `review-language.md`
- 팀 리뷰어 관점 → `review-team.md`

**② 코딩 규칙** (다음 코드 생성에서 처음부터 잘 쓰기 위해):
리뷰에서 발견한 이슈를 **"이렇게 써라" 형태의 규칙**으로 변환한다.

**③ CLAUDE.md/AGENTS.md 페어 (CRITICAL)**:
글로벌 또는 Buzzvil scope에서 한쪽 파일을 수정했다면 페어 파일도 같이 업데이트한다. 도구별 차이(assignee 등)만 분기 섹션으로 유지. 페어 경로는 SKILL Step 6 참조.

**분류 게이트 (순서대로 적용)**:

1. **범용성 체크** — 2개 이상 언어/프로젝트에서 재발 가능한가?
   - YES → `~/.claude/coding-rules.md` 코어
   - NO → 2번으로
2. **언어/도메인 특화**:
   - Python/Django/Pydantic → `~/.claude/coding-rules-python.md`
   - Vue + Buzzvil 메인 프로젝트(ads-center, dash 등) → `~/.claude/coding-rules-vue.md`
   - React/Vue 공통 프론트 → `~/.claude/coding-rules-frontend.md`
   - 해당 서브 파일이 없으면 신규 생성 가능
3. **니치 도구/프로젝트 전용** (Playwright/BootstrapVue/Testcontainers 등 특정 도구에 국한된 노하우, 또는 특정 프로젝트 구조/컨벤션에만 해당되는 것):
   - 단일 프로젝트에서만 반복 → `project_{name}.md` 메모리
   - 여러 프로젝트에서 그 도구를 공유 → `reference_tool_{tool}.md` 메모리
   - 둘 다 해당 → 둘 다 저장
   - **코어(coding-rules.md)나 언어 서브 파일에 넣지 않는다** — 모든 세션에 로드되어 노이즈가 된다

**예시 언어 중립화**: 원칙이 범용이면 코어의 서술을 언어 중립적으로 다듬는다. 구체 예시(`list[str] | None`, `npm run build` 등)는 해당 서브 파일에 둔다.

**반영 전 확인**: 대상 파일을 먼저 읽어 이미 포함된 내용인지 확인. 중복 금지.

**예시**:
- "함수 내부 import 발견" → `coding-rules.md` 코어 ("import는 파일 최상단에 배치")
- "Pydantic Field validator 테스트 발견" → `coding-rules-python.md` ("프레임워크 빌트인 검증 테스트 금지"의 Python 예시)
- "Playwright strict mode 위반" → `reference_tool_playwright.md` (도구 전용)

각 반영: `[SKILL-UPDATE] {파일}: {추가 내용 1줄 요약}`
신규 지식 없으면 "스킬 업데이트 없음" 출력 후 건너뛴다.

## 9c: coding-rules.md 분할 관리

반영 후 `~/.claude/coding-rules.md`의 줄 수를 `wc -l`로 확인한다.

**200줄 이상**: 가장 큰 섹션을 서브 파일로 분리한다. **내용은 하나도 삭제하지 않는다.**

1. 가장 줄 수가 많은 섹션(예: `## 테스팅`)을 식별
2. 해당 섹션 내용을 `~/.claude/coding-rules-{섹션명}.md`로 이동
3. coding-rules.md에는 1줄 참조로 교체:
   ```
   ## 테스팅 → `~/.claude/coding-rules-testing.md` 참조
   ```
4. 보고: `[SPLIT] 테스팅 섹션({N}줄) → coding-rules-testing.md로 분리`

**코드 작성 시 로드 규칙** (CLAUDE.md에 이미 명시):
- `coding-rules.md` (코어)는 항상 읽는다
- 서브 파일은 현재 작업 언어/도메인에 해당하는 것만 읽는다

review-*.md는 전용 서브에이전트에 로드되므로 줄 수 제한을 적용하지 않는다.
