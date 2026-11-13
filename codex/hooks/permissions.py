#!/usr/bin/env python3
"""Use Claude's explicit deny rules and the approved dev metadata exception."""

import fnmatch
import json
import os
from pathlib import Path
import re
import shlex
import sys


HOME_DIR = Path.home()
# [context, namespace] pairs whose secret names may be listed without asking; the private file keeps
# cluster and service names out of this public repo, and without it the hook asks as usual.
SECRET_NAME_SCOPES = HOME_DIR / "git/mac-setup/private/codex/hooks/secret-name-scopes.json"
READ_COMMANDS = {"cat", "head", "tail", "sed", "tee", "cp", "mv", "awk", "grep", "rg", "less", "more"}
PATH_KEYS = {"path", "file_path", "file", "filename", "paths", "files"}
PUSH_OR_PR_CREATE = re.compile(r"\bgit\s+(?:-[^\n]*?\s+)?push\b|\bgh\s+pr\s+create\b")
PUSH_REMINDER = (
    "구현 뒤 첫 push·PR 생성이면 implement-review를 마쳤는지 확인하세요. "
    "리뷰 대응 커밋은 사람 리뷰 요청 전에 implement-review로 다시 봅니다. "
    "인증·권한·시크릿·결제 변경이면 cso도 확인하세요."
)


def settings_files(cwd):
    files = [
        Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
        HOME_DIR / ".claude/settings.json",
    ]
    directories = []
    for directory in (cwd, *cwd.parents):
        directories.append(directory)
        if (directory / ".git").exists() or directory == HOME_DIR:
            break
    for directory in reversed(directories):
        files.extend(directory / ".claude" / name for name in ("settings.json", "settings.local.json"))
    return list(dict.fromkeys(files))


def deny_rules(cwd):
    rules = []
    for source in settings_files(cwd):
        if source.is_file():
            rules.extend(json.loads(source.read_text()).get("permissions", {}).get("deny", []))
    return rules


def mcp_key(name):
    if not name.lower().startswith("mcp__"):
        return None
    parts = name[5:].split("__")
    namespace, action = "__".join(parts[:-1]).lower(), parts[-1]
    for service in ("linear", "slack", "atlassian"):
        if re.search(r"(?:^|[_-])" + service + r"(?:$|[_-])", namespace) or action.lower().startswith(service + "_"):
            while action.lower().startswith(service + "_"):
                action = action[len(service) + 1:]
            action = re.sub(r"[^a-z0-9*?]", "", action.lower())
            if service == "atlassian" and action == "addoreditjiraissuecomment":
                action = "addcommenttojiraissue"
            return service, action
    return None


def shell_tokens(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def input_paths(tool, arguments):
    paths = []

    def visit(value, path_value=False):
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, key in PATH_KEYS)
        elif isinstance(value, list):
            for child in value:
                visit(child, path_value)
        elif path_value and isinstance(value, str):
            paths.append(value)

    visit(arguments)
    command = arguments.get("command", "") if isinstance(arguments, dict) else ""
    if tool == "apply_patch":
        paths.extend(re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", command, re.M))
    if tool == "Bash":
        tokens = shell_tokens(command)
        segment = []
        for index, token in enumerate(tokens):
            if token in {";", "&&", "||", "|", "&", "(", ")"}:
                segment = []
            else:
                segment.append(token)
                if token in {"<", ">", ">>", "&>"} and index + 1 < len(tokens):
                    paths.append(tokens[index + 1])
                if segment and Path(segment[0]).name in READ_COMMANDS and len(segment) > 1 and not token.startswith("-"):
                    paths.append(token)
    return paths


def denied_rule(tool, arguments, cwd, rules):
    key = mcp_key(tool)
    for rule in rules:
        if not isinstance(rule, str):
            continue
        if fnmatch.fnmatchcase(tool, rule):
            return rule
        blocked = mcp_key(rule)
        if key and blocked and key[0] == blocked[0] and fnmatch.fnmatchcase(key[1], blocked[1]):
            return rule
    paths = input_paths(tool, arguments)
    for path in paths:
        expanded = os.path.expandvars(os.path.expanduser(path))
        absolute = os.path.normpath(str(cwd / expanded))
        for rule in rules:
            if not rule.startswith("Read(") or not rule.endswith(")"):
                continue
            pattern = rule[5:-1]
            if pattern.startswith("//"):
                pattern = pattern[1:]
            elif pattern.startswith("~/"):
                pattern = str(HOME_DIR / pattern[2:])
            if fnmatch.fnmatchcase(absolute, pattern):
                return rule
    return None


def secret_name_scopes():
    try:
        return json.loads(SECRET_NAME_SCOPES.read_text())
    except (OSError, ValueError):
        return []


def dev_secret_names(command):
    if any(character in command for character in ("$", "`", "\n", "\r")):
        return False
    tokens = shell_tokens(command)
    if tokens[:2] != ["tsh", "kubectl"]:
        return False
    flags, positional = {}, []
    aliases = {"--context": "context", "--namespace": "namespace", "-n": "namespace", "--output": "output", "-o": "output"}
    index = 2
    while index < len(tokens):
        token = tokens[index]
        option, separator, value = token.partition("=")
        if option in aliases:
            if not separator:
                index += 1
                if index >= len(tokens):
                    return False
                value = tokens[index]
            key = aliases[option]
            if key in flags:
                return False
            flags[key] = value
        elif token.startswith("-") or token in {";", "&&", "||", "|", "&", "(", ")", "<", ">", ">>", "&>"}:
            return False
        else:
            positional.append(token)
        index += 1
    scope = {"context": flags.get("context"), "namespace": flags.get("namespace"), "output": "name"}
    return positional == ["get", "secrets"] and flags == scope and [scope["context"], scope["namespace"]] in secret_name_scopes()


def decision(payload):
    tool = payload.get("tool_name", "")
    arguments = payload.get("tool_input", {})
    if not isinstance(arguments, dict):
        return None
    event = payload.get("hook_event_name", "PreToolUse")
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    blocked = denied_rule(tool, arguments, cwd, deny_rules(cwd))
    if blocked:
        reason = "Claude와 공유하는 차단 규칙: " + blocked
        if event == "PermissionRequest":
            return {"hookSpecificOutput": {"hookEventName": event, "decision": {"behavior": "deny", "message": reason}}}
        return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": reason}}
    if event == "PermissionRequest" and tool == "Bash" and dev_secret_names(arguments.get("command", "")):
        return {"hookSpecificOutput": {"hookEventName": event, "decision": {"behavior": "allow"}}}
    if event == "PreToolUse" and tool == "Bash" and PUSH_OR_PR_CREATE.search(arguments.get("command", "")):
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": PUSH_REMINDER}}
    return None


if __name__ == "__main__":
    try:
        result = decision(json.load(sys.stdin))
        if result:
            print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, TypeError) as error:
        print("Claude permission policy could not be checked: " + str(error), file=sys.stderr)
        sys.exit(2)
