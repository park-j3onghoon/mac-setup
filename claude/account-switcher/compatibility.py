"""Validate the installed credential contract instead of pinning a patch version."""

import json
import mmap
from pathlib import Path
import re
import subprocess

from storage import SwitcherError


MARKERS = (b'.oauth_refresh.lock', b'claudeAiOauth', b'mcpOAuth',
           b'find-generic-password', b'add-generic-password', b'api/oauth/usage',
           b'/v1/oauth/token')
# Running the check reads the login through Claude Code, so a failure may mean a prompt.
FAILURE = 'Installed Claude credential compatibility check failed'


def check(executable, config_home, accounts, previous=None, runner=None):
    runner = subprocess.run if runner is None else runner
    if (Path(config_home) / '.config.json').exists():
        raise SwitcherError('Legacy Claude config layout needs a separate compatibility check')
    try:
        path = Path(executable).resolve(strict=True)
        info = path.stat()
        identity = [str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
        if previous and previous.get('binary_identity') == identity:
            # The same binary reads the login the same way, and every tick still reads it through
            # /usr/bin/security (macos.NativeKeychain.read), which halts when it fails. Running
            # the CLI cost 0.17 s of CPU and 145 MB on every tick (2026-11-16).
            return previous
        version = runner([executable, '--version'], capture_output=True, text=True,
                         timeout=5, check=True).stdout.strip().split(' ', 1)[0]
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise SwitcherError('Could not identify the installed Claude CLI')
        with path.open('rb') as stream, \
                mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as binary:
            if not all(binary.find(marker) >= 0 for marker in MARKERS):
                raise SwitcherError('Claude credential storage or lock contract changed')
        status = json.loads(runner([executable, 'auth', 'status', '--json'], capture_output=True,
                                   text=True, timeout=5, check=True).stdout)
        if (status.get('loggedIn') is not True or status.get('authMethod') != 'claude.ai'
                or status.get('email') not in accounts):
            raise SwitcherError('Installed Claude CLI cannot read the configured subscription login')
        return {'version': version, 'binary_identity': identity, 'credential_contract': 'verified',
                'native_login_read': 'ok', 'active': status['email']}
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SwitcherError(FAILURE) from None
