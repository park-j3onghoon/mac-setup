#!/usr/bin/env python3
"""A two-account Claude Code switcher, with no third-party Python packages."""

import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

from api import Anthropic, ApiError
from compatibility import FAILURE as COMPATIBILITY_FAILURE
from compatibility import IncompatibleLayout
from macos import Keychain, KeychainError, SavedCredentialError, TransientKeychainError, Vault, system_awake
from measurement import Measurement, observe, summarize
from monitoring import review_if_due, start as start_monitoring
from refresh import record_switch
from service import Switcher, refresh_generation
from storage import LiveClaude, LockBusy, State, SwitcherError, email_key, fingerprint, read_json


AUDITED_VERSION = '2.1.323'
LABEL = 'local.claude-account-switcher'
HALT_POLL_SECONDS = 300
DEFAULT_STATE = Path(__file__).resolve().parents[2] / 'private/claude/account-switcher'
ENROLL_SECONDS = 300
LOG_BYTES = 1024 * 1024


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    commands = root.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init', help='create non-secret local settings')
    init.add_argument('--primary', required=True)
    init.add_argument('--fallback', required=True)
    init.add_argument('--threshold', type=float, default=90)
    for name in ('status', 'doctor', 'authorize', 'service-install', 'service-uninstall',
                 'measure-once', 'measure-status', 'monitor-status', 'resume', 'restore-enrollment'):
        commands.add_parser(name)
    migration = commands.add_parser('migrate-vault')
    migration.add_argument('--from-state-dir', type=Path, required=True)
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
    # cmux can put a temporary command shim first on PATH; launchd must outlive it.
    native = Path.home() / '.local/bin/claude'
    executable = str(native) if native.is_file() else shutil.which('claude')
    if not executable:
        raise SwitcherError('Claude Code executable was not found')
    config = {'schema': 1, 'primary': email_key(args.primary), 'fallback': email_key(args.fallback),
              'threshold': args.threshold, 'poll_seconds': 60, 'settle_seconds': 45,
              'supported_version': AUDITED_VERSION,
              'claude_executable': str(Path(executable).absolute()),
              'config_home': str(Path.home() / '.claude'),
              'config_path': str(Path.home() / '.claude.json')}
    from service import validate_config
    validate_config(config)
    with state.lock(blocking=True):
        if (state.root / 'config.json').exists():
            raise SwitcherError('Configuration already exists; init never overwrites it')
        state.save('config', config)
    print('Initialized local settings. No credential was changed.')


def saved_namespace(data):
    value = data.get('namespace')
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{16}', value):
        raise SwitcherError('Invalid saved vault namespace')
    return value


def vault_namespace(state, previous_root=None):
    with state.lock('namespace', blocking=True):
        saved = state.load('vault_namespace')
        if saved:
            namespace = saved_namespace(saved)
            if previous_root is None:
                return namespace
        source = (previous_root or state.root).expanduser().resolve()
        candidate = hashlib.sha256(str(source).encode()).hexdigest()[:16]
        if previous_root is not None and (source / 'vault_namespace.json').exists():
            candidate = saved_namespace(read_json(source / 'vault_namespace.json'))
        if previous_root is not None:
            keychain = Keychain(False)
            config = state.load('config')
            names = set(state.load('roster')) | {'__transaction__'}
            names.update(config[key] for key in ('primary', 'fallback') if key in config)
            def populated(namespace):
                vault = Vault(keychain, namespace)
                return any(vault.read(name) is not None for name in names)
            if saved and namespace != candidate and populated(namespace):
                raise SwitcherError('Destination vault already contains enrolled credentials')
            if not populated(candidate):
                raise SwitcherError('No enrolled credentials found for the old state directory')
        state.save('vault_namespace', {'namespace': candidate})
        return candidate


def build(state, allow_interaction=False):
    config = state.load('config')
    namespace = vault_namespace(state)
    vault = Vault(Keychain(allow_interaction), namespace)
    live = LiveClaude(config['config_home'], config['config_path'], vault)
    return Switcher(config, state, live, vault, Anthropic())


def show_status(state):
    print(json.dumps({'config': state.load('config'), 'accounts': state.load('roster'),
                      'runtime': state.load('runtime'),
                      'last_report': state.load('last_report'),
                      'last_observation': state.load('last_observation'),
                      'halt': state.load('halt'),
                      'service_settings': state.load('service_settings'),
                      'monitoring': state.load('monitoring')}, indent=2))


def halts_keychain_work(exc, awake=system_awake):
    """A failed Keychain read can mean a prompt in every Claude session; never retry it on a timer.

    The compatibility check also fails when it runs in a dark wake: on 2026-11-14 14:37 the
    first check of a freshly updated Claude Code ran one second into a lid-closed wake, with no
    prompt (no SecurityAgent), and halted the service for a day. That case retries instead.
    """
    if isinstance(exc, (SavedCredentialError, TransientKeychainError)):
        return False
    if isinstance(exc, (KeychainError, IncompatibleLayout)):
        return True
    return str(exc) == COMPATIBILITY_FAILURE and awake()


def measurement_deadline(state):
    try:
        error = state.load('measurement_error')
        value = error.get('retry_at', 0)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError('Invalid measurement retry deadline')
        return error, value
    except (SwitcherError, OSError, ValueError, OverflowError) as exc:
        print(json.dumps({'measurement_state_error': type(exc).__name__}), flush=True)
        return {}, 0


def tick_once(app, apply, last_outcome):
    """Return (report, delay, outcome). While halted, nothing reads Claude's login item."""
    health = 'switcher_health' if apply else 'observer_health'
    halt = app.state.load('halt')
    if halt:
        app.state.save(health, {
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
        app.state.save(health, {
            'observed_at': time.time(), 'state': 'blocked',
            'error_type': type(exc).__name__, 'reason': str(exc),
            'operation': getattr(exc, 'operation', None), 'threshold': app.config['threshold']})
        if apply and halts_keychain_work(exc):
            app.state.save('halt', {'observed_at': time.time(),
                                    'error_type': type(exc).__name__, 'reason': str(exc)})
            print(json.dumps({'halted': str(exc)}), flush=True)
        return None, max(60, getattr(exc, 'retry_after', 0)), outcome
    app.state.save(health, {
        'observed_at': time.time(), 'state': 'running',
        'reason': report['reason'], 'threshold': app.config['threshold'],
        'error_stages': report.get('error_stages', {}),
        'compatibility': getattr(app, 'compatibility', {})})
    outcome = (report['active'], report['target'], report['reason'],
               report['switched'], tuple(sorted(report['errors'].items())))
    if outcome != last_outcome:
        print(json.dumps({k: report[k] for k in (
            'observed_at', 'active', 'target', 'reason', 'switched', 'errors')}), flush=True)
    if report['reason'] == 'waiting_for_retry_after':
        return report, max(2, app.state.load('runtime')['retry_after'] - time.time()), outcome
    if report['reason'] == 'waiting_for_operation':
        return report, 5, outcome
    return report, app.next_delay(time.time()), outcome


def measure_and_review(app, measurement, report, delay):
    """Return the next delay. Measurement uses no-UI reads and encrypted saved bundles."""
    error, retry_at = measurement_deadline(app.state)
    remaining = max(app.state.load('runtime').get('retry_after', 0),
                    retry_at) - time.time()
    if report and report.get('reason') == 'waiting_for_retry_after':
        report = None
    if report and report.get('reason') == 'waiting_for_operation':
        return delay
    if report is None and remaining <= 0:
        try:
            report = observe(app) if measurement.enabled() else None
            retry = report.get('retry_after_seconds', 0) if report else 0
            if retry:
                error = {'observed_at': time.time(), 'stage': 'observe',
                         'retry_after_seconds': retry, 'retry_at': time.time() + retry}
                save_measurement_error(app.state, error)
                delay = max(delay, retry)
        except (SwitcherError, KeychainError, OSError, ValueError) as exc:
            if isinstance(exc, ApiError):
                delay = max(delay, exc.retry_after)
            save_measurement_error(app.state, {
                'observed_at': time.time(), 'type': type(exc).__name__,
                'http_status': getattr(exc, 'status', None),
                'stage': 'observe', 'retry_at': time.time() + getattr(exc, 'retry_after', 0),
                'retry_after_seconds': getattr(exc, 'retry_after', None)})
    if report is not None:
        try:
            if (measurement.record(report) is not None and error
                    and error.get('retry_at', 0) <= time.time()):
                save_measurement_error(app.state, {})
        except (SwitcherError, OSError, ValueError) as exc:
            # Measurement failures must not interrupt an account swap.
            print(json.dumps({'measurement_error': type(exc).__name__}), flush=True)
            save_measurement_error(app.state, {'observed_at': time.time(), 'stage': 'record',
                                               'type': type(exc).__name__,
                                               'retry_at': error.get('retry_at', 0)})
    try:
        review_if_due(app.state)
        measurement.prune(time.time())
    except (SwitcherError, OSError, ValueError) as exc:
        print(json.dumps({'monitoring_error': type(exc).__name__}), flush=True)
    return delay


def save_measurement_error(state, details):
    try:
        state.save('measurement_error', details)
    except (SwitcherError, OSError, ValueError) as exc:
        print(json.dumps({'measurement_state_error': type(exc).__name__}), flush=True)


def rotate_logs(state):
    # launchd retains open descriptors, so preserve the active inode when rotating.
    for name in ('service.log', 'service-error.log'):
        path = state.root / name
        try:
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            continue
        with os.fdopen(fd, 'r+b') as log:
            size = os.fstat(fd).st_size
            if size <= LOG_BYTES:
                continue
            log.seek(size - LOG_BYTES)
            with tempfile.NamedTemporaryFile(dir=state.root, delete=False) as archive:
                try:
                    archive.write(log.read(LOG_BYTES))
                    archive.flush()
                    os.fsync(archive.fileno())
                    os.replace(archive.name, path.with_suffix('.log.1'))
                finally:
                    Path(archive.name).unlink(missing_ok=True)
            log.truncate(0)
            for descriptor in (1, 2):
                if os.path.samestat(os.fstat(fd), os.fstat(descriptor)):
                    os.lseek(descriptor, 0, os.SEEK_END)


def writer_directory(app):
    return getattr(app.vault, 'writer_lock_directory', app.live.home)


def writer_status(app):
    directory = writer_directory(app)
    name = 'claude-account-writer'
    try:
        with app.state.lock(name, directory=directory):
            return 'waiting_for_writer'
    except LockBusy:
        try:
            owner = read_json(directory / (name + '.lock'))
        except (OSError, ValueError, SwitcherError):
            return 'waiting_for_writer'
        return ('writer_running' if owner.get('state_dir') == str(app.state.root.resolve())
                else 'different_writer')


def reading_requested(app, since):
    """Whether the dashboard's 지금 확인 asked for a usage reading after `since` (usage_request.json)."""
    try:
        value = app.state.load('usage_request').get('requested_at')
    except (SwitcherError, OSError, ValueError):
        return False
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value > since


def run(app, apply):
    stopping = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopping.set())
    last_outcome = None
    measurement = Measurement(app.state, Path(app.config['config_home']) / 'projects')
    mode_lock = (app.state.lock('claude-account-writer', directory=writer_directory(app))
                 if apply else app.state.lock('observer'))
    with mode_lock as locked, (app.state.lock('daemon') if apply else contextlib.nullcontext()):
        app.writer_daemon = apply
        if apply:
            with os.fdopen(os.dup(locked), 'w') as stream:
                stream.seek(0)
                stream.truncate()
                json.dump({'state_dir': str(app.state.root.resolve()), 'pid': os.getpid()}, stream)
        next_lock_cleanup = 0
        app.state.save('service_settings' if apply else 'observer_settings', {
            'loaded_at': time.time(), 'threshold': app.config['threshold'],
            'mode': 'apply' if apply else 'observe',
            'poll_seconds': app.config['poll_seconds'],
            'supported_version': app.config['supported_version']})
        while not stopping.is_set():
            if apply:
                try:
                    rotate_logs(app.state)
                except OSError as exc:
                    print(json.dumps({'log_rotation_error': type(exc).__name__}), flush=True)
            if time.monotonic() >= next_lock_cleanup:
                app.state.prune_restart_locks()
                next_lock_cleanup = time.monotonic() + 3600
            try:
                requested = app.preference()
            except SwitcherError:
                requested = None
            ticked_at = time.time()
            report, delay, last_outcome = tick_once(app, apply, last_outcome)
            if apply:
                delay = measure_and_review(app, measurement, report, delay)
            deadline = time.monotonic() + delay
            while not stopping.is_set() and time.monotonic() < deadline:
                try:
                    changed = app.preference() != requested
                except SwitcherError:
                    changed = False
                if changed or reading_requested(app, ticked_at):
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
    if report['errors'] or set(report['usage']) != set(app.accounts):
        raise SwitcherError('Both account metadata checks must succeed before service installation')
    directory = Path.home() / 'Library/LaunchAgents'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f'{LABEL}.plist'
    data = {'Label': LABEL, 'ProgramArguments': [sys.executable, str(Path(__file__).resolve()),
            '--state-dir', str(app.state.root.resolve()), 'run', '--apply'],
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 60,
            'ProcessType': 'Background', 'WorkingDirectory': str(app.state.root.resolve()),
            'StandardOutPath': str(app.state.root.resolve() / 'service.log'),
            'StandardErrorPath': str(app.state.root.resolve() / 'service-error.log')}
    domain = f'gui/{os.getuid()}'
    with app.state.lock('.' + LABEL + '-install', blocking=True, directory=directory):
        if writer_status(app) == 'different_writer':
            raise SwitcherError('Another configuration owns the active account writer')
        if destination.is_symlink():
            raise SwitcherError('Service plist path is a symlink')
        repair = False
        if destination.exists():
            existing = destination.read_bytes()
            intended = plistlib.dumps(data)
            info = destination.stat()
            repair = (len(existing) < len(intended) and intended.startswith(existing)
                      and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600)
            if existing != intended and not repair:
                raise SwitcherError('Existing service plist belongs to another configuration')
            if subprocess.run(['/bin/launchctl', 'print', f'{domain}/{LABEL}'],
                              capture_output=True, timeout=10).returncode == 0:
                if repair:
                    raise SwitcherError('Loaded service has an incomplete plist; check its registration')
                print(f'Background service already installed: {writer_status(app)}')
                return
        if repair or not destination.exists():
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
                try:
                    plistlib.dump(data, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                    if repair:
                        os.replace(stream.name, destination)
                    else:
                        os.link(stream.name, destination)
                finally:
                    Path(stream.name).unlink(missing_ok=True)
        result = subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(destination)],
                                capture_output=True, timeout=10)
        if result.returncode and subprocess.run(
                ['/bin/launchctl', 'print', f'{domain}/{LABEL}'],
                capture_output=True, timeout=10).returncode:
            raise SwitcherError(f'launchctl bootstrap failed: status={result.returncode}')
    print(f'Background service installed: {writer_status(app)}')


def uninstall_service(state):
    destination = Path.home() / f'Library/LaunchAgents/{LABEL}.plist'
    if not destination.parent.is_dir():
        raise SwitcherError('Owned service plist was not found')
    with state.lock('.' + LABEL + '-install', blocking=True, directory=destination.parent):
        _remove_service(state, destination)


def _remove_service(state, destination):
    if not destination.exists() or destination.is_symlink():
        raise SwitcherError('Owned service plist was not found')
    with destination.open('rb') as stream:
        data = plistlib.load(stream)
    arguments = data.get('ProgramArguments', [])
    if (data.get('Label') != LABEL or len(arguments) != 6
            or arguments[1] != str(Path(__file__).resolve())
            or arguments[2:] != ['--state-dir', str(state.root.resolve()), 'run', '--apply']):
        raise SwitcherError('Service belongs to another switcher configuration')
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
        uninstall_service(state)
    elif args.command == 'migrate-vault':
        with state.lock('daemon'), state.lock():
            vault_namespace(state, args.from_state_dir)
    elif args.command == 'resume':
        # Clear a Keychain halt only after confirming `security find-generic-password` works.
        print(json.dumps({'cleared': state.load('halt') or None}, indent=2))
        state.save('halt', {})
    else:
        return None
    return 0


def enroll(app, role):
    # Hold only the switcher's operation lock while the browser is open. Claude
    # must remain free to acquire its native credential locks to finish login.
    with app.state.lock():
        app.prepare_write(app.vault.read('__transaction__'))
        _, account = app.live.read()
        previous = app.capture_locked(account['emailAddress'])
        expected = app.config[role]
        intent = {'enrollment': expected, 'previous': previous}
        app.vault.write('__transaction__', intent)
        try:
            result = subprocess.run([app.config['claude_executable'], 'auth', 'login',
                                     '--email', expected], timeout=ENROLL_SECONDS)
        except subprocess.TimeoutExpired:
            app.finish_enrollment_intent(intent)
            raise SwitcherError('Official Claude login timed out; retry enrollment') from None
        try:
            actual = app.finish_enrollment_intent(intent)
        except KeychainError:
            if account['emailAddress'] != expected:
                record_switch(app.state, time.time())
            raise SwitcherError(
                'Login completed. Run authorize once to enroll the newly saved Keychain login.') from None
        if result.returncode or actual != expected:
            raise SwitcherError(f'Login did not complete for {expected} or selected a different account')
    print(f'Enrolled {role} account. No logout was used.')


def doctor(app):
    app.check_version()
    _, account = app.live.read()
    registered = {}
    for email in app.accounts:
        try:
            bundle = app.vault.read(email)
            if (not isinstance(bundle, dict) or not isinstance(bundle.get('oauth'), dict)
                    or not isinstance(bundle.get('account'), dict)):
                raise SwitcherError('Invalid saved credential')
            fingerprint(bundle['oauth'])
            if (app.account_key(bundle['account'].get('emailAddress')) != email
                    or not bundle['account'].get('accountUuid') or not refresh_generation(bundle)):
                raise SwitcherError('Incomplete saved credential')
            app.verify_identity(bundle)
        except (SwitcherError, KeychainError, ValueError):
            registered[email] = False
        else:
            registered[email] = True
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
    elif args.command == 'restore-enrollment':
        with state.lock():
            intent = app.vault.read('__transaction__')
            if not intent or 'enrollment' not in intent:
                raise SwitcherError('No pending enrollment to restore')
            _, current = app.live.read()
            app.check_version(recovery_email=current.get('emailAddress'))
            app.finish_enrollment_intent(intent, restore=True)
    elif args.command == 'doctor':
        return doctor(app)
    elif args.command == 'once':
        report = app.tick(apply=args.apply)
        print(json.dumps(report, indent=2))
    elif args.command == 'measure-once':
        with state.lock('daemon'):
            measurement = Measurement(state, Path(app.config['config_home']) / 'projects')
            now = time.time()
            if max(measurement_deadline(state)[1], state.load('runtime').get('retry_after', 0)) > now:
                print('null')
                return 0
            if not measurement.enabled(now):
                print('null')
                return 0
            measurement.resume_manual_interval(now)
            row = measurement.record(observe(app))
            measurement.save_manual_interval(row)
            print(json.dumps(row, indent=2))
    elif args.command == 'run':
        run(app, args.apply)
    elif args.command == 'service-install':
        install_service(app)
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    state = State(args.state_dir)
    if args.command == 'migrate-vault':
        check_environment()
    code = run_state_command(args, state)
    if code is not None:
        return code
    check_environment()
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
