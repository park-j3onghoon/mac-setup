"""Recovery at the boundaries between launchers, supervisor, and running terminals."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
import os
from pathlib import Path
import plistlib
import runpy
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import launcher
from policy import UsageUnavailable
import profiles
import rpc
import runtime
import service
import state
import supervisor


def fixture_reload_process():
    home, pid, script, lock = sys.argv[1:]
    home = Path(home)

    def launchctl(command, **kwargs):
        if command[0] != '/bin/launchctl' or command[1] not in ('print', 'bootout', 'bootstrap'):
            raise AssertionError(command)
        with (home / 'launch-actions').open('a') as log:
            log.write(command[1] + '\n')
        current = f'state = running\npid = {pid}\n' if (home / 'live').exists() else 'state = not running'
        return subprocess.CompletedProcess(command, 0, stdout=current)

    with patch.object(Path, 'home', return_value=home), patch.object(subprocess, 'run', side_effect=launchctl):
        sys.argv = [script, '--finish-reload', lock]
        runpy.run_path(script, run_name='__main__')


class SwitcherBoundaryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.rt = runtime.Runtime({}, self.home)
        self.rt.active = 'company'
        self.now = 1000
        self.accounts = {
            name: {'used_percent': 10, 'observed_at': 1000, 'windows': {}} for name in ('company', 'personal')
        }

    def monitor(self, rt, saved, profiles_, ticks, wait=None):
        stop = Mock()
        stop.is_set.side_effect = [False] * ticks + [True]

        def tick(_):
            self.now += 2
            if wait:
                wait(self.now)

        stop.wait.side_effect = tick
        with (
            patch.object(supervisor, 'time', Mock(time=lambda: self.now)),
            patch.object(supervisor, 'collect', return_value=(self.accounts, {})) as collect,
            patch.object(supervisor, 'RUNTIME', self.home),
            patch.object(supervisor, 'save'),
            patch.object(supervisor, 'preference', return_value={}),
        ):
            supervisor.monitor(rt, profiles_, stop, saved)
        return collect.call_count

    def monitor_runtime(self):
        self.rt.running = Mock(return_value=True)
        self.rt.observe_account = Mock()
        self.rt.release_subscriptions = Mock(return_value=True)
        self.rt.continue_limited = Mock(return_value=True)
        self.rt.select = Mock(return_value=True)
        return self.rt

    def register(self, *names):
        with (
            patch.object(launcher, 'RUNTIME', self.home),
            patch.object(launcher, 'raise_file_limit'),
            patch.object(launcher, 'load_settings', return_value=profiles.DEFAULT_SETTINGS),
            patch.object(profiles, 'credentials', return_value={'chatgptAccountId': 'requested'}),
        ):
            for name in names:
                self.assertEqual(launcher.main(['--account-register', name]), 0)

    def test_two_profiles_register_before_one_poll(self):
        self.register('company', 'personal')
        profiles_ = {name: Mock() for name in self.accounts}
        self.monitor(self.monitor_runtime(), {}, profiles_, 2)
        for profile in profiles_.values():
            profile.register.assert_called_once_with('requested')

    def test_transient_registration_retries_and_mismatch_is_final(self):
        self.register('company', 'personal')
        profiles_ = {name: Mock() for name in self.accounts}
        profiles_['company'].register.side_effect = [UsageUnavailable('temporarily unreadable'), None]
        profiles_['personal'].register.side_effect = profiles.RegistrationMismatch('workspace changed')
        saved = {}
        self.monitor(self.monitor_runtime(), saved, profiles_, 5)
        self.assertEqual(profiles_['company'].register.call_count, 2)
        self.assertEqual(profiles_['personal'].register.call_count, 1)
        self.assertEqual(saved['registration_errors'], {'personal': 'workspace changed'})

    def test_observation_gap_preserves_external_change(self):
        rt = self.monitor_runtime()

        def observe():
            rt.active = None if self.now == 1000 else 'personal'
            if rt.active is None:
                raise UsageUnavailable('unreachable')

        rt.observe_account.side_effect = observe
        saved = {'active': 'company'}
        with patch.object(supervisor, 'poll_delay', return_value=2):
            self.monitor(rt, saved, {}, 2)
        self.assertEqual(saved['last_external_change']['from'], 'company')
        self.assertEqual(saved['last_external_change']['to'], 'personal')

    def test_limit_notification_triggers_fresh_poll(self):
        rt = self.monitor_runtime()

        def event(now):
            if now == 1002:
                rt.activity(
                    'turn/completed',
                    {
                        'threadId': 't',
                        'turn': {'status': 'failed', 'error': {'codexErrorInfo': 'usageLimitExceeded'}},
                    },
                )

        self.assertEqual(self.monitor(rt, {}, {}, 3, event), 2)
        self.assertEqual(rt.continue_limited.call_count, 2)

    def limited(self, queue_failure=False):
        turn = ['original']
        client = Mock()
        queues = [0]

        def request(method, params):
            if method == 'thread/read':
                return {'thread': {'status': {'type': 'idle'}}}
            if method == 'thread/turns/list':
                return {
                    'data': [
                        {'id': turn[0], 'status': 'failed', 'error': {'codexErrorInfo': 'usageLimitExceeded'}}
                    ]
                }
            if method == 'thread/queue/list':
                queues[0] += 1
                if queue_failure and queues[0] == 2:
                    raise UsageUnavailable('queue unavailable')
                return {'data': []}
            if method == 'thread/goal/get':
                return {'goal': None}
            self.assertEqual(method, 'turn/start')
            turn[0] += '-next'
            return {'turn': {'id': turn[0]}}

        client.request.side_effect = request
        self.rt.continuation_path = self.home / 'continuation-receipts.json'
        return client, turn

    def test_unsent_continuation_has_no_receipt(self):
        client, turn = self.limited(queue_failure=True)
        with self.assertRaises(UsageUnavailable):
            self.rt.continue_thread('t', client)
        self.assertEqual(state.load(self.rt.continuation_path), {})
        self.rt.continue_thread('t', client)
        self.assertEqual(turn, ['original-next'])

    def test_failed_automatic_turn_waits_for_new_quota_or_account(self):
        client, turn = self.limited()
        self.rt.continue_thread('t', client)
        self.rt.continue_thread('t', client)
        self.assertEqual(turn, ['original-next'])
        self.assertEqual(state.load(self.home / 'continuation-followups.json')['t'][0], turn[0])
        self.rt.quota_periods['company'] = 1002
        self.rt.continue_thread('t', client)
        self.assertEqual(turn, ['original-next-next'])
        self.rt.active = 'personal'
        self.rt.continue_thread('t', client)
        self.assertEqual(turn, ['original-next-next-next'])

    def exec_case(self, states):
        homes = {name: self.home / name for name in self.accounts}
        for path in homes.values():
            path.mkdir(exist_ok=True)
            (path / 'auth.json').touch()
        samples = iter(states)
        last = [states[-1]]

        def read(path=None):
            if path is not None:
                return state.load(path)
            last[0] = next(samples, last[0])
            sample = dict(last[0])
            if sample.pop('fresh', False):
                sample['usage_request_at'] = state.load(self.home / 'usage-request.json')['requested_at']
            return sample

        def sleep(dt):
            self.now += dt

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(launcher, 'load_settings', return_value=replace(profiles.DEFAULT_SETTINGS, homes=homes)),
            patch.object(launcher, 'RUNTIME', self.home),
            patch.object(launcher, 'raise_file_limit'),
            patch.object(launcher, 'load', side_effect=read),
            patch.object(launcher, 'direct_usages', return_value={'company': 5}) as fallback,
            patch.object(
                launcher, 'time', Mock(time=lambda: self.now, monotonic=lambda: self.now, sleep=sleep)
            ),
            patch.object(service, 'running', side_effect=lambda s: s.get('status') == 'ready'),
            patch.object(launcher.os, 'execve') as exe,
            redirect_stderr(StringIO()),
        ):
            launcher.main(['exec', 'fixture'])
        return fallback.call_count, Path(exe.call_args.args[-1]['CODEX_HOME']).name

    def test_exec_while_draining_uses_direct_usage(self):
        self.assertEqual(self.exec_case([{'status': 'ready', 'upgrade_status': 'draining'}]), (1, 'company'))
        self.assertEqual(self.now, 1000)

    def test_exec_stops_waiting_as_soon_as_supervisor_exits(self):
        self.assertEqual(self.exec_case([{'status': 'ready'}, {'status': 'stopped'}]), (1, 'company'))
        self.assertLess(self.now, 1001)

    def test_exec_accepts_fresh_approval_after_two_slow_polls(self):
        states = [{'status': 'ready'}] * 225 + [{'status': 'ready', 'fresh': True, 'accounts': self.accounts}]
        self.assertEqual(self.exec_case(states), (0, 'company'))
        self.assertGreater(self.now, 1030)
        self.assertLess(self.now, 1150)

    def test_clock_rollback_requires_new_acknowledgement(self):
        self.assertEqual(
            self.exec_case(
                [
                    {'status': 'ready', 'usage_request_at': 2000, 'accounts': self.accounts},
                    {
                        'status': 'ready',
                        'fresh': True,
                        'accounts': {'company': {'used_percent': 98}, 'personal': {'used_percent': 5}},
                    },
                ]
            ),
            (0, 'personal'),
        )
        self.assertGreater(state.load(self.home / 'usage-request.json')['requested_at'], 2000)

    def test_stopped_status_does_not_report_ready_or_waiting(self):
        buf = StringIO()
        with (
            patch.object(launcher, 'load', return_value={'status': 'ready', 'desired': 'company'}),
            patch.object(service, 'running', return_value=False),
            patch.object(launcher, 'read_snapshot', return_value=self.accounts['company']),
            redirect_stdout(buf),
        ):
            launcher.show_status()
        self.assertIn('service: stopped', buf.getvalue())
        self.assertNotIn('waiting for active work', buf.getvalue())

    def test_matching_cached_cli_when_installed_link_is_missing(self):
        cached = self.home / 'app-server-packages/1.2/bin/codex'
        cached.parent.mkdir(parents=True)
        cached.touch()
        cached.chmod(0o700)
        with (
            patch.object(launcher, 'RUNTIME', self.home),
            patch.object(launcher, 'BINARY', self.home / 'gone'),
            patch.object(launcher, 'server_version', return_value='1.2'),
        ):
            self.assertEqual(launcher.terminal_command(self.home / 'auto.sock')[0], str(cached))

    def test_direct_launcher_import_avoids_proxy_and_mask_tables(self):
        code = "import launcher,sys,unix_ws; assert 'idle' not in sys.modules; assert unix_ws.xor_table.cache_info().currsize==0"
        subprocess.run([sys.executable, '-B', '-c', code], cwd=Path(__file__).parent, check=True)

    def test_unmodified_cache_avoids_hash_and_same_size_edit_is_repaired(self):
        release = self.home / 'Caskroom/codex/1.0/bin'
        release.mkdir(parents=True)
        for name in ('codex', 'codex-code-mode-host', 'codex-exec-server'):
            (release / name).write_bytes(b'original')
            (release / name).chmod(0o700)
        cached = runtime.preserve_server_package(release / 'codex', self.home)
        with patch.object(runtime.hashlib, 'sha256', side_effect=AssertionError('unnecessary hash')):
            runtime.preserve_server_package(release / 'codex', self.home)
        cached.write_bytes(b'modified')
        runtime.preserve_server_package(release / 'codex', self.home)
        self.assertEqual(cached.read_bytes(), b'original')

    def test_paused_goal_allows_update_but_active_goal_blocks(self):
        with patch.object(runtime, 'loaded_threads', return_value=[('t', {'status': {'type': 'idle'}})]):
            for status, safe in [('paused', True), ('active', False)]:
                client = Mock()
                client.request.side_effect = [{'data': []}, {'data': []}, {'goal': {'status': status}}]
                self.assertEqual(all(self.rt.upgrade_checks(client)), safe)

    def test_adopted_logged_out_replacement_restores_checkpoint(self):
        self.rt.socket.touch()
        self.rt.active = None
        with (
            patch.object(runtime, 'prepare_home'),
            patch.object(runtime.socket, 'socket'),
            patch.object(runtime, 'peer_process', return_value=(100, 'start')),
            patch.object(self.rt, 'observe_account'),
            patch.object(self.rt, 'restore_account') as restore,
        ):
            self.rt.start(restore_account='personal')
        restore.assert_called_once_with('personal')

    def test_refresh_can_complete_during_a_slow_quota_read(self):
        entered, release, refreshed = threading.Event(), threading.Event(), threading.Event()
        auth = lambda _: {'chatgptAccountId': 'a', 'expires': 1e12, 'accessToken': 'fixture'}
        with patch.object(profiles, 'credentials', side_effect=auth):
            profile = profiles.Profile('company', self.home)
            profile.client = Mock(closed=False)

            def request(method, *args, **kwargs):
                if method == 'account/rateLimits/read':
                    entered.set()
                    release.wait(2)
                    return {'accountId': 'a', 'rateLimits': {'primary': {'usedPercent': 5}}}
                refreshed.set()
                return {}

            profile.client.request.side_effect = request
            with ThreadPoolExecutor(2) as pool:
                read = pool.submit(profile.usage)
                self.assertTrue(entered.wait(1))
                token = pool.submit(profile.tokens, force=True)
                try:
                    self.assertTrue(refreshed.wait(0.5))
                finally:
                    release.set()
                self.assertEqual(read.result()['used_percent'], 5)
                self.assertEqual(token.result()['chatgptAccountId'], 'a')

    def test_stdio_reader_sleeps_until_data_or_shutdown(self):
        client = rpc.Rpc.__new__(rpc.Rpc)
        client.closing = threading.Event()
        client.reader_wakeup = socket.socketpair()
        self.addCleanup(client.close_wakeup)
        client.process = Mock()
        fd, writer = os.pipe()
        self.addCleanup(os.close, fd)
        self.addCleanup(os.close, writer)
        client.process.stdout.fileno.return_value = fd
        entered = threading.Event()
        original = rpc.selectors.DefaultSelector.select

        def waiting(selector, *timeout):
            self.assertEqual(timeout, ())
            entered.set()
            return original(selector, *timeout)

        with patch.object(rpc.selectors.DefaultSelector, 'select', autospec=True, side_effect=waiting) as read:
            thread = threading.Thread(target=lambda: list(client.stdio_lines()))
            thread.start()
            self.assertTrue(entered.wait(1))
            client.wake_reader()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(read.call_count, 1)

    def test_repair_launchd_settings_only_after_live_supervisor_exits(self):
        dest = self.home / 'Library/LaunchAgents' / f'{service.LABEL}.plist'
        with patch.object(Path, 'home', return_value=self.home):
            with patch.object(
                service.subprocess, 'run', side_effect=[Mock(returncode=1), Mock(returncode=0)]
            ):
                service.install_service()
            stale = plistlib.loads(dest.read_bytes())
            stale['KeepAlive'] = False
            dest.write_bytes(plistlib.dumps(stale))

            real_popen = subprocess.Popen
            dummy = real_popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], stdin=subprocess.PIPE)
            self.addCleanup(dummy.wait, 4)
            self.addCleanup(dummy.stdin.close)
            (self.home / 'live').touch()
            children = []

            def spawn(command, **kwargs):
                helper = real_popen([sys.executable, '-B', '-c',
                                     'from test_switcher_boundaries import fixture_reload_process; fixture_reload_process()',
                                     str(self.home), str(dummy.pid), command[1], command[-1]],
                                    cwd=Path(__file__).parent, **kwargs)
                children.append(helper)
                self.addCleanup(helper.wait, 4)
                self.addCleanup(lambda: helper.terminate() if helper.poll() is None else None)
                return helper

            with patch.object(service.subprocess, 'run', return_value=Mock(
                    returncode=0, stdout=f'state = running\npid = {dummy.pid}')), \
                    patch.object(service.subprocess, 'Popen', side_effect=spawn):
                service.install_service()
                service.install_service()
            self.assertEqual(len(children), 1)
            actions = self.home / 'launch-actions'
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and (not actions.exists() or actions.read_text().count('print') < 2):
                time.sleep(.01)
            self.assertEqual(actions.read_text().splitlines(), ['print', 'print'])
            self.assertIsNone(children[0].poll())
            (self.home / 'live').unlink()
            dummy.stdin.close()
            dummy.wait(timeout=4)
            self.assertEqual(children[0].wait(timeout=6), 0)
            self.assertEqual(actions.read_text().splitlines()[-2:], ['bootout', 'bootstrap'])
            self.assertTrue(plistlib.loads(dest.read_bytes())['KeepAlive'])
            self.assertFalse(dest.with_suffix('.reload-pending').exists())
