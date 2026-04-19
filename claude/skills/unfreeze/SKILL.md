---
name: unfreeze
version: 1.0.0
description: guard/freeze로 설정된 편집 제한을 해제한다. "unfreeze", "편집 제한 해제" 등으로 트리거.
allowed-tools:
  - Bash
  - Read
---

# /unfreeze — 편집 제한 해제

`/guard`로 설정된 디렉토리 편집 제한을 해제한다.
모든 디렉토리에 대한 Edit/Write가 다시 허용된다.

위험 명령어 경고(careful)는 유지된다. 세션 종료 시 전체 해제.

실행 시: "편집 제한이 해제되었습니다. 모든 디렉토리에서 편집 가능합니다."
