#!/usr/bin/env python3
"""Launch Codex with company-first, 90%-threshold account selection."""

from contextlib import closing
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from idle import start_proxy
from policy import UsageUnavailable, choose
from rpc import version_from_initialize
from runtime import raise_file_limit, server_package_cache
from usage import read_usage, read_snapshot
from state import RUNTIME, load, record
from unix_ws import UnixWebSocket


BINARY = Path("/opt/homebrew/bin/codex")
PROFILES = {
    "company": Path.home() / ".codex-work",
    "personal": Path.home() / ".codex",
}
MANAGEMENT = {
    "login", "logout", "mcp", "plugin", "app-server", "remote-control",
    "app", "completion", "update", "doctor", "sandbox", "debug", "features",
    "apply", "exec-server", "migrate-rollouts", "migrate-nfs-db", "help",
    "queue", "archive", "delete", "unarchive",
}


def show_status():
    from service import running
    state = load()
    is_running = running(state)
    if is_running:
        state = dict(state)
    else:
        state["active"] = None
        state['errors'] = {}
        for name, home in PROFILES.items():
            try:
                current = read_snapshot(BINARY, home)
            except (UsageUnavailable, OSError) as error:
                state['errors'][name] = type(error).__name__
                print(f'{name}: usage unavailable')
                continue
            state.setdefault("accounts", {})[name] = record(
                state.get("accounts", {}).get(name), current,
            )
        state["updated_at"] = time.time()
    for name, value in state.get("accounts", {}).items():
        reset_labels = []
        for window in value.get("windows", {}).values():
            if window.get("resets_at"):
                reset = datetime.fromtimestamp(window["resets_at"]).astimezone()
                reset_labels.append(reset.strftime("%Y-%m-%d %H:%M %Z"))
        reset_text = ", ".join(reset_labels) or "unknown"
        checked = datetime.fromtimestamp(value["observed_at"]).astimezone()
        print(f"{name}: {value['used_percent']:g}% used; resets {reset_text}; "
              f"checked {checked:%m-%d %H:%M:%S %Z}")
        confirmed = [window.get("last_reset_confirmed_at")
                     for window in value.get("windows", {}).values()
                     if window.get("last_reset_confirmed_at")]
        if confirmed:
            print("  last reset confirmed: " + datetime.fromtimestamp(max(confirmed)).astimezone().isoformat())
    selected = state.get("active") or "unknown"
    if not is_running:
        try:
            selected = choose({name: value['used_percent'] for name, value in state.get('accounts', {}).items()
                               if name not in state['errors']}, preferred=state.get('preferred', 'company'))
        except UsageUnavailable:
            selected = 'unknown'
    print(f"selected: {selected}; service: {state.get('status', 'not started')}")
    if is_running and state.get("runtime_version"):
        print(f"shared server: {state['runtime_version']}")
        if state.get("upgrade_target"):
            print(f"update to {state['upgrade_target']}: {state.get('upgrade_error') or state.get('upgrade_status')}")
    if state.get("desired") and state["desired"] != state.get("active"):
        print(f"waiting for active work to finish: {state['desired']}")
    if state.get("errors") or state.get("runtime_error") or state.get("account_error"):
        print("Some checks failed; recorded usage may be stale.")
    return 0


def command_name(arguments):
    value_options = {"-c", "--config", "-m", "--model", "-p", "--profile",
                     "-s", "--sandbox", "-a", "--ask-for-approval", "-C", "--cd",
                     "--add-dir", "-i", "--image", "--remote-auth-token-env",
                     "--local-provider", "--enable", "--disable"}
    skip = False
    for argument in arguments:
        if skip:
            skip = False
        elif argument == "--":
            return None
        elif argument in value_options:
            skip = True
        elif not argument.startswith("-"):
            return argument
    return None


def interactive(arguments):
    # Known non-interactive subcommands keep the existing per-profile behavior.
    noninteractive = MANAGEMENT | {"exec", "e", "review", "cloud"}
    return command_name(arguments) not in noninteractive


def server_version(socket_path):
    # 인증 갱신과 승인 요청은 기존 연결이 처리하므로 버전 조회는 initialize 응답만 읽는다.
    with closing(UnixWebSocket(socket_path, deadline=time.monotonic() + 2)) as connection:
        connection.send(b'{"id":1,"method":"initialize","params":'
                        b'{"clientInfo":{"name":"codex-version-check","version":"1"}}}')
        for raw in connection.messages():
            message = json.loads(raw)
            if not isinstance(message, dict) or message.get("id") != 1 or "method" in message:
                continue
            return version_from_initialize(message.get("result"))


def terminal_command(socket_path):
    installed = BINARY.resolve(strict=True)
    command = [str(installed)]
    cache = server_package_cache(installed, RUNTIME)
    if cache is None:
        return command
    try:
        version = server_version(socket_path)
    except (OSError, EOFError, ValueError):
        return command
    if version and version != installed.parent.parent.name:
        for packages in (cache, installed.parents[2]):
            cli = packages / version / "bin" / "codex"
            if cli.is_file() and os.access(cli, os.X_OK):
                # Homebrew로 업데이트해도 이 서버에 맞춰 고른 CLI의 버전은 바뀌지 않는다.
                return [str(cli), "-c", "check_for_update_on_startup=false"]
    return command


def launch_automatic(arguments):
    from service import ensure
    from runtime import SOCKET
    state = ensure()
    print(f"[codex] {state['active']}; automatic switching enabled (90%, idle turns)",
          file=sys.stderr)
    environment = dict(os.environ, CODEX_HOME=str(RUNTIME))
    # A remote terminal sends no directory unless told, and the thread then runs in the
    # server's own directory (measured on 0.168.0, 2026-11-13).
    directory = [] if any(arg.startswith(("-C", "--cd")) for arg in arguments) else ["-C", os.getcwd()]
    try:
        idle_seconds = float(os.environ.get("CODEX_IDLE_SECONDS", "900"))
    except ValueError as error:
        raise UsageUnavailable("CODEX_IDLE_SECONDS must be a number") from error
    command = terminal_command(SOCKET)
    endpoint = start_proxy(SOCKET, idle_seconds) if idle_seconds > 0 else SOCKET
    os.execve(command[0], [*command, "--remote", "unix://" + str(endpoint), *directory,
                           *cmux_tab_overrides(), *arguments], environment)


def cmux_tab_overrides():
    # The server runs this terminal's shell commands, so they cannot inherit its cmux tab the way a
    # local terminal's commands do; pass the tab and this process (execve keeps the pid) so they can
    # act on their own terminal. cmux refuses processes it did not start unless they carry the tab's
    # socket capability (measured 2026-11-16). A remote terminal sends shell_environment_policy with
    # thread/start and resume (0.169.0).
    if not os.environ.get("CMUX_SURFACE_ID"):
        return []
    values = {name: os.environ[name] for name in ("CMUX_SURFACE_ID", "CMUX_SOCKET_CAPABILITY")
              if name in os.environ}
    values["CMUX_CODEX_PID"] = str(os.getpid())
    return [part for name, value in values.items()
            for part in ("-c", f'shell_environment_policy.set.{name}="{value}"')]


def report_runtime_update():
    from service import running
    installed = BINARY.resolve().parent.parent.name
    deadline = time.monotonic() + 35
    while True:
        state = load()
        if state.get("status") == "failed" or state.get("upgrade_error"):
            print("[codex] Shared server update failed. Check codex --account-status.", file=sys.stderr)
            return False
        if not running(state):
            print(f"[codex] Next automatic server will start from the installed release ({installed}).")
            return True
        if state.get("runtime_version") == installed and state.get("active"):
            print(f"[codex] Shared server is using {installed}.")
            return True
        if state.get("upgrade_target") == installed and state.get("upgrade_status") == "waiting_for_idle":
            print(f"[codex] Installed {installed}; the switcher will replace {state['runtime_version']} "
                  "when active work finishes. Check codex --account-status.")
            return True
        if time.monotonic() >= deadline:
            print("[codex] Server update is unconfirmed. Check codex --account-status.", file=sys.stderr)
            return False
        time.sleep(0.5)


def update_clis():
    failed = False
    for binary in (BINARY, Path.home() / ".local/bin/claude"):
        try:
            result = subprocess.run([str(binary), "update"])
        except OSError as error:
            print(f"[update] {binary}: {error}", file=sys.stderr)
            failed = True
        else:
            if result.returncode:
                print(f"[update] {binary.name} update exited {result.returncode}", file=sys.stderr)
                failed = True
    confirmed = report_runtime_update()
    return int(failed or not confirmed)


def main(arguments):
    raise_file_limit()
    if arguments == ["update"]:
        RUNTIME.mkdir(mode=0o700, exist_ok=True)
        with (RUNTIME / "cli-update.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("[update] Another CLI update is running.", file=sys.stderr)
                return 1
            return update_clis()
    if arguments == ["--account-status"]:
        return show_status()
    # Explicit CODEX_HOME always wins, including invocations from existing sessions.
    if os.environ.get("CODEX_HOME"):
        os.execv(str(BINARY), [str(BINARY), *arguments])
    if any(arg in ("--help", "-h", "--version", "-V", "--remote")
           or arg.startswith("--remote=") for arg in arguments):
        os.execv(str(BINARY), [str(BINARY), *arguments])
    explicit = os.environ.get("CODEX_ACCOUNT", "auto")
    if explicit not in ("auto", "company", "personal"):
        raise UsageUnavailable("CODEX_ACCOUNT must be auto, company, or personal")
    if command_name(arguments) in MANAGEMENT and explicit == "auto":
        explicit = "company"
    if explicit == "auto" and interactive(arguments) and "--no-daemon" not in arguments:
        return launch_automatic(arguments)
    if explicit != "auto":
        selected = explicit
    else:
        usages = {}
        for name in ("company", "personal"):
            usages[name] = read_usage(BINARY, PROFILES[name])
            if usages[name] < 90:
                break
        summary = ", ".join(f"{name} {used:g}% used" for name, used in usages.items())
        selected = choose(usages)
        print(f"[codex] {summary}; selected {selected}", file=sys.stderr)
    if command_name(arguments) != 'login' and not (PROFILES[selected] / "auth.json").is_file():
        raise UsageUnavailable(f"Saved {selected} login is missing")
    environment = dict(os.environ, CODEX_HOME=str(PROFILES[selected]))
    os.execve(str(BINARY), [str(BINARY), *arguments], environment)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (UsageUnavailable, OSError) as error:
        print(f"[codex] {error}", file=sys.stderr)
        print("[codex] No automatic launch. To choose explicitly: "
              "CODEX_ACCOUNT=company codex or CODEX_ACCOUNT=personal codex", file=sys.stderr)
        raise SystemExit(2)
