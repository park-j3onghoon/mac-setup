#!/usr/bin/env python3
"""프로필 토큰을 사용자 전용 launchd 설정에 저장하고 공유 Playwright 서버를 등록한다."""

import argparse
import getpass
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


LABEL = 'local.codex-playwright'
PORT = 8931


def install(profile, token):
    directory = Path(__file__).resolve().parent
    cli = directory / 'node_modules/@playwright/mcp/cli.js'
    if not cli.is_file():
        raise FileNotFoundError(f'Playwright dependency missing: run npm ci in {directory}')
    node = shutil.which('node')
    if node is None:
        raise FileNotFoundError('Node.js is not installed')
    chrome_profile = Path.home() / 'Library/Application Support/Google/Chrome' / profile
    extension = chrome_profile / 'Extensions/mmlmfjhmonkocbjadbfplnigmagldckm'
    if not extension.is_dir():
        raise FileNotFoundError(f'Playwright Extension is not installed in Chrome profile {profile}')
    runtime = Path.home() / '.local/share/codex-playwright'
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime.chmod(0o700)
    log = runtime / 'server.log'
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)
    destination = Path.home() / f'Library/LaunchAgents/{LABEL}.plist'
    destination.parent.mkdir(parents=True, exist_ok=True)
    configuration = {
        'Label': LABEL,
        'ProgramArguments': [node, str(cli), '--extension', '--background',
                             '--profile-dir-name', profile, '--host', '127.0.0.1', '--port', str(PORT)],
        'EnvironmentVariables': {'PLAYWRIGHT_MCP_EXTENSION_TOKEN': token,
                                 'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'WorkingDirectory': str(runtime),
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 10,
        'ProcessType': 'Background',
        'StandardOutPath': str(log),
        'StandardErrorPath': str(log),
    }
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{LABEL}-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            plistlib.dump(configuration, output)
        subprocess.run(['/usr/bin/plutil', '-lint', temporary], check=True, capture_output=True, timeout=10)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    domain = f'gui/{os.getuid()}'
    subprocess.run(['/bin/launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True, timeout=10)
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(destination)], check=True, timeout=10)
    print(f'Shared Playwright installed: http://127.0.0.1:{PORT}/mcp (profile={profile})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, help='Chrome profile directory, for example Default')
    arguments = parser.parse_args()
    token = getpass.getpass('Playwright extension token: ') if sys.stdin.isatty() else sys.stdin.read().strip()
    if not token or any(character.isspace() for character in token):
        parser.error('Provide the extension token without whitespace')
    if Path(arguments.profile).name != arguments.profile:
        parser.error('Provide a profile directory name, not a path')
    install(arguments.profile, token)
