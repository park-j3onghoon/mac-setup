#!/usr/bin/env python3
"""A two-account Claude Code switcher, with no third-party Python packages."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import threading
import time

from api import Anthropic
from compatibility import FAILURE as COMPATIBILITY_FAILURE
from macos import Keychain, KeychainError, Vault, system_awake
from measurement import Measurement, observe, summarize
from monitoring import review_if_due, start as start_monitoring
from refresh import record_switch
from service import Switcher
from storage import LiveClaude, State, SwitcherError, read_json


AUDITED_VERSION = '2.1.323'
LABEL = 'local.claude-account-switcher'
HALT_POLL_SECONDS = 300
DEFAULT_STATE = Path(__file__).resolve().parents[2] / 'private/claude/account-switcher'


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    commands = root.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='create non-secret local settings')
    init.add_argument('--primary', required=True)
    init.add_argument('--fallback', required=True)
    init.add_argument('--threshold', type=float, default=90)
    for name in ('status', 'doctor', 'authorize', 'service-install', 'service-uninstall',
                 'measure-once', 'measure-status', 'monitor-status', 'resume'):
        commands.add_parser(name)
    monitor = commands.add_parser('monitor-start')
    monitor.add_argument('--days', type=int, default=14)
    for name in ('capture', 'enroll'):
        command = commands.add_parser(name)
        command.add_argument('role', choices=('primary', 'fallback'))
    for name in ('once', 'run'):
        command = commands.add_parser(name)
        command.add_argument('--apply', action='store_true', help='permit live credential changes')
    return root


def check_environment():
    names = ('CLAUDE_CONFIG_DIR', 'CLAUDE_SECURESTORAGE_CONFIG_DIR',
             'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN',
             'ANTHROPIC_PROFILE', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_USE_BEDROCK',
             'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')
    present = [name for name in names if os.environ.get(name)]
    if present:
        raise SwitcherError('Default subscription profile required; unset: ' + ', '.join(present))


def initialize(args, state):
    if (state.root / 'config.json').exists():
        raise SwitcherError('Configuration already exists; init never overwrites it')
    # cmux can put a temporary command shim first on PATH; launchd must outlive it.
    native = Path.home() / '.local/bin/claude'
    executable = str(native) if native.is_file() else shutil.which('claude')
    if not executable:
        raise SwitcherError('Claude Code executable was not found')
    config = {'schema': 1, 'primary': args.primary, 'fallback': args.fallback,
              'threshold': args.threshold, 'poll_seconds': 60, 'settle_seconds': 45,
              'supported_version': AUDITED_VERSION,
              'claude_executable': str(Path(executable).absolute()),
              'config_home': str(Path.home() / '.claude'),
              'config_path': str(Path.home() / '.claude.json')}
    from service import validate_config
    validate_config(config)
    state.save('config', config)
    print('Initialized local settings. No credential was changed.')


def build(state, allow_interaction=False):
    config = state.load('config')
    namespace = hashlib.sha256(str(state.root.resolve()).encode()).hexdigest()[:16]
    vault = Vault(Keychain(allow_interaction), namespace)
    live = LiveClaude(config['config_home'], config['config_path'], vault)
    return Switcher(config, state, live, vault, Anthropic())


def show_status(state):
    print(json.dumps({'config': state.load('config'), 'accounts': state.load('roster'),
                      'runtime': state.load('runtime'),
                      'last_report': state.load('last_report'),
                      'halt': state.load('halt'),
                      'service_settings': state.load('service_settings'),
                      'monitoring': state.load('monitoring')}, indent=2))


def halts_keychain_work(exc, awake=system_awake):
    """A failed Keychain read can mean a prompt in every Claude session; never retry it on a timer.

    The compatibility check also fails when it runs in a dark wake: on 2026-11-14 14:37 the
    first check of a freshly updated Claude Code ran one second into a lid-closed wake, with no
    prompt (no SecurityAgent), and halted the service for a day. That case retries instead.
    """
    if isinstance(exc, KeychainError):
        return True
    return str(exc) == COMPATIBILITY_FAILURE and awake()


def tick_once(app, apply, last_outcome):
    """Return (report, delay, outcome). While halted, nothing reads Claude's login item."""
    halt = app.state.load('halt')
    if halt:
        app.state.save('switcher_health', {
            'observed_at': time.time(), 'state': 'halted', 'reason': halt.get('reason'),
            'threshold': app.config['threshold']})
        return None, HALT_POLL_SECONDS, last_outcome
    try:
        report = app.tick(apply=apply)
    except (SwitcherError, KeychainError, OSError, ValueError) as exc:
        # Every admitted exception has a credential-free message.
        outcome = (type(exc).__name__, str(exc))
        if outcome != last_outcome:
            print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}), flush=True)
        app.state.save('switcher_health', {
            'observed_at': time.time(), 'state': 'blocked',
            'error_type': type(exc).__name__, 'reason': str(exc),
            'threshold': app.config['threshold']})
        if halts_keychain_work(exc):
            app.state.save('halt', {'observed_at': time.time(),
                                    'error_type': type(exc).__name__, 'reason': str(exc)})
            print(json.dumps({'halted': str(exc)}), flush=True)
        return None, 60, outcome
    app.state.save('switcher_health', {
        'observed_at': time.time(), 'state': 'running',
        'reason': report['reason'], 'threshold': app.config['threshold'],
        'compatibility': getattr(app, 'compatibility', {})})
    outcome = (report['active'], report['target'], report['reason'],
               report['switched'], tuple(sorted(report['errors'].items())))
    if outcome != last_outcome:
        print(json.dumps({k: report[k] for k in (
            'observed_at', 'active', 'target', 'reason', 'switched', 'errors')}), flush=True)
    return report, app.next_delay(time.time()), outcome


def measure_and_review(app, measurement, report, delay):
    """Return the next delay. Measurement uses no-UI reads and encrypted saved bundles."""
    if report is None and measurement.enabled():
        try:
            report = observe(app)
            delay = max(delay, report.get('retry_after_seconds', 0))
        except (SwitcherError, KeychainError, OSError, ValueError) as exc:
            from api import ApiError
            if isinstance(exc, ApiError):
                delay = max(delay, exc.retry_after)
            app.state.save('measurement_error', {
                'observed_at': time.time(), 'type': type(exc).__name__,
                'http_status': getattr(exc, 'status', None),
                'retry_after_seconds': getattr(exc, 'retry_after', None)})
    if report is not None:
        try:
            measurement.record(report)
            app.state.save('measurement_error', {})
        except (SwitcherError, OSError, ValueError) as exc:
            # Measurement failures must not interrupt an account swap.
            print(json.dumps({'measurement_error': type(exc).__name__}), flush=True)
    try:
        review_if_due(app.state)
    except (SwitcherError, OSError, ValueError) as exc:
        print(json.dumps({'monitoring_error': type(exc).__name__}), flush=True)
    return delay


def record_if_switched(state, report):
    """Each session's Stop/StopFailure hook restarts it after this time (refresh_hook.py)."""
    if report is not None and report['switched']:
        record_switch(state, report['observed_at'])


def run(app, apply):
    stopping = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopping.set())
    last_outcome = None
    measurement = Measurement(app.state, Path(app.config['config_home']) / 'projects')
    with app.state.lock('daemon'):
        app.state.save('service_settings', {
            'loaded_at': time.time(), 'threshold': app.config['threshold'],
            'poll_seconds': app.config['poll_seconds'],
            'supported_version': app.config['supported_version']})
        while not stopping.is_set():
            requested = app.state.load('preference')
            report, delay, last_outcome = tick_once(app, apply, last_outcome)
            record_if_switched(app.state, report)
            deadline = time.monotonic() + measure_and_review(app, measurement, report, delay)
            while not stopping.is_set() and time.monotonic() < deadline:
                if app.state.load('preference') != requested:
                    # A halted service must keep its backoff even when a request is pending.
                    if (not app.state.load('halt')
                            and time.time() >= app.state.load('runtime').get('retry_after', 0)):
                        break
                stopping.wait(min(2, max(0, deadline - time.monotonic())))


def install_service(app):
    roster = app.state.load('roster')
    if not all(roster.get(e, {}).get('registered') for e in app.accounts):
        raise SwitcherError('Enroll both accounts before installing the background service')
    app.check_version()
    # A read-only preflight must work before installing an unattended writer.
    report = app.tick(apply=False)
    if report['errors'] or report['target'] is None:
        raise SwitcherError('Both account metadata checks must succeed before service installation')
    directory = Path.home() / 'Library/LaunchAgents'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f'{LABEL}.plist'
    if destination.exists() or destination.is_symlink():
        raise SwitcherError('Service plist already exists; uninstall it before reinstalling')
    data = {'Label': LABEL, 'ProgramArguments': [sys.executable, str(Path(__file__).resolve()),
            '--state-dir', str(app.state.root.resolve()), 'run', '--apply'],
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 60,
            'ProcessType': 'Background', 'WorkingDirectory': str(app.state.root.resolve()),
            'StandardOutPath': str(app.state.root / 'service.log'),
            'StandardErrorPath': str(app.state.root / 'service-error.log')}
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        plistlib.dump(data, stream)
    result = subprocess.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(destination)],
                            capture_output=True, timeout=10)
    if result.returncode:
        destination.unlink()
        raise SwitcherError(f'launchctl bootstrap failed: status={result.returncode}')
    print('Background service installed and started.')


def uninstall_service():
    destination = Path.home() / f'Library/LaunchAgents/{LABEL}.plist'
    if not destination.exists() or destination.is_symlink():
        raise SwitcherError('Owned service plist was not found')
    result = subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'],
                            capture_output=True, timeout=10)
    if result.returncode not in (0, 3, 113):
        raise SwitcherError(f'launchctl bootout failed: status={result.returncode}')
    destination.unlink()
    print('Background service removed. Current Claude login and saved accounts are retained.')


def run_state_command(args, state):
    """Commands that need no account configuration. Return None for the rest."""
    if args.command == 'init':
        initialize(args, state)
    elif args.command == 'status':
        show_status(state)
    elif args.command == 'measure-status':
        print(json.dumps(summarize(state), indent=2))
    elif args.command == 'monitor-start':
        print(json.dumps(start_monitoring(state, args.days), indent=2))
    elif args.command == 'monitor-status':
        print(json.dumps(state.load('monitoring'), indent=2))
    elif args.command == 'service-uninstall':
        uninstall_service()
    elif args.command == 'resume':
        # Clear a Keychain halt only after confirming `security find-generic-password` works.
        print(json.dumps({'cleared': state.load('halt') or None}, indent=2))
        state.save('halt', {})
    else:
        return None
    return 0


def enroll(app, role):
    # Preserve the outgoing account before official login rotates the live store.
    _, account = app.live.read()
    app.capture(account['emailAddress'])
    result = subprocess.run([app.config['claude_executable'], 'auth', 'login',
                             '--email', app.config[role]])
    if result.returncode:
        raise SwitcherError('Official Claude login did not complete; saved account is retained')
    expected = app.config[role]
    identity = read_json(app.live.config).get('oauthAccount', {})
    if identity.get('emailAddress') != expected:
        raise SwitcherError(
            f'Browser signed into a different account; expected {expected}. '
            'Retry using a separate browser session.')
    if account['emailAddress'] != expected:
        # Open sessions keep the outgoing login in memory until they restart.
        record_switch(app.state, time.time())
    try:
        app.capture(expected)
    except KeychainError:
        raise SwitcherError(
            'Login completed. Run authorize once to enroll the newly saved Keychain login.') from None
    print(f'Enrolled {role} account. No logout was used.')


def doctor(app):
    app.check_version()
    _, account = app.live.read()
    registered = {e: app.vault.read(e) is not None for e in app.accounts}
    print(json.dumps({'version': app.compatibility['version'], 'keychain_no_ui': 'ok',
                      'active': account['emailAddress'], 'registered': registered}, indent=2))
    return 0 if all(registered.values()) else 1


def run_app_command(args, state, app):
    if args.command == 'authorize':
        # Only this explicit, manually invoked command may ask macOS for access.
        _, account = app.live.read()
        app.capture(account['emailAddress'])
        print('Current account enrolled. Run doctor to verify access without a prompt.')
    elif args.command == 'capture':
        app.capture(app.config[args.role])
        print(f'Enrolled {args.role} account.')
    elif args.command == 'enroll':
        enroll(app, args.role)
    elif args.command == 'doctor':
        return doctor(app)
    elif args.command == 'once':
        report = app.tick(apply=args.apply)
        record_if_switched(state, report)
        print(json.dumps(report, indent=2))
    elif args.command == 'measure-once':
        with state.lock('daemon'):
            measurement = Measurement(state, Path(app.config['config_home']) / 'projects')
            print(json.dumps(measurement.record(observe(app)), indent=2))
    elif args.command == 'run':
        run(app, args.apply)
    elif args.command == 'service-install':
        install_service(app)
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    check_environment()
    state = State(args.state_dir)
    code = run_state_command(args, state)
    if code is not None:
        return code
    if not state.load('config'):
        raise SwitcherError('Run init first')
    app = build(state, allow_interaction=args.command == 'authorize')
    return run_app_command(args, state, app)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SwitcherError, KeychainError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        # Unexpected payloads and OS errors must never print a credential-bearing repr.
        print('Operation failed. Check local configuration and permissions; details redacted.',
              file=sys.stderr)
        sys.exit(1)
