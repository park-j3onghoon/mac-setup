"""Own an isolated app-server; account changes stay in that server's memory."""

import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
import resource
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time

from policy import THRESHOLD, UsageUnavailable
from profiles import BINARY, PROFILES
from rpc import Rpc, RpcNotSent, RpcRejected
from state import RUNTIME


SOCKET = RUNTIME / "auto.sock"
CONTINUE_PROMPT = "이어서 해줘"
# A thread in systemError runs nothing; leaving it out of the wait keeps one failed thread
# from blocking every later switch.
QUIET = ("idle", "notLoaded", "systemError")


def process_start(pid):
    """명령 인자와 환경을 읽지 않고 PID의 재사용을 구분한다."""
    if not isinstance(pid, int) or pid < 2:
        return None
    try:
        result = subprocess.run(['/bin/ps', '-o', 'lstart=', '-p', str(pid)],
                                capture_output=True, text=True, timeout=2, check=False,
                                env={'LC_ALL': 'C', 'TZ': 'UTC'})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def peer_process(connection):
    # Darwin의 LOCAL_PEERPID=2, LOCAL_PEERCRED=1은 연결한 상대의 커널 정보를 돌려준다.
    pid = connection.getsockopt(0, 2)
    credentials = connection.getsockopt(0, socket.LOCAL_PEERCRED, 128)
    _, uid = struct.unpack_from('II', credentials)
    started = process_start(pid)
    if uid != os.getuid() or not started:
        raise UsageUnavailable('Automatic runtime socket owner could not be verified')
    return pid, started


def raise_file_limit():
    """새 Codex 프로세스의 용량을 보완하며 hard limit은 유지한다."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = 4096 if hard == resource.RLIM_INFINITY else min(4096, hard)
    if soft != resource.RLIM_INFINITY and soft < target:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))


def prepare_home(home=RUNTIME, shared=Path.home() / ".codex",
                 config=PROFILES["company"] / "config.toml"):
    home = Path(home)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    home.chmod(0o700)
    # Company comes first, so the shared server opens with the company setup (MCP servers,
    # model); earlier versions linked the personal config here.
    target = home / "config.toml"
    if target.is_symlink() and target.readlink() != config:
        target.unlink()
    if not target.exists() and not target.is_symlink():
        target.symlink_to(config)
    for name in ("AGENTS.md", "skills", "agents", "rules",
                 "plugins", "packages", "hooks.json", ".hook-trust"):
        target = home / name
        if not target.exists() and not target.is_symlink() and (shared / name).exists():
            target.symlink_to(shared / name, target_is_directory=(shared / name).is_dir())


def preserve_server_package(binary, home):
    installed = Path(binary).resolve(strict=True)
    release = installed.parent.parent
    if installed.parent.name != "bin" or release.parent.parts[-2:] != ("Caskroom", "codex"):
        return installed

    packages = home / "app-server-packages"
    packages.mkdir(mode=0o700, exist_ok=True)
    current = packages / release.name
    executables = ('codex', 'codex-code-mode-host', 'codex-exec-server')
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=packages) as temporary:
        staging = Path(temporary)
        if not all((current / 'bin' / name).is_file() and os.access(current / 'bin' / name, os.X_OK)
                   for name in executables):
            staged = staging / "package"
            shutil.copytree(release, staged)
            for name in executables:
                if not (staged / 'bin' / name).is_file() or not os.access(staged / "bin" / name, os.X_OK):
                    raise UsageUnavailable(f"Codex package {release.name} is missing executable {name}")
            if current.exists() or current.is_symlink():
                current.rename(staging / 'replaced')
            staged.rename(current)

        # 정리 중 종료돼도 다음 시작에서 반쯤 지운 릴리스를 재사용하지 않도록 먼저 이름을 옮긴다.
        for previous in packages.iterdir():
            if previous not in (current, staging) and previous.is_dir() and not previous.is_symlink():
                previous.rename(staging / previous.name)
    return current / "bin" / installed.name


def scan_request(client, method, params, deadline=None):
    if deadline is None:
        return client.request(method, params)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UsageUnavailable('Idle scan budget exhausted')
    result = client.request(method, params, timeout=min(30, remaining))
    if time.monotonic() >= deadline:
        raise UsageUnavailable('Idle scan budget exhausted')
    return result


def loaded_thread_ids(client, deadline=None):
    cursor = None
    while True:
        response = scan_request(client, 'thread/loaded/list', {'cursor': cursor}, deadline)
        yield from response.get('data', [])
        cursor = response.get("nextCursor")
        if not cursor:
            return


def loaded_threads(client, deadline=None):
    """Yield (thread id, thread without turns) for every thread loaded in the runtime."""
    for thread_id in loaded_thread_ids(client, deadline):
        yield thread_id, scan_request(client, 'thread/read', {
            'threadId': thread_id, 'includeTurns': False,
        }, deadline).get('thread', {})


def quiet(thread):
    return thread.get("status", {}).get("type") in QUIET


def all_idle(client, deadline=None):
    return all(quiet(thread) for _, thread in loaded_threads(client, deadline))


def newest_turn(client, thread_id, deadline=None):
    try:
        turns = scan_request(client, "thread/turns/list", {
            "threadId": thread_id, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded",
        }, deadline).get("data", [])
    except RpcRejected:
        # A thread whose first turn has not been written yet has no rollout to list.
        return None
    return turns[0] if turns else None


class Runtime:
    def __init__(self, profiles, home=RUNTIME, binary=BINARY):
        self.profiles, self.home, self.binary = profiles, Path(home), binary
        self.socket = self.home / "auto.sock"
        self.process = self.client = None
        self.pid = None
        self.pid_start = None
        self.active = None
        self.continued = set()
        self.uncertain_continuations = {}
        self.continuation_future = None
        self.continuation_ids = deque()
        self.continuation_cursor = None
        self.continuation_started = False
        self.continuation_failed = False
        self.release_ids = deque()
        self.release_cursor = None
        self.idle_pool = None
        self.idle_job = None
        self.activity_lock = threading.Lock()
        self.activity_serial = 0

    def start(self):
        prepare_home(self.home)
        if self.socket.exists():
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.settimeout(2)
                probe.connect(str(self.socket))
            except (ConnectionRefusedError, FileNotFoundError):
                self.socket.unlink(missing_ok=True)
            else:
                self.pid, self.pid_start = peer_process(probe)
                self.observe_account()
                return
            finally:
                probe.close()
        # Every loaded conversation can retain MCP pipes and sockets in this one process.
        # macOS's inherited soft limit of 256 is insufficient for the shared server.
        raise_file_limit()
        server_binary = preserve_server_package(self.binary, self.home)
        # The company config locks logins to the company workspace; the shared server must also
        # accept the personal workspace. A terminal attached to it does not enforce the lock
        # (both measured on 0.168.0, 2026-11-13).
        self.process = subprocess.Popen(
            [str(server_binary), "app-server", "-c", 'forced_chatgpt_workspace_id=""',
             "--listen", "unix://" + str(self.socket)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, CODEX_HOME=str(self.home)),
            start_new_session=True,
        )
        self.pid = self.process.pid
        self.pid_start = process_start(self.pid)
        try:
            deadline = time.monotonic() + 20
            while True:
                if self.process.poll() is not None or time.monotonic() >= deadline:
                    raise UsageUnavailable("Automatic Codex runtime did not start")
                if self.socket.exists():
                    try:
                        self.client = Rpc(self.binary, self.home, self.socket, self.refresh,
                                          notification=self.activity)
                        break
                    except (ConnectionRefusedError, FileNotFoundError):
                        pass
                time.sleep(0.1)
        except Exception:
            self.stop()
            raise

    def observe_account(self):
        """Read the server's current identity even when another client changed it.

        Logging in again would restart every loaded thread's MCP servers, and token refresh
        requests reach every connection anyway (app-server/src/outgoing_message.rs in 0.169.0).
        """
        self.active = None
        if self.client is None or self.client.closed:
            if self.client:
                self.client.close()
            self.client = Rpc(self.binary, self.home, self.socket, self.refresh,
                              notification=self.activity)
        response = self.client.request("account/read", {"refreshToken": False})
        if response.get("account") is None:
            return
        account = (response.get("workspaceRouting") or {}).get("chatgptAccountId")
        self.active = next((name for name, profile in self.profiles.items()
                            if profile.account_id == account), None)
        if self.active is None:
            raise UsageUnavailable("Existing runtime account is outside the saved profiles")

    def running(self):
        if self.process is not None:
            return self.process.poll() is None
        return self.pid_start is not None and process_start(self.pid) == self.pid_start

    def refresh(self, method, params):
        if method != "account/chatgptAuthTokens/refresh":
            raise UsageUnavailable("Unexpected runtime request")
        previous = params.get("previousAccountId")
        for profile in self.profiles.values():
            if profile.account_id == previous:
                return profile.tokens(force=True)
        raise UsageUnavailable("Unknown account requested a token refresh")

    def release_subscriptions(self):
        """한 대화씩 최대 2초 안에 정리하여 감독 루프에 제어를 돌려준다."""
        if self.continuation_future is not None and not self.continuation_future.done():
            return False
        if self.idle_job is not None:
            if self.idle_job['future'].done() and time.monotonic() >= self.idle_job['deadline']:
                self.idle_job = None
            else:
                return False
        if self.client.closed:
            self.release_ids.clear()
            self.release_cursor = None
            return True
        deadline = time.monotonic() + 2

        def request(method, params):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UsageUnavailable('Subscription cleanup budget exhausted')
            return self.client.request(method, params, timeout=remaining)

        if not self.release_ids:
            page = request('thread/loaded/list', {'cursor': self.release_cursor})
            self.release_ids.extend(page.get('data', []))
            self.release_cursor = page.get('nextCursor')
        if self.release_ids:
            thread_id = self.release_ids[0]
            params = {'threadId': thread_id}
            try:
                thread = request('thread/read', {**params, 'includeTurns': False}).get('thread', {})
                if quiet(thread) and not request('thread/backgroundTerminals/list', params)['data']:
                    request('thread/unsubscribe', params)
            finally:
                self.release_ids.popleft()
        return not self.release_ids and not self.release_cursor

    def activity(self, method, params):
        if (method in ('thread/started', 'turn/started') or method == 'thread/status/changed'
                and params.get('status', {}).get('type') not in QUIET):
            with self.activity_lock:
                self.activity_serial += 1

    @property
    def idle_pending(self):
        return self.idle_job is not None and not self.idle_job['future'].done()

    def idle_ready(self, name, tokens):
        if self.idle_job is None:
            with self.activity_lock:
                deadline = time.monotonic() + 300
                self.idle_job = {'name': name, 'tokens': tokens, 'client': self.client,
                                 'serial': self.activity_serial, 'deadline': deadline,
                                 'future': self.worker_pool().submit(
                                     all_idle, self.client, deadline=deadline)}
        job = self.idle_job
        try:
            idle = job['future'].result(timeout=.02)
        except FutureTimeout:
            return False
        except Exception:
            self.idle_job = None
            raise
        self.idle_job = None
        with self.activity_lock:
            return (idle and job['name'] == name and job['tokens'] == tokens
                    and job['client'] is self.client and job['serial'] == self.activity_serial)

    def worker_pool(self):
        if self.idle_pool is None:
            self.idle_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='codex-maintenance')
        return self.idle_pool

    def select(self, name, *, force=False):
        if self.client.closed:
            self.observe_account()
        if name == self.active:
            if self.idle_job is not None and not self.idle_pending:
                self.idle_job = None
            return True
        if not force and self.idle_pending:
            return False
        profile = self.profiles[name]
        if profile.usage()['used_percent'] >= THRESHOLD:
            raise UsageUnavailable('Target account no longer has available quota')
        tokens = profile.tokens()
        if not force and not self.idle_ready(name, tokens):
            return False
        old = self.active
        self.activity('turn/started', {})
        try:
            self.client.request("account/login/start", {
                "type": "chatgptAuthTokens", **tokens,
            })
            verified = self.client.request("account/rateLimits/read")
            if verified.get("accountId") != profile.account_id:
                raise UsageUnavailable("Runtime account verification did not match")
            self.active = name
            return True
        except Exception:
            self.active = None
            if old is not None:
                try:
                    self.client.request("account/login/start", {
                        "type": "chatgptAuthTokens", **self.profiles[old].tokens(),
                    })
                    restored = self.client.request("account/rateLimits/read")
                    if restored.get("accountId") == self.profiles[old].account_id:
                        self.active = old
                except Exception:
                    pass
            raise

    def continue_limited(self):
        """Start CONTINUE_PROMPT once on each quiet thread whose newest turn hit the usage limit.

        A turn started from this connection still sends its approval requests to the terminal
        that opened the thread (measured on 0.168.0, 2026-11-13).
        """
        if self.continuation_future is None:
            self.continuation_future = self.worker_pool().submit(self.continue_batch, self.client)
        try:
            complete = self.continuation_future.result(timeout=.02)
        except FutureTimeout:
            return False
        except Exception:
            self.continuation_future = None
            raise
        self.continuation_future = None
        return complete

    def continue_batch(self, client):
        """Keep the page cursor across bounded background batches."""
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not self.continuation_ids:
                if self.continuation_started and not self.continuation_cursor:
                    failed = self.continuation_failed
                    self.continuation_started = self.continuation_failed = False
                    if failed or self.uncertain_continuations:
                        raise UsageUnavailable('Some limited threads could not be continued')
                    return True
                page = scan_request(client, 'thread/loaded/list',
                                    {'cursor': self.continuation_cursor}, deadline)
                self.continuation_ids.extend(page.get('data', []))
                self.continuation_cursor = page.get('nextCursor')
                self.continuation_started = True
                continue
            thread_id = self.continuation_ids[0]
            try:
                self.continue_thread(thread_id, client, deadline)
            except UsageUnavailable:
                if time.monotonic() >= deadline:
                    return False
                self.continuation_failed = True
            self.continuation_ids.popleft()
        return False

    def continue_thread(self, thread_id, client, deadline):
        thread = scan_request(client, 'thread/read', {
            'threadId': thread_id, 'includeTurns': False,
        }, deadline).get('thread', {})
        # A parent drives its sub-agents; direct turn/start on a child is rejected.
        if thread.get('parentThreadId') or not quiet(thread):
            if thread.get('status', {}).get('type') == 'active':
                self.uncertain_continuations.pop(thread_id, None)
            return
        turn = newest_turn(client, thread_id, deadline)
        uncertain = self.uncertain_continuations.get(thread_id)
        if uncertain and turn and turn['id'] != uncertain:
            self.uncertain_continuations.pop(thread_id, None)
        if (not turn or turn['id'] in self.continued or turn['status'] != 'failed'
                or (turn.get('error') or {}).get('codexErrorInfo') != 'usageLimitExceeded'):
            return
        self.continued.add(turn['id'])
        try:
            # Do not classify a batch budget expiring before send as an uncertain submission.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RpcNotSent('Continuation batch budget exhausted')
            client.request('turn/start', {
                "threadId": thread_id, "input": [{"type": "text", "text": CONTINUE_PROMPT}],
            }, timeout=min(30, remaining))
        except (RpcRejected, RpcNotSent):
            self.continued.discard(turn['id'])
            raise
        except UsageUnavailable:
            self.uncertain_continuations[thread_id] = turn['id']
            raise

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
        if self.idle_pool:
            self.idle_pool.shutdown(wait=False, cancel_futures=True)
            self.idle_pool = None
            self.idle_job = None

    def stop(self):
        """새 서버 시작 실패와 명시적인 종료에서만 소유 프로세스를 내린다."""
        self.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
