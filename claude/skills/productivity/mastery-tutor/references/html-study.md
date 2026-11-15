# HTML 공부방

## 호출

학습을 HTML로 넘길 때는 공용 저장소에 체크포인트를 먼저 저장한다. 이미 있는 다른 회차들은 읽기만 한다. HTML이 진행하는 회차는 서버가 holder `web:study`로 저장한다.

```sh
python3 ~/.claude/skills/mastery-tutor/scripts/study_server.py start
python3 ~/.claude/skills/mastery-tutor/scripts/study_server.py status
```

`start`가 반환한 주소에 `#회차-id`를 붙이면 그 공부가 바로 선택된다. 주소를 사용자에게 제공하며 앱 활성화·포커스 전환은 하지 않는다. `--root` 또는 `MASTERY_TUTOR_HOME`이 지정되면 같은 저장소를 사용한다. 기본 포트는 8766이며 충돌할 때 `--port 0`으로 빈 포트를 고를 수 있다.

화면 원본은 `assets/study.html`, `assets/study.css`, `assets/study.js`, `assets/study_markdown.js`, `assets/study_images.js`다. 실행 시 `assets/vendor/`의 고정 버전 라이브러리와 CSS·JavaScript를 합친 HTML 하나를 `{학습 저장소}/web/index.html`에 만든다. 기록 읽기·저장·채점에는 로컬 실행기가 필요하므로 반환된 HTTP 주소로 접속한다. 외부 호스팅이나 공개 배포를 하지 않는다.

## 화면과 진행

- 답안과 일반 입력에 스크린샷 붙여넣기 또는 `이미지 첨부`를 지원한다. 전송 전 미리보기·삭제가 가능하고, 이미지만 제출할 수도 있다. 한 요청에 PNG·JPEG·WebP 최대 3개, 이미지당 6MB이며 파일은 로컬 요청 폴더에 보존한다. 조회는 공부방 토큰 인증을 거친다. 선택한 Codex에는 `--image`, Claude에는 `stream-json`의 실제 이미지 콘텐츠를 전달하고, 아직 채점하지 않은 이미지 근거도 함께 제공한다. 이미지 내용도 학습 자료로만 취급한다.
- 설명은 로컬에 포함한 Marked·DOMPurify로 Markdown 표·제목·목록·인용·코드 블록을 표시한다. 제출한 원답은 문법을 변환하지 않고 그대로 보인다. 원시 HTML은 글자로 표시하고 실행하지 않는다. 브라우저에서 외부 라이브러리를 다운로드하지 않는다.
- 필요한 그림은 `html-diagram height=320` 코드 블록으로 전달한다. 높이는 160~720px, 기본 320px이다. 정적 HTML·인라인 CSS·SVG와 읽기 쉬운 한글을 사용한다. 블록이 닫힌 뒤 정화하여 빈 `sandbox`의 iframe에 표시한다. 그림 안의 스크립트·폼·외부 리소스·탐색은 허용하지 않으며 학습 페이지·학습 데이터에 접근할 수 없다. 일반 `html` 블록은 코드로 표시한다.
- 화면의 `보낼 AI`에서 Codex 또는 Claude를 선택한다. 답 제출·질문·이어하기·재시도는 선택한 CLI로 보내며, 기존 로그인 계정의 사용량을 사용한다. API 키를 HTML에 넣지 않는다. Codex는 읽기 전용·일회성, Claude는 `--safe-mode`와 빈 도구 목록으로 실행한다. 둘 다 외부 MCP 연결을 로드하지 않는다.
- 대화에서 같은 회차를 이어갈 때 state의 `pending_concept_card_updates`를 최신 회차 근거로 개념 카드에 병합한다.

다른 대화에서 HTML 소유의 active 회차를 가져올 때도 learning-records.md의 소유권 확인을 따른다. 단순 기록 조회는 승인이나 넘겨받기가 필요 없다.

## 확인과 장애

`status`와 `/health`로 연결을 확인한다. 실행 로그는 `web/server.log`, 채점 로그는 요청 폴더의 `runner.log`다. 로컬 포트 열기가 샌드박스에 막히면 필요한 범위의 실행 권한으로 다시 실행한다. Chrome 검증은 등록된 공유 연결을 사용하고 `background: true`와 명시적 `pageId`를 지킨다.

실패한 요청의 원답·실행 결과와 `runner.log`는 요청 폴더 `web/jobs/{요청-id}/`에 남는다. 실제 사용자의 답·통과 증거를 테스트 데이터로 만들거나 수정하지 않는다.
