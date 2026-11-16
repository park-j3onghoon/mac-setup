## 의존성 방향

- 순환 의존은 critical로 낸다.
- 모듈끼리는 공유 상태나 전역 변수 대신 함수 인자나 port로 값을 주고받는다.

## 컴포넌트 경계

- 새 서비스·모듈을 만들기 전에 같은 일을 하는 기존 모듈을 찾고, 있으면 거기에 더한다.

## API 계약 설계

- 계획이 proto 파일의 메시지·RPC나 REST 경로·요청·응답 필드를 추가하거나 바꾸면 `~/.claude/lib/api-aip/index.md`를 Read하고 적용/보류 정책 절과, 트랙에 맞는 `~/.claude/lib/api-aip/proto.md`나 `~/.claude/lib/api-aip/rest.md`의 작성 후 체크 절 항목에 계획을 대 본다.
