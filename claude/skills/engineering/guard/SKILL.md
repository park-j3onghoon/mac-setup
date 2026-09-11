---
name: guard
description: 이번 세션에 안전 모드를 건다. 위험 명령 경고 + 지정 디렉토리 밖 편집 확인. `off` 로 편집 제한을 푼다.
disable-model-invocation: true
argument-hint: "[경로 | off]"
---

# /guard: 안전 모드

프로덕션 작업·라이브 디버깅처럼 되돌리기 어려운 실수가 비싼 세션에 **careful**(위험 명령 경고)과 **freeze**(디렉토리 편집 제한)를 건다. 인자가 `off`면 3번만 수행한다.

## 1. 제한 디렉토리 확정

인자에 경로가 있으면 그대로 쓴다. 경로 없이 `/guard`만 왔을 때만 AskUserQuestion으로 묻는다. "편집을 제한할 디렉토리를 지정해주세요. 이 경로 밖 파일의 Edit/Write는 확인 후 진행합니다." (현재 작업 디렉토리를 후보로 제시하고 직접 입력도 받는다. 여러 개면 목록으로.)

→ 완료: 슬래시로 끝나는 절대경로 목록이 확정됐다.

## 2. 활성화

`~/.claude/lib/guard.md`를 Read하고, 그 문서의 활성화 메시지를 제한 디렉토리로 채워 출력한다. 이후 이 세션의 모든 Bash·Edit·Write에 그 문서의 careful·freeze 규칙을 적용한다.

→ 완료: 메시지를 출력했고 규칙이 적용 중이다.

## 3. 해제: `/guard off`

`~/.claude/lib/guard.md`의 해제 절을 그대로 따른다. freeze만 풀고 careful은 세션 종료까지 유지한다.

→ 완료: 해제 메시지를 출력했고 모든 디렉토리에서 Edit/Write가 열렸다.
