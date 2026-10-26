#!/usr/bin/env python3
"""편집한 코드 파일이 함수 본문 길이·줄 길이 기준을 넘으면 알린다.

기준 숫자는 ~/.claude/lib/coding/functions.md에서 읽는다. Claude는 PostToolUse 훅으로 stdin JSON을 넘기고,
훅이 없는 에이전트는 `--file 경로`로 직접 실행한다. HEAD와 비교해 아직 커밋하지 않은 줄과,
HEAD에서 기준 이하였다가 넘은 함수만 알린다. 위반이 있으면 stderr로 알리고 2로 끝난다.
"""

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

RULES_PATH = Path.home() / ".claude/lib/coding/functions.md"
BODY_LIMIT_PATTERN = re.compile(r"body passes (\d+) lines")
LINE_LIMIT_PATTERN = re.compile(r"stays within (\d+) characters")
CODE_SUFFIXES = {".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".kt", ".java"}
SKIPPED_PATH_PARTS = ("/migrations/", "/node_modules/", "/vendor/", "/generated/")
SKIPPED_SUFFIXES = ("_pb2.py", "_pb2_grpc.py", ".pb.go")
COMMENT_PREFIXES = ("#", "//", "/*", "*", "<!--")
HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
COMPOUND_STATEMENTS = tuple(
    getattr(ast, name)
    for name in ("If", "For", "AsyncFor", "While", "With", "AsyncWith", "Try", "TryStar", "Match")
    if hasattr(ast, name)
)
RULES_ERROR_EXIT_CODE = 1
VIOLATION_EXIT_CODE = 2


def main():
    args = parse_args()
    if args.check_rules:
        return check_rules()
    path = args.file or read_hook_path()
    if path is None or not is_checked(path):
        return 0
    return check_file(path)


def parse_args():
    parser = argparse.ArgumentParser(description="함수 본문 길이·줄 길이 기준 검사")
    parser.add_argument("--file", type=Path, help="검사할 파일. 없으면 stdin의 훅 입력을 읽는다")
    parser.add_argument("--check-rules", action="store_true", help="functions.md에서 기준을 읽을 수 있는지만 본다")
    return parser.parse_args()


def check_rules():
    """functions.md에서 기준을 읽을 수 있는지 본다. verify.sh가 문장이 바뀌어 훅이 멈추는 것을 잡는 데 쓴다."""
    limits = read_limits()
    if limits is None:
        return RULES_ERROR_EXIT_CODE
    body_limit, line_limit = limits
    print(f"함수 본문 {body_limit}줄, 줄 {line_limit}자")
    return 0


def read_limits():
    """functions.md에서 (함수 본문 줄 수, 줄 글자 수) 기준을 읽는다. 못 읽으면 stderr로 알리고 None을 돌려준다."""
    text = RULES_PATH.read_text(encoding="utf-8") if RULES_PATH.is_file() else ""
    body_match = BODY_LIMIT_PATTERN.search(text)
    line_match = LINE_LIMIT_PATTERN.search(text)
    if body_match is None or line_match is None:
        print(f"{RULES_PATH}에서 길이 기준 문장을 찾지 못했습니다.", file=sys.stderr)
        return None
    return int(body_match.group(1)), int(line_match.group(1))


def read_hook_path():
    """PostToolUse 훅 입력에서 편집한 파일 경로를 읽는다."""
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return None
    file_path = hook_input.get("tool_input", {}).get("file_path")
    return Path(file_path) if file_path else None


def is_checked(path):
    """검사할 코드 파일인지 본다. 생성물·의존성·마이그레이션은 뺀다."""
    text = str(path)
    return (
        path.is_file()
        and path.suffix in CODE_SUFFIXES
        and not text.endswith(SKIPPED_SUFFIXES)
        and not any(part in text for part in SKIPPED_PATH_PARTS)
    )


def check_file(path):
    """파일의 위반을 찾아 stderr로 알리고 종료 코드를 돌려준다."""
    limits = read_limits()
    if limits is None:
        return RULES_ERROR_EXIT_CODE
    body_limit, line_limit = limits
    source = path.read_text(encoding="utf-8", errors="replace")
    repo = find_repo(path)
    head_source = read_head_source(repo, path)
    messages = find_long_lines(path, source, find_changed_lines(repo, path, head_source), line_limit)
    if path.suffix == ".py":
        messages += find_long_functions(source, head_source, body_limit)
    if not messages:
        return 0
    print(f"{path}: ~/.claude/lib/coding/functions.md의 길이 기준을 넘었습니다.", file=sys.stderr)
    for message in messages:
        print(f"- {message}", file=sys.stderr)
    return VIOLATION_EXIT_CODE


def find_repo(path):
    """파일이 든 git 저장소의 최상위 경로. 저장소 밖이면 None."""
    top = run_git(path.resolve().parent, "rev-parse", "--show-toplevel")
    return Path(top.strip()) if top else None


def read_head_source(repo, path):
    """HEAD에 있는 같은 파일의 내용. 저장소 밖이거나 HEAD에 없는 새 파일이면 None."""
    if repo is None:
        return None
    relative = path.resolve().relative_to(repo.resolve())
    return run_git(repo, "show", f"HEAD:{relative.as_posix()}")


def find_changed_lines(repo, path, head_source):
    """HEAD 이후 바뀐 줄 번호 집합. HEAD에 없는 파일이면 None 이고, 모든 줄을 바뀐 줄로 본다."""
    if head_source is None:
        return None
    diff = run_git(repo, "diff", "--no-ext-diff", "--no-color", "-U0", "HEAD", "--", str(path.resolve()))
    changed = set()
    for line in (diff or "").splitlines():
        match = HUNK_PATTERN.match(line)
        if match:
            start = int(match.group(1))
            changed.update(range(start, start + int(match.group(2) or 1)))
    return changed


def run_git(directory, *args):
    """git 명령의 stdout. 실패하면 None."""
    completed = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True)
    return completed.stdout if completed.returncode == 0 else None


def find_long_lines(path, source, changed_lines, limit):
    """바뀐 줄 가운데 기준 글자 수를 넘는 코드 줄. 주석 줄과 여러 줄 문자열의 안쪽 줄은 뺀다."""
    string_lines = find_multiline_string_lines(source) if path.suffix == ".py" else set()
    messages = []
    for number, line in enumerate(source.splitlines(), start=1):
        if changed_lines is not None and number not in changed_lines:
            continue
        if number in string_lines or line.strip().startswith(COMMENT_PREFIXES):
            continue
        if len(line) > limit:
            messages.append(f"{number}행 {len(line)}자(기준 {limit}자): 식을 이름 붙인 변수로 뺀다")
    return messages


def find_multiline_string_lines(source):
    """여러 줄 문자열 토큰의 둘째 줄부터 끝 줄까지의 줄 번호. 토큰으로 못 나누는 코드면 빈 집합."""
    lines = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.STRING and token.end[0] > token.start[0]:
                lines.update(range(token.start[0] + 1, token.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):
        return set()
    return lines


def find_long_functions(source, head_source, limit):
    """이번 변경으로 기준을 넘은 함수. HEAD에서 이미 기준을 넘던 함수는 모양을 유지하므로 뺀다."""
    before = measure_functions(head_source) if head_source is not None else {}
    messages = []
    for name, (line_number, length) in measure_functions(source).items():
        already_long = name in before and before[name][1] > limit
        if length > limit and not already_long:
            messages.append(f"{name}({line_number}행) 본문 {length}줄(기준 {limit}줄): 단계 경계에서 함수로 나눈다")
    return messages


def measure_functions(source):
    """`바깥.이름` 별 (시작 줄, 본문 줄 수). 단순 문장 하나뿐인 본문은 통째로 두므로 빼고, 파싱이 안 되면 빈 dict."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    lines = source.splitlines()
    measured = {}
    for name, node in walk_functions(tree, ""):
        body = strip_docstring(node.body)
        if not body or (len(body) == 1 and not isinstance(body[0], COMPOUND_STATEMENTS)):
            continue
        measured[name] = (node.lineno, count_code_lines(lines[body[0].lineno - 1:node.end_lineno]))
    return measured


def walk_functions(node, prefix):
    """함수 노드를 클래스·바깥 함수 이름을 앞에 붙인 이름과 함께 내놓는다."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = f"{prefix}{child.name}"
            if not isinstance(child, ast.ClassDef):
                yield name, child
            yield from walk_functions(child, f"{name}.")
        else:
            yield from walk_functions(child, prefix)


def strip_docstring(body):
    """본문 첫 문장이 docstring이면 뺀 본문."""
    first = body[0]
    is_constant = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    is_docstring = is_constant and isinstance(first.value.value, str)
    return body[1:] if is_docstring else body


def count_code_lines(lines):
    """빈 줄과 주석만 있는 줄을 뺀 줄 수."""
    return sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))


if __name__ == "__main__":
    sys.exit(main())
