"""Read usage through the official app-server protocol, without model turns."""

import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from policy import UsageUnavailable
from state import snapshot


def send(process, method, request_id=None, params=None):
    message = {"method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    process.stdin.write((json.dumps(message) + "\n").encode())
    process.stdin.flush()


def read_usage(binary, profile, timeout=20):
    return read_snapshot(binary, profile, timeout)["used_percent"]


def read_snapshot(binary, profile, timeout=20):
    if not (Path(profile) / "auth.json").is_file():
        raise UsageUnavailable("Saved login is missing")
    environment = dict(os.environ, CODEX_HOME=str(profile))
    process = subprocess.Popen(
        [str(binary), "app-server"], env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        return receive_usage(process, timeout)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()


def receive_usage(process, timeout):
    send(process, "initialize", 1, {
        "clientInfo": {"name": "codex-account-launcher", "version": "1.0.0"},
    })
    deadline = time.monotonic() + timeout
    buffer = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            for key, _ in selector.select(timeout=min(1, max(0, deadline - time.monotonic()))):
                block = os.read(key.fd, 65536)
                if not block:
                    raise UsageUnavailable("Usage query exited before returning a result")
                buffer += block
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    result = handle_message(process, line)
                    if result is not None:
                        return snapshot(result)
    raise UsageUnavailable("Usage lookup timed out; no account was selected")


def handle_message(process, line):
    try:
        message = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    request_id = message.get("id")
    if request_id not in (1, 2):
        return None
    if "error" in message:
        # Never include server diagnostics: they may contain credential details.
        raise UsageUnavailable("The official usage query returned an error")
    if request_id == 1:
        send(process, "initialized")
        send(process, "account/rateLimits/read", 2)
        return None
    result = message.get("result")
    if not isinstance(result, dict):
        raise UsageUnavailable("The usage response was invalid")
    return result
