`~/.claude/lib/coding/architecture.md`와 `~/.claude/lib/coding/design.md`를 Read하고 계획의 층·의존 방향·범위를 그 규칙에 대어 본다. 계획이 도메인 객체나 상태 전이를 만들거나 바꾸면 `~/.claude/lib/coding/domain.md`, 종류·상태 값을 새로 두면 `~/.claude/lib/coding/types.md`도 Read해 대어 본다.

## 의존성 방향

- 순환 의존은 critical 이슈로 낸다.
- 모듈끼리 공유 상태나 전역 변수로 이어지면 이슈로 낸다.

## 컴포넌트 경계

- 계획이 새 서비스·모듈을 만들면 같은 일을 하는 기존 모듈을 찾고, 있으면 거기에 더하는 안을 낸다.

## API 계약 설계

- 계획이 proto 파일의 메시지·RPC나 REST 경로·요청·응답 필드를 추가하거나 바꾸면 `~/.claude/lib/api-aip/index.md`를 Read하고 적용/보류 정책 절과, 트랙에 맞는 `~/.claude/lib/api-aip/proto.md`나 `~/.claude/lib/api-aip/rest.md`의 작성 후 체크 절 항목에 계획을 대 본다.
