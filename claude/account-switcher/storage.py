"""Private non-secret state and Claude Code's existing directory-lock protocol."""

from contextlib import contextmanager, ExitStack
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time


class SwitcherError(RuntimeError):
    """An operator-safe error message, never an upstream response or token."""


class LockBusy(SwitcherError):
    """A different process currently owns the requested lock."""


def fingerprint(oauth):
    token = oauth.get('accessToken')
    if not isinstance(token, str) or not token:
        raise SwitcherError('Claude subscription OAuth access token is missing')
    return hashlib.sha256(token.encode()).hexdigest()


def read_json(path):
    with open(path, encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise SwitcherError(f'Expected a JSON object: {Path(path).name}')
    return data


def write_json(path, value):
    raw = json.dumps(value, indent=2, allow_nan=False) + '\n'
    write_text(path, raw)


def write_text(path, raw):
    path = Path(path)
    if path.is_symlink():
        raise SwitcherError(f'Refusing to replace a symlink: {path.name}')
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class State:
    def __init__(self, root):
        self.root = Path(root).expanduser()
        if self.root.is_symlink():
            raise SwitcherError('State directory must not be a symlink')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.root.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SwitcherError('State directory must be owned by you with mode 0700')

    def load(self, name, default=None):
        path = self.root / f'{name}.json'
        if path.is_symlink():
            raise SwitcherError('State files must not be symlinks')
        return read_json(path) if path.exists() else ({} if default is None else default)

    def save(self, name, data):
        write_json(self.root / f'{name}.json', data)

    def prune_restart_locks(self):
        for path in self.root.glob('restart-*.lock'):
            try:
                fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            except FileNotFoundError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if os.path.samestat(os.fstat(fd), path.lstat()):
                    path.unlink()
            except (BlockingIOError, FileNotFoundError):
                pass
            finally:
                os.close(fd)

    @contextmanager
    def lock(self, name='operation', *, blocking=False):
        path = self.root / f'{name}.lock'
        transient = name.startswith('restart-')
        while True:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
                    fcntl.flock(fd, flags)
                except BlockingIOError:
                    raise LockBusy(f'Another switcher process holds {name}') from None
                if transient:
                    # A contender can open the old inode just before its owner unlinks it.
                    try:
                        if not os.path.samestat(os.fstat(fd), path.stat()):
                            continue
                    except FileNotFoundError:
                        continue
                try:
                    yield
                finally:
                    if transient:
                        path.unlink()
                return
            finally:
                os.close(fd)


@contextmanager
def directory_lock(path, timeout=5):
    """Reclaim only our recorded directory after its kernel-held owner lock is released."""
    path = Path(path)
    owner = Path(str(path) + '.switcher-owner')
    fd = os.open(owner, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SwitcherError(f'Claude is busy: lock={path.name}') from None
                time.sleep(0.1)
        try:
            recorded = json.loads(os.read(fd, 1024))
        except (ValueError, UnicodeDecodeError):
            recorded = None
        if path.exists() and recorded == directory_identity(path):
            path.rmdir()
        with owned_directory_lock(path, max(0, deadline - time.monotonic()), fd):
            yield
    finally:
        os.close(fd)


def directory_identity(path):
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_birthtime]


@contextmanager
def owned_directory_lock(path, timeout, owner_fd):
    deadline = time.monotonic() + timeout
    # Record the inode before publishing it. A crash before publication leaves only staging.
    staged = path.with_name(path.name + '.switcher-staging')
    if staged.exists():
        staged.rmdir()
    staged.mkdir(mode=0o700)
    try:
        identity = directory_identity(staged)
        os.lseek(owner_fd, 0, os.SEEK_SET)
        os.ftruncate(owner_fd, 0)
        record = json.dumps(identity).encode()
        if os.write(owner_fd, record) != len(record):
            raise OSError('Incomplete Claude lock ownership record')
        os.fsync(owner_fd)
        # macOS renamex_np(RENAME_EXCL) never replaces another owner's empty lock.
        rename = ctypes.CDLL(None, use_errno=True).renamex_np
        while rename(os.fsencode(staged), os.fsencode(path), 4) != 0:
            error = ctypes.get_errno()
            if error != errno.EEXIST:
                raise OSError(error, os.strerror(error))
            if time.monotonic() >= deadline:
                raise SwitcherError(f'Claude is busy: lock={path.name}')
            time.sleep(0.1)
    finally:
        if staged.exists():
            staged.rmdir()
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(1):
            try:
                if directory_identity(path) != identity:
                    return
                os.utime(path)
            except OSError:
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    started = False
    try:
        thread.start()
        started = True
        yield
        if directory_identity(path) != identity:
            raise SwitcherError('Claude credential lock ownership changed')
    finally:
        stop.set()
        if started:
            thread.join(timeout=2)
        try:
            if directory_identity(path) == identity:
                path.rmdir()
        except FileNotFoundError:
            pass


class LiveClaude:
    def __init__(self, config_home, config_path, vault):
        self.home = Path(config_home).expanduser().resolve()
        self.config = Path(config_path).expanduser().resolve()
        self.vault = vault

    @contextmanager
    def locked(self):
        with ExitStack() as stack:
            for path in (self.home / '.oauth_refresh.lock',
                         Path(str(self.home) + '.lock'),
                         Path(str(self.config) + '.lock')):
                stack.enter_context(directory_lock(path))
            yield

    def read(self):
        blob = self.vault.read_active()
        if not isinstance(blob, dict) or not isinstance(blob.get('claudeAiOauth'), dict):
            raise SwitcherError('Default Claude subscription login was not found')
        config = read_json(self.config)
        account = config.get('oauthAccount')
        if not isinstance(account, dict) or not account.get('emailAddress'):
            raise SwitcherError('Default Claude account identity is missing')
        fingerprint(blob['claudeAiOauth'])
        return blob, account

    def write_account(self, account):
        config = read_json(self.config)
        config['oauthAccount'] = account
        write_json(self.config, config)
