"""Own an isolated app-server; account changes stay in that server's memory."""

import os
import hashlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import closing, contextmanager
from pathlib import Path
import resource
import select
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time

from policy import THRESHOLD, UsageUnavailable
from profiles import BINARY, PROFILES
from rpc import Rpc, RpcNotSent, RpcRejected, guard_request
from state import RUNTIME, load, read_checkpoint, save


SOCKET = RUNTIME / "auto.sock"
CONTINUE_PROMPT = "이어서 해줘"
# A thread in systemError runs nothing; leaving it out of the wait keeps one failed thread
# from blocking every later switch.
QUIET = ("idle", "notLoaded", "systemError")
SCAN_COMPLETE = object()


class ActivityChanged(RpcNotSent):
    """New local activity invalidated the check before the write."""


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
    if (target.is_file() and not target.is_symlink()
            or target.is_symlink() and target.readlink() != config):
        with tempfile.TemporaryDirectory(dir=home) as directory:
            replacement = Path(directory) / 'config.toml'
            replacement.symlink_to(config)
            if not target.is_symlink():
                backup = Path(tempfile.mkdtemp(prefix='previous-config-', dir=home))
                os.link(target, backup / 'config.toml')
            os.replace(replacement, target)
    elif target.exists() and not target.is_symlink():
        raise UsageUnavailable(f'Cannot link shared configuration over {target}')
    else:
        link_missing(target, config)
    for profile_config in Path(config).parent.glob('*.config.toml'):
        link_missing(home / profile_config.name, profile_config)
    for name in ("AGENTS.md", "skills", "agents", "rules",
                 "plugins", "packages", "hooks.json", ".hook-trust"):
        target = home / name
        if not target.exists() and not target.is_symlink() and (shared / name).exists():
            link_missing(target, shared / name)


def link_missing(target, source):
    if not target.exists() and not target.is_symlink():
        try:
            target.symlink_to(source)
        except FileExistsError:
            if not target.is_symlink() or target.readlink() != source:
                raise


def server_package_cache(installed, home):
    if installed.parent.name == "bin" and installed.parent.parent.parent.parts[-2:] == ("Caskroom", "codex"):
        return home / "app-server-packages"
    return None


def preserve_server_package(binary, home):
    installed = Path(binary).resolve(strict=True)
    packages = server_package_cache(installed, home)
    if packages is None:
        return installed

    release = installed.parent.parent
    packages.mkdir(mode=0o700, exist_ok=True)
    current = packages / release.name
    executables = ('codex', 'codex-code-mode-host', 'codex-exec-server')
    manifest = '.switcher-checksums.json'

    def identity(package):
        result = {}
        for name in executables:
            path = package / 'bin' / name
            if not path.is_file() or not os.access(path, os.X_OK) or not path.stat().st_size:
                return None
        for path in sorted(package.rglob('*')):
            if path == package / manifest or not path.is_file():
                continue
            info = path.stat()
            result[str(path.relative_to(package))] = [
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode]
        return result

    def digests(package, files):
        result = {}
        for name in files:
            digest = hashlib.sha256()
            with (package / name).open('rb') as stream:
                for block in iter(lambda: stream.read(1 << 20), b''):
                    digest.update(block)
            result[name] = [digest.hexdigest(), (package / name).stat().st_mode]
        return result

    cached, original = identity(current), identity(release)
    recorded = load(current / manifest)
    expected = recorded.get('sha256')
    if not isinstance(expected, dict):
        expected = None
    if original and expected and expected.keys() - original.keys():
        original = None
    if original and (not expected or original != recorded.get('source')):
        expected = digests(release, original)
    matches = cached and expected and (cached == recorded.get('cache') and expected == recorded.get('sha256')
                                       or digests(current, cached) == expected)
    if not matches:
        if original is None:
            raise UsageUnavailable(f"Codex package {release.name} has incomplete executables")
        with tempfile.TemporaryDirectory(prefix=".staging-", dir=packages) as temporary:
            staging = Path(temporary)
            staged = staging / "package"
            shutil.copytree(release, staged)
            copied = identity(staged)
            if copied is None or digests(staged, copied) != expected or identity(release) != original:
                raise UsageUnavailable(f"Codex package {release.name} changed during staging")
            save({'sha256': expected, 'source': original, 'cache': identity(staged)}, staged / manifest)
            if current.exists() or current.is_symlink():
                current.rename(staging / 'replaced')
            staged.rename(current)
    elif original is not None and (recorded.get('source') != original or recorded.get('cache') != cached):
        save({'sha256': expected, 'source': original, 'cache': cached}, current / manifest)

    return current / "bin" / installed.name


def prune_server_packages(server_binary, home, keep=()):
    current = Path(server_binary).parent.parent
    packages = home / "app-server-packages"
    if current.parent != packages:
        return
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=packages) as temporary:
        staging = Path(temporary)
        # 정리 중 종료돼도 다음 시작에서 반쯤 지운 릴리스를 재사용하지 않도록 먼저 이름을 옮긴다.
        for previous in packages.iterdir():
            if previous not in (current, staging) and previous.name not in keep and previous.is_dir() and not previous.is_symlink():
                previous.rename(staging / previous.name)


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
        yield from response['data']
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


def all_idle(client, deadline=None, progress=None):
    if progress is None:
        return all(quiet(thread) for _, thread in loaded_threads(client, deadline))
    # Each RPC keeps its own timeout. Save the iterator between maintenance slices.
    if 'threads' not in progress:
        progress['threads'] = loaded_threads(client)
    for _, thread in progress['threads']:
        if not quiet(thread):
            return False
        if time.monotonic() >= deadline:
            return None
    return True


def newest_turn(client, thread_id):
    try:
        turns = client.request("thread/turns/list", {
            "threadId": thread_id, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded",
        }).get("data", [])
    except RpcRejected as error:
        if error.no_history:
            return None
        raise
    return turns[0] if turns else None


class Runtime:
    def __init__(self, profiles, home=RUNTIME, binary=BINARY):
        self.profiles, self.home, self.binary = profiles, Path(home), binary
        self.socket = self.home / "auto.sock"
        self.process = self.client = None
        self.pid = None
        self.pid_start = None
        self.exit_watch = None
        self.active = None
        self.must_observe_account = False
        self.continued = {}
        self.followups = {}
        self.quota_periods = {}
        self.limit_failure = False
        self.continuation_seen = set()
        self.continuation_missing = None
        self.uncertain_continuations = {}
        self.uncertain_periods = {}
        self.continuation_error = None
        self.restore_error = None
        self.before_drain = None
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
        self.continuing_thread = None
        self.continuation_changed = False
        self.prepared_upgrade = None
        self.upgrade_inspection = None
        self.continuation_path = None
        self.next_subscription_scan = 0
        self.new_subscriptions = set()
        self.release_retries = {}
        self.settled_threads = {}

    def start(self, *, restore_account=None):
        prepare_home(self.home)
        self.continuation_path = self.home / 'continuation-receipts.json'
        try:
            self.load_continuations()
        except UsageUnavailable as error:
            self.continuation_error = str(error)
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
                if restore_account and self.active is None:
                    self.try_restore_account(restore_account)
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
            if restore_account:
                self.try_restore_account(restore_account)
            prune_server_packages(server_binary, self.home)
        except BaseException:
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
                            if account and profile.account_id == account), None)
        if self.active is None:
            raise UsageUnavailable("Existing runtime account is outside the saved profiles")

    def running(self):
        if self.process is not None:
            alive = self.process.poll() is None
            if alive and not self.pid_start:
                self.pid_start = process_start(self.process.pid)
            return alive
        if not self.pid_start:
            return False
        if self.exit_watch:
            if not self.exit_watch.control([], 1, 0):
                return True
            self.exit_watch.close()
            self.exit_watch = None
            self.pid_start = None
            return False
        watch = select.kqueue()
        try:
            try:
                watch.control([select.kevent(self.pid, filter=select.KQ_FILTER_PROC,
                                             flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                             fflags=select.KQ_NOTE_EXIT)], 0, 0)
            except (OSError, ValueError):
                # The kernel may deny event registration. Only a confirmed exit or PID reuse
                # means this adopted server is gone.
                started = process_start(self.pid)
                if started:
                    return started == self.pid_start
                try:
                    os.kill(self.pid, 0)
                except ProcessLookupError:
                    return False
                except PermissionError:
                    pass
                return True
            started = process_start(self.pid)
            if not started:
                return True
            if started != self.pid_start:
                return False
            self.exit_watch, watch = watch, None
            return True
        finally:
            if watch is not None:
                watch.close()

    def drain_for_upgrade(self, installed):
        if self.prepared_upgrade != installed:
            candidate = preserve_server_package(installed, self.home)
            with tempfile.TemporaryDirectory(dir=self.home) as probe:
                config = self.home / "config.toml"
                if config.exists():
                    (Path(probe) / "config.toml").symlink_to(config)
                with closing(Rpc(candidate, probe)) as client:
                    if client.version != installed.parent.parent.name:
                        raise UsageUnavailable("The staged Codex server reported a different version")
            self.prepared_upgrade = installed
            self.upgrade_inspection = None
            if isinstance(self.client.version, str):
                prune_server_packages(candidate, self.home, keep=(self.client.version,))
        if self.client.closed:
            self.observe_account()
        if self.idle_pending or (self.continuation_future and not self.continuation_future.done()):
            return False
        with self.activity_lock:
            serial = self.activity_serial
        deadline = time.monotonic() + 4
        job = self.upgrade_inspection
        if not job or (job['serial'], job['client']) != (serial, self.client):
            if job and job['future'] and not job['future'].done():
                return False
            job = self.upgrade_inspection = {'serial': serial, 'client': self.client,
                'checks': self.upgrade_checks(self.client), 'future': None}
        try:
            while time.monotonic() < deadline:
                if job['future'] is None:
                    job['future'] = self.worker_pool().submit(next, job['checks'], SCAN_COMPLETE)
                try:
                    safe = job['future'].result(timeout=min(.05, max(0, deadline - time.monotonic())))
                except FutureTimeout:
                    if job['future'].done():
                        job['future'].result()
                    return False
                job['future'] = None
                if safe is SCAN_COMPLETE:
                    break
                if not safe:
                    self.upgrade_inspection = None
                    return False
            else:
                return False
        except Exception:
            self.upgrade_inspection = None
            raise
        self.upgrade_inspection = None
        return self.finish_upgrade(serial)

    def upgrade_checks(self, client):
        for thread_id, thread in loaded_threads(client):
            if not quiet(thread) or thread.get("ephemeral"):
                yield False
            params = {"threadId": thread_id}
            yield not client.request("thread/backgroundTerminals/list", params)["data"]
            yield not client.request("thread/queue/list", params)["data"]
            goal = client.request("thread/goal/get", params)["goal"]
            yield not goal or goal["status"] in ("complete", "paused", "blocked", "usageLimited", "budgetLimited")

    def finish_upgrade(self, serial):
        self.observe_account()
        if self.active is None:
            raise UsageUnavailable("Cannot restore an unknown account after the update")
        self.profiles[self.active].tokens()
        if peer_process(self.client.websocket.socket) != (self.pid, self.pid_start):
            raise UsageUnavailable("The shared socket no longer belongs to the recorded runtime")
        # Codex의 SIGHUP은 유휴 확인 도중 시작한 턴도 끝까지 기다린다.
        with self.activity_lock:
            if serial != self.activity_serial:
                return False
            if self.before_drain:
                self.before_drain(self.active)
            os.kill(self.pid, signal.SIGHUP)
        return True

    def login(self, tokens):
        self.client.request("account/login/start", {
            "type": "chatgptAuthTokens", **tokens,
        })

    def restore_account(self, name):
        self.observe_account()
        if self.active is None:
            self.login(self.profiles[name].tokens())
            self.observe_account()
        if self.active != name:
            raise UsageUnavailable("Updated runtime account did not match the previous account")

    def try_restore_account(self, name):
        try:
            self.restore_account(name)
        except (UsageUnavailable, OSError) as error:
            self.restore_error = type(error).__name__

    def refresh(self, method, params, *, cancel=None):
        if method != "account/chatgptAuthTokens/refresh":
            raise UsageUnavailable("Unexpected runtime request")
        previous = params.get("previousAccountId")
        for profile in self.profiles.values():
            if previous and profile.account_id == previous:
                return profile.tokens(force=True, cancel=cancel) if cancel is not None else profile.tokens(force=True)
        raise UsageUnavailable("Unknown account requested a token refresh")

    def release_subscriptions(self):
        """한 대화씩 최대 2초 안에 정리하여 감독 루프에 제어를 돌려준다."""
        if self.continuation_future is not None and not self.continuation_future.done():
            return False
        if self.idle_pending:
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
            if self.release_cursor or time.monotonic() >= self.next_subscription_scan:
                page = request('thread/loaded/list', {'cursor': self.release_cursor})
                self.release_ids.extend(page.get('data', []))
                self.release_cursor = page.get('nextCursor')
                if not self.release_cursor:
                    self.next_subscription_scan = time.monotonic() + 600
            with self.activity_lock:
                self.release_ids.extend(self.new_subscriptions)
                self.new_subscriptions.clear()
            now = time.monotonic()
            self.release_ids.extend(key for key, retry in self.release_retries.items() if now >= retry)
            self.release_ids = deque(dict.fromkeys(self.release_ids))
        if self.release_ids:
            thread_id = self.release_ids[0]
            params = {'threadId': thread_id}
            try:
                thread = request('thread/read', {**params, 'includeTurns': False}).get('thread', {})
                if quiet(thread) and not request('thread/backgroundTerminals/list', params)['data']:
                    goal = request('thread/goal/get', params)['goal']
                    if (not goal or goal.get('status') == 'complete') and not request('thread/queue/list', params)['data']:
                        request('thread/unsubscribe', params)
            except RpcRejected as error:
                if not error.thread_missing:
                    self.release_retries[thread_id] = time.monotonic() + 5
                    raise
                self.release_retries.pop(thread_id, None)
            except (UsageUnavailable, OSError):
                self.release_retries[thread_id] = time.monotonic() + 5
                raise
            else:
                self.release_retries.pop(thread_id, None)
            finally:
                self.release_ids.popleft()
        return not self.release_ids and not self.release_cursor and not self.release_retries

    def take_limit_failure(self):
        with self.activity_lock:
            pending, self.limit_failure = self.limit_failure, False
            return pending

    def activity(self, method, params):
        owner = params.get('threadId') or (params.get('thread') or {}).get('id')
        with self.activity_lock:
            turn = params.get('turn') or {}
            if method == 'turn/completed' and (turn.get('error') or {}).get('codexErrorInfo') == 'usageLimitExceeded':
                self.limit_failure = True
            if owner:
                self.settled_threads.pop(owner, None)
            else:
                self.settled_threads.clear()
        if (method in ('thread/started', 'turn/started', 'turn/completed', 'thread/queue/changed',
                       'thread/goal/updated', 'thread/goal/cleared') or method == 'thread/status/changed'
                and params.get('status', {}).get('type') not in QUIET):
            with self.activity_lock:
                self.activity_serial += 1
                if owner and method == 'thread/started':
                    self.new_subscriptions.add(owner)
                if self.continuing_thread and owner in (None, self.continuing_thread):
                    self.continuation_changed = True

    @property
    def idle_pending(self):
        return self.idle_job is not None and not self.idle_job['future'].done()

    def idle_ready(self, name, tokens):
        if self.idle_job is None:
            with self.activity_lock:
                deadline = time.monotonic() + 300
                progress = {}
                self.idle_job = {'name': name, 'tokens': tokens, 'client': self.client,
                                 'serial': self.activity_serial, 'deadline': deadline, 'progress': progress,
                                 'future': self.worker_pool().submit(all_idle, self.client,
                                     deadline=time.monotonic() + 30, progress=progress)}
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
            valid = (time.monotonic() < job['deadline'] and job['name'] == name and job['tokens'] == tokens
                     and job['client'] is self.client and job['serial'] == self.activity_serial)
            if valid and idle is None:
                job['future'] = self.worker_pool().submit(all_idle, self.client,
                    deadline=time.monotonic() + 30, progress=job['progress'])
                self.idle_job = job
            return valid and idle is True

    def worker_pool(self):
        if self.idle_pool is None:
            self.idle_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='codex-maintenance')
        return self.idle_pool

    def select(self, name, *, force=False):
        if self.client.closed or self.must_observe_account:
            self.observe_account()
            self.must_observe_account = False
        if name == self.active:
            if self.idle_job is not None and not self.idle_pending:
                self.idle_job = None
            return True
        if not force and self.idle_pending:
            return False
        profile = self.profiles[name]
        tokens = profile.tokens()
        with self.activity_lock:
            serial = self.activity_serial
        if not force and not self.idle_ready(name, tokens):
            return False
        if profile.usage()['used_percent'] >= THRESHOLD:
            raise UsageUnavailable('Target account no longer has available quota')
        tokens = profile.tokens()
        with self.activity_lock:
            if not force and serial != self.activity_serial:
                return False
            self.activity_serial += 1
            serial = self.activity_serial
            self.settled_threads.clear()
            if self.continuing_thread:
                self.continuation_changed = True
        @contextmanager
        def idle_at_send():
            with self.activity_lock:
                if not force and serial != self.activity_serial:
                    raise ActivityChanged('New activity before account switch')
                yield
        old = self.active
        login_sent = False
        try:
            with guard_request('account/login/start', idle_at_send):
                self.login(tokens)
            login_sent = True
            verified = self.client.request("account/rateLimits/read")
            if verified.get("accountId") != profile.account_id:
                raise UsageUnavailable("Runtime account verification did not match")
            self.active = name
            return True
        except Exception as error:
            if isinstance(error, ActivityChanged):
                return False
            if isinstance(error, (RpcNotSent, RpcRejected)) and not login_sent:
                raise
            self.active = None
            self.must_observe_account = True
            if old is not None:
                try:
                    self.observe_account()
                    if self.active == name:
                        rollback_tokens = self.profiles[old].tokens()
                        self.observe_account()
                        if self.active == name:
                            self.login(rollback_tokens)
                            self.observe_account()
                except (UsageUnavailable, OSError):
                    self.active = None
            raise

    def continue_limited(self):
        """Start CONTINUE_PROMPT once on each quiet thread whose newest turn hit the usage limit.

        A turn started from this connection still sends its approval requests to the terminal
        that opened the thread (measured on 0.168.0, 2026-11-13).
        """
        if self.continuation_error:
            self.load_continuations()
            self.continuation_error = None
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
                    if self.continuation_missing is None:
                        self.continuation_missing = deque()
                        for gone in self.continued.keys() - self.continuation_seen - self.uncertain_continuations.keys():
                            self.continued.pop(gone)
                        self.continuation_missing.extend((self.uncertain_continuations.keys() | self.followups.keys())
                                                         - self.continuation_seen)
                        with self.activity_lock:
                            for gone in self.settled_threads.keys() - self.continuation_seen:
                                self.settled_threads.pop(gone)
                    if self.continuation_missing:
                        gone = self.continuation_missing.popleft()
                        # An unloaded conversation may return. Confirm deletion before permitting replay.
                        try:
                            client.request('thread/read', {'threadId': gone, 'includeTurns': False})
                            if gone in self.followups:
                                latest = newest_turn(client, gone)
                                if latest and (latest['id'] != self.followups[gone][0] or latest['status'] == 'completed'):
                                    self.followups.pop(gone)
                                    self.store_followups()
                        except RpcRejected as error:
                            if error.thread_missing:
                                self.uncertain_continuations.pop(gone, None)
                                self.continued.pop(gone, None)
                                self.store_continuations()
                                if self.followups.pop(gone, None):
                                    self.store_followups()
                        except UsageUnavailable:
                            pass
                        continue
                    self.continuation_missing = None
                    self.continuation_started = self.continuation_failed = False
                    unresolved = bool(self.uncertain_continuations.keys() & self.continuation_seen)
                    self.continuation_seen.clear()
                    if failed or unresolved:
                        raise UsageUnavailable('Some limited threads could not be continued')
                    return True
                page = scan_request(client, 'thread/loaded/list',
                                    {'cursor': self.continuation_cursor}, deadline)
                self.continuation_ids.extend(page.get('data', []))
                self.continuation_seen.update(page.get('data', []))
                self.continuation_cursor = page.get('nextCursor')
                self.continuation_started = True
                continue
            thread_id = self.continuation_ids[0]
            try:
                # Finish one thread with the per-RPC timeout; restarting its metadata phases
                # at every batch boundary would starve both slow and later threads.
                self.continue_thread(thread_id, client)
            except (UsageUnavailable, KeyError, AttributeError, IndexError, TypeError):
                self.continuation_failed = True
            self.continuation_ids.popleft()
        return False

    def continue_thread(self, thread_id, client):
        with self.activity_lock:
            cached = self.settled_threads.get(thread_id)
            if cached and cached[0] is client and time.monotonic() < cached[1]:
                return
            self.continuing_thread, self.continuation_changed = thread_id, False
        try:
            self._continue_thread(thread_id, client)
        finally:
            with self.activity_lock:
                self.continuing_thread = None

    def _continue_thread(self, thread_id, client):
        thread = client.request('thread/read', {
            'threadId': thread_id, 'includeTurns': False,
        }).get('thread', {})
        # A parent drives its sub-agents; direct turn/start on a child is rejected.
        if thread.get('parentThreadId') or not quiet(thread):
            return
        turn = newest_turn(client, thread_id)
        workspace = getattr(self.profiles.get(self.active), 'account_id', None)
        period = [workspace if isinstance(workspace, str) else self.active, self.quota_periods.get(self.active, 0)]
        prior = self.followups.get(thread_id)
        if prior and turn:
            if prior == [turn['id'], *period] and turn['status'] == 'failed':
                return
            if prior[0] != turn['id'] or turn['status'] == 'completed':
                self.followups.pop(thread_id)
                self.store_followups()
        uncertain = self.uncertain_continuations.get(thread_id)
        if uncertain and turn and turn['id'] != uncertain:
            submitted_period = self.uncertain_periods.get(thread_id)
            if turn['status'] == 'failed' and (submitted_period is None or submitted_period == period):
                self.followups[thread_id] = [turn['id'], *period]
                self.store_followups()
            self.uncertain_continuations.pop(thread_id, None)
            self.store_continuations()
            if self.followups.get(thread_id) == [turn['id'], *period]:
                return
        if (not turn or self.continued.get(thread_id) == turn['id'] or turn['status'] != 'failed'
                or (turn.get('error') or {}).get('codexErrorInfo') != 'usageLimitExceeded'):
            if turn and turn['status'] == 'completed' and not self.continuation_changed:
                with self.activity_lock:
                    if not self.continuation_changed:
                        self.settled_threads[thread_id] = (client, time.monotonic() + 300)
            return
        if self.continuation_changed:
            return
        if client.request('thread/queue/list', {'threadId': thread_id})['data']:
            return
        latest = newest_turn(client, thread_id)
        if self.continuation_changed or latest != turn:
            return
        if client.request('thread/queue/list', {'threadId': thread_id})['data'] or self.continuation_changed:
            return
        goal = client.request('thread/goal/get', {'threadId': thread_id})['goal']
        if goal and goal.get('status') not in ('active', 'usageLimited'):
            return
        self.uncertain_continuations[thread_id] = turn['id']
        self.uncertain_periods[thread_id] = period
        self.store_continuations()
        self.continued[thread_id] = turn['id']
        @contextmanager
        def unchanged_at_send():
            with self.activity_lock:
                if self.continuation_changed:
                    raise ActivityChanged('Conversation changed before continuation')
                yield
        try:
            with guard_request('turn/start', unchanged_at_send):
                result = client.request('turn/start', {
                    "threadId": thread_id, "input": [{"type": "text", "text": CONTINUE_PROMPT}],
                })
        except (RpcRejected, RpcNotSent) as error:
            self.continued.pop(thread_id, None)
            self.uncertain_continuations.pop(thread_id, None)
            self.store_continuations()
            if isinstance(error, ActivityChanged):
                return
            raise
        except UsageUnavailable:
            self.uncertain_continuations[thread_id] = turn['id']
            raise
        else:
            started = (result.get('turn') or {}).get('id') if isinstance(result, dict) else None
            if not isinstance(started, str) or not started:
                raise UsageUnavailable('Continuation acknowledgement did not identify the new turn')
            self.followups[thread_id] = [started, *period]
            self.store_followups()
            self.uncertain_continuations.pop(thread_id, None)
            self.store_continuations()

    def store_followups(self):
        if self.continuation_path:
            save(self.followups, self.home / 'continuation-followups.json', durable=True)

    def store_continuations(self):
        self.uncertain_periods = {key: value for key, value in self.uncertain_periods.items()
                                  if key in self.uncertain_continuations}
        if self.continuation_path:
            save({key: {'turn_id': turn, 'period': self.uncertain_periods[key]}
                  if key in self.uncertain_periods else turn
                  for key, turn in self.uncertain_continuations.items()}, self.continuation_path, durable=True)

    def load_continuations(self):
        receipts = read_checkpoint(self.continuation_path)
        followups = read_checkpoint(self.home / 'continuation-followups.json')
        turns, periods = {}, {}
        for key, value in receipts.items():
            if isinstance(value, str) and value:
                turns[key] = value
            elif (isinstance(value, dict) and isinstance(value.get('turn_id'), str)
                  and isinstance(value.get('period'), list) and len(value['period']) == 2):
                turns[key], periods[key] = value['turn_id'], value['period']
            else:
                raise UsageUnavailable('Invalid continuation receipt')
        if any(not isinstance(value, list) or len(value) != 3 or not isinstance(value[0], str)
               for value in followups.values()):
            raise UsageUnavailable('Invalid continuation followup')
        self.uncertain_continuations, self.uncertain_periods, self.followups = turns, periods, followups
        self.continued.update(turns)

    def close(self):
        if self.exit_watch is not None:
            self.exit_watch.close()
            self.exit_watch = None
        if self.client:
            self.client.close()
            self.client = None
        self.settled_threads.clear()
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
