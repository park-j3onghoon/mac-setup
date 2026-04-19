# 수동 셋업 노트

`install.sh`로 자동화되지 않는 부분을 모아둔 체크리스트.

## 1. Claude / Codex 로그인

```bash
claude login
codex login
```

## 2. 앱 설치 (Brewfile에 포함되지 않는 경우만 수동)

Brewfile로 대부분 설치되지만, GUI 앱 중 App Store 전용이거나 cask 미존재인 것은 수동:

- Scroll Reverser
- Maccy (클립보드 히스토리)
- Karabiner-Elements (키 리맵)
- Rectangle (윈도우 스냅)
- Obsidian
- KakaoTalk

## 3. macOS 시스템 설정

### 키보드 단축키
- **시스템 설정 → 키보드 → 키보드 단축키 → 앱 단축키**
- "게임 오버레이 표시"의 `Command+Esc` 제거 (IDE 포커스와 충돌)

## 4. IDE 단축키 (PyCharm / IntelliJ)

### Window → Active Tool Window
- Hide All Tool Windows: `Cmd+Esc`

### Editor Actions
- Focus Editor: `Cmd+5`

### Tool Windows
- Commit: `Cmd+2`
- Python Console: `Cmd+3`
- Terminal: `Cmd+4`

## 5. 시크릿/개인 파일 (수동 생성)

레포에는 올리지 않는 파일들. 필요 시 직접 만든다:

```bash
# Linear API 키 (daily-todo, save-document 등 옵시디언 연동 스킬 사용 시)
# 레포에는 이 스킬들을 포함하지 않았으니, 필요하면 개인 머신에만 추가.
# ~/.claude/linear_api_key
# ~/.claude/redash_config.json
```

## 6. 플러그인 설치 (Claude Code)

`claude` 실행 후:

```
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/plugin install ralph-loop  # 선택
/plugin install everything-claude-code  # 선택
/plugin install slack  # 선택
/plugin install sentry  # 선택
/plugin install figma  # 선택
/plugin install pyright-lsp  # 선택
/reload-plugins
```

`~/.claude/settings.json`의 `enabledPlugins` 필드에 플러그인이 미리 명시되어 있으므로, 설치만 하면 자동 활성화된다.
