"""Account, quota and receipt recovery with an isolated home and local RPC fixtures."""
from contextlib import ExitStack
import fcntl
import json
import os
import resource
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import profiles
import rpc
import runtime
import state
import supervisor
from policy import UsageUnavailable
from test_rpc import connect


class RuntimeStabilityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.profiles = {name: Mock(account_id=name) for name in ('company', 'personal')}
        for name, profile in self.profiles.items():
            profile.tokens.return_value = {'chatgptAccountId': name}
            profile.usage.return_value = {'used_percent': 1}
        self.rt = runtime.Runtime(self.profiles, self.home)
        self.rt.active = 'company'
        self.rt.client = Mock(closed=False)
        self.rt.continuation_path = self.home / 'continuation-receipts.json'
        self.addCleanup(self.rt.close)

    def test_first_binding_survives_restart_and_explicit_reregistration(self):
        available = {'company': 'workspace-A'}
        homes = {name: self.home / name for name in self.profiles}
        def auth(path):
            if path.name not in available:
                raise UsageUnavailable('not signed in')
            return {'chatgptAccountId': available[path.name], 'expires': 1e12}
        with patch.object(profiles, 'credentials', side_effect=auth):
            self.assertEqual(profiles.registered_accounts(homes, self.home), available)
            available['company'] = 'workspace-B'
            pinned = profiles.registered_accounts(homes, self.home)
            profile = profiles.Profile('company', homes['company'], bindings_dir=self.home, account_id=pinned['company'])
            with self.assertRaises(UsageUnavailable):
                profile.tokens()
            profile.register('workspace-B')
            self.assertEqual(profiles.registered_accounts(homes, self.home), available)

    def test_migration_prefers_acknowledged_binding_over_changed_file(self):
        request = {'profile': 'company', 'requested_at': 9, 'account_id': 'registered'}
        state.save(request, self.home / 'profile-registration-company.json')
        prior = {'registration_requests': {'company': 9}}
        with patch.object(profiles, 'credentials', return_value={'chatgptAccountId': 'changed'}):
            self.assertEqual(profiles.registered_accounts({'company': self.home}, self.home, prior),
                             {'company': 'registered'})

    def test_rejected_login_does_not_restart_previous_account(self):
        self.rt.client.request.side_effect = rpc.RpcRejected('login refused')
        with self.assertRaises(rpc.RpcRejected):
            self.rt.select('personal', force=True)
        self.assertEqual(self.rt.active, 'company')
        self.assertEqual(self.rt.client.request.call_count, 1)

    def test_external_account_survives_verification_failure_and_later_retry(self):
        external = {'account': {'type': 'chatgpt'}, 'workspaceRouting': {'chatgptAccountId': 'external'}}
        self.rt.client.request.side_effect = [{}, {'accountId': 'external'}, external, external]
        for _ in range(2):
            with self.assertRaises(UsageUnavailable):
                self.rt.select('personal', force=True)
        methods = [c.args[0] for c in self.rt.client.request.call_args_list]
        self.assertEqual(methods.count('account/login/start'), 1)
        self.assertIsNone(self.rt.active)

    def send_after_activity(self, method):
        transport = rpc.Rpc.__new__(rpc.Rpc)
        transport.closed, transport.websocket = False, Mock()
        transport.write_lock = threading.Lock()
        self.rt.activity('turn/started', {'threadId': 'work'})
        try:
            transport.send({'id': 1, 'method': method})
        finally:
            transport.websocket.send.assert_not_called()

    def test_new_activity_at_transport_write_cancels_login(self):
        self.rt.idle_ready = Mock(return_value=True)
        self.rt.login = lambda _: self.send_after_activity('account/login/start')
        self.assertFalse(self.rt.select('personal'))
        self.assertEqual(self.rt.active, 'company')

    def test_unloaded_and_deleted_threads_have_distinct_rpc_results(self):
        client, wire = connect()
        self.addCleanup(client.close)
        for text, deleted in [('thread not loaded: work', False), ('thread not found: work', True)]:
            def send(message, deadline=None):
                wire.incoming.put(json.dumps({'id': json.loads(message)['id'], 'error': {'message': text}}))
            wire.send = send
            with self.assertRaises(rpc.RpcRejected) as error:
                client.request('thread/read', {'threadId': 'work', 'includeTurns': False})
            self.assertEqual(error.exception.thread_missing, deleted)

    def limited_client(self, turn='failed', goal=None):
        client = Mock()
        def request(method, params, **kwargs):
            if method == 'thread/read':
                return {'thread': {'status': {'type': 'idle'}}}
            if method == 'thread/turns/list':
                return {'data': [{'id': turn, 'status': 'failed',
                                  'error': {'codexErrorInfo': 'usageLimitExceeded'}}]}
            if method == 'thread/queue/list':
                return {'data': []}
            if method == 'thread/goal/get':
                return {'goal': goal}
            if method == 'turn/start':
                return {'turn': {'id': 'new'}}
            raise AssertionError(method)
        client.request.side_effect = request
        return client

    def test_paused_goal_keeps_failed_turn_paused(self):
        client = self.limited_client(goal={'status': 'paused'})
        self.rt.continue_thread('work', client)
        self.assertNotIn('turn/start', [c.args[0] for c in client.request.call_args_list])

    def test_previous_receipt_stops_same_period_retry_after_restart(self):
        state.save({'work': {'turn_id': 'original', 'period': ['company', 0]}}, self.rt.continuation_path)
        self.rt.load_continuations()
        client = self.limited_client(turn='new')
        self.rt.continue_thread('work', client)
        self.assertNotIn('turn/start', [c.args[0] for c in client.request.call_args_list])
        self.assertEqual(self.rt.followups['work'], ['new', 'company', 0])
        self.rt.quota_periods['company'] = 3
        self.rt.continue_thread('work', client)
        self.assertIn('turn/start', [c.args[0] for c in client.request.call_args_list])

    def test_new_user_activity_at_transport_write_cancels_continuation(self):
        client = self.limited_client()
        normal = client.request.side_effect
        def race(method, params):
            if method == 'turn/start':
                self.send_after_activity(method)
            return normal(method, params)
        client.request.side_effect = race
        self.rt.continue_thread('work', client)
        self.assertEqual(state.load(self.rt.continuation_path), {})

    def test_receipt_and_directory_are_synced_before_submit(self):
        operations = []
        replace, sync = os.replace, os.fsync
        def write(fd):
            operations.append('fsync')
            sync(fd)
        def rename(src, dst):
            operations.append('rename')
            replace(src, dst)
        with patch.object(state.os, 'fsync', side_effect=write), patch.object(state.os, 'replace', side_effect=rename):
            self.rt.uncertain_continuations['work'] = 'old'
            self.rt.store_continuations()
        self.assertEqual(operations, ['fsync', 'rename', 'fsync'])

    def test_spending_block_only_clears_after_explicit_permission(self):
        def response(flag):
            limits = {'primary': {'usedPercent': 2}}
            if flag is not None:
                limits['spendControlReached'] = flag
            return state.snapshot({'rateLimits': limits})
        blocked = state.record(None, response(True))
        uncertain = state.record(blocked, response(None))
        self.assertEqual(uncertain['used_percent'], 100)
        self.assertEqual(state.record(uncertain, response(False))['used_percent'], 2)

    def test_partial_windows_retain_quota_period_and_reset_schedule(self):
        initial = {'windows': {'secondary': {'last_reset_confirmed_at': 990, 'resets_at': 1005}}}
        partial = state.record(initial, {'used_percent': 2, 'observed_at': 1000, 'windows': {}})
        self.assertEqual(max(w['last_reset_confirmed_at'] for w in state.known_windows(partial)), 990)
        self.assertEqual(state.poll_delay({'company': partial}, 'company', now=1000), 6)

    def test_bad_receipt_blocks_only_auto_continue_until_repaired(self):
        self.rt.continuation_path.write_text('{')
        self.rt.continuation_error = 'read failed'
        with self.assertRaises(UsageUnavailable):
            self.rt.continue_limited()
        self.rt.client.request.assert_not_called()
        state.save({'work': 'older-format'}, self.rt.continuation_path)
        self.rt.continue_batch = Mock(return_value=True)
        self.assertTrue(self.rt.continue_limited())
        self.assertEqual(self.rt.uncertain_continuations, {'work': 'older-format'})

    def test_blocked_goal_allows_idle_upgrade(self):
        self.rt.client.request.side_effect = [{'data': []}, {'data': []}, {'goal': {'status': 'blocked'}}]
        with patch.object(runtime, 'loaded_threads', return_value=[('work', {'status': {'type': 'idle'}})]):
            self.assertTrue(all(self.rt.upgrade_checks(self.rt.client)))

    def test_package_repairs_missing_ancillary_resource(self):
        release = self.home / 'Caskroom/codex/1.0'
        (release / 'bin').mkdir(parents=True)
        for name in ('codex', 'codex-code-mode-host', 'codex-exec-server'):
            executable = release / 'bin' / name
            executable.write_bytes(b'fixture')
            executable.chmod(0o700)
        (release / 'voice').write_bytes(b'voice')
        cached = runtime.preserve_server_package(release / 'bin/codex', self.home).parents[1]
        (cached / 'voice').unlink()
        runtime.preserve_server_package(release / 'bin/codex', self.home)
        self.assertEqual((cached / 'voice').read_bytes(), b'voice')

    def test_unsubscribe_retry_precedes_next_periodic_scan(self):
        client = self.rt.client
        client.request.side_effect = [{'data': ['work']}, {'thread': {'status': {'type': 'idle'}}},
                                      {'data': []}, {'goal': None}, {'data': []}, UsageUnavailable('slow')]
        with patch.object(runtime.time, 'monotonic', return_value=1000), self.assertRaises(UsageUnavailable):
            self.rt.release_subscriptions()
        client.request.side_effect = [{'thread': {'status': {'type': 'idle'}}},
                                      {'data': []}, {'goal': None}, {'data': []}, {}]
        with patch.object(runtime.time, 'monotonic', return_value=1006):
            self.assertTrue(self.rt.release_subscriptions())
        self.assertEqual([c.args[0] for c in client.request.call_args_list].count('thread/unsubscribe'), 2)

    def test_page_cursor_is_not_starved_by_new_thread(self):
        self.rt.release_cursor = 'old-page'
        self.rt.new_subscriptions.add('just-created')
        self.rt.client.request.side_effect = [{'data': ['older']}, {'thread': {'status': {'type': 'active'}}}]
        self.assertFalse(self.rt.release_subscriptions())
        self.assertEqual(self.rt.client.request.call_args_list[1].args[1]['threadId'], 'older')

    def test_stdio_accepts_fd_beyond_select_limit(self):
        reader, writer = os.pipe()
        with ExitStack() as stack:
            stack.callback(os.close, writer)
            stack.callback(os.close, reader)
            limits = resource.getrlimit(resource.RLIMIT_NOFILE)
            if limits[1] != resource.RLIM_INFINITY and limits[1] < 1051:
                self.skipTest('hard descriptor limit is below 1051')
            if limits[0] != resource.RLIM_INFINITY and limits[0] < 1051:
                resource.setrlimit(resource.RLIMIT_NOFILE, (1051, limits[1]))
                stack.callback(resource.setrlimit, resource.RLIMIT_NOFILE, limits)
            high = fcntl.fcntl(reader, fcntl.F_DUPFD, 1050)
            stack.callback(os.close, high)
            client = rpc.Rpc.__new__(rpc.Rpc)
            client.reader_wakeup = socket.socketpair()
            stack.callback(client.close_wakeup)
            client.closing, client.process = threading.Event(), Mock()
            client.process.stdout.fileno.return_value = high
            os.write(writer, b'fixture\n')
            source = client.stdio_lines()
            stack.callback(source.close)
            self.assertEqual(next(source), b'fixture')

    def test_bad_thread_metadata_does_not_strand_other_threads(self):
        client = Mock()
        client.request.return_value = {'data': ['bad', 'good']}
        self.rt.continue_thread = Mock(side_effect=[KeyError('status'), None])
        with self.assertRaises(UsageUnavailable):
            self.rt.continue_batch(client)
        self.assertEqual([c.args[0] for c in self.rt.continue_thread.call_args_list], ['bad', 'good'])

    def test_migrate_regular_config_preserves_original_contents(self):
        fixed, shared = self.home / 'company.toml', self.home / 'runtime'
        fixed.write_text('company')
        shared.mkdir()
        (shared / 'config.toml').write_text('old')
        runtime.prepare_home(shared, self.home, fixed)
        self.assertEqual((shared / 'config.toml').readlink(), fixed)
        self.assertEqual(next(shared.glob('previous-config-*/config.toml')).read_text(), 'old')

    def monitor(self, saved, batches, request=None):
        stop, clock = Mock(), [1000]
        stop.is_set.side_effect = [False] * len(batches) + [True]
        stop.wait.side_effect = lambda _: clock.__setitem__(0, clock[0] + 61)
        self.rt.running = Mock(return_value=True)
        self.rt.release_subscriptions = Mock(return_value=True)
        self.rt.observe_account = Mock()
        self.rt.continue_limited = Mock(return_value=True)
        def choose(name, *, force):
            self.rt.active = name
            return True
        self.rt.select = Mock(side_effect=choose)
        samples = [({n: {'used_percent': pct, 'windows': {}, 'observed_at': 1000}
                     for n, pct in batch.items()}, {}) for batch in batches]
        with (patch.object(supervisor.time, 'time', side_effect=lambda: clock[0]),
              patch.object(supervisor, 'changed_file', return_value={}),
              patch.object(supervisor, 'poll_delay', return_value=60),
              patch.object(supervisor, 'preference', return_value=request or {}),
              patch.object(supervisor, 'collect', side_effect=samples), patch.object(supervisor, 'save')):
            supervisor.monitor(self.rt, self.profiles, stop, saved)

    def test_stuck_draining_still_polls_accounts(self):
        saved = {'upgrade_status': 'draining', 'drain_started_at': 850}
        self.monitor(saved, [{'company': 98, 'personal': 2}])
        self.assertEqual(saved['upgrade_status'], 'drain_timeout')
        self.assertEqual(saved['active'], 'personal')
        self.assertEqual(saved['restore_account'], 'personal')

    def test_replacement_checkpoint_is_durable_when_exit_is_requested(self):
        installed = self.home / 'Caskroom/codex/2/bin/codex'
        installed.parent.mkdir(parents=True)
        installed.touch()
        self.rt.binary = installed
        self.rt.pid, self.rt.pid_start = 20, 'fixture'
        self.rt.observe_account = Mock()
        saved = {'runtime_version': '1'}
        observed = []
        def signal_sent(*args):
            observed.append(state.read_checkpoint(self.home / state.STATE_FILE.name))
        self.rt.drain_for_upgrade = lambda _: self.rt.finish_upgrade(self.rt.activity_serial)
        with patch.object(runtime, 'peer_process', return_value=(20, 'fixture')), patch.object(os, 'kill', side_effect=signal_sent):
            supervisor.check_upgrade(self.rt, saved)
        self.assertEqual(observed[0]['restore_account'], 'company')
        self.assertEqual(observed[0]['upgrade_status'], 'draining')

    def test_restoration_error_permits_healthy_profile(self):
        self.rt.active = None
        self.rt.restore_account = Mock(side_effect=UsageUnavailable('registration unavailable'))
        self.rt.try_restore_account('company')
        saved = {'preferred': 'company'}
        self.monitor(saved, [{'personal': 5}])
        self.assertEqual(saved['active'], 'personal')

    def test_delayed_quota_recovery_does_not_force_busy_switch(self):
        request = {'preferred': 'personal', 'requested_at': 1, 'immediate': True}
        self.monitor({}, [{'personal': 100, 'company': 2}, {'personal': 2, 'company': 2}], request)
        self.assertEqual([(c.args[0], c.kwargs['force']) for c in self.rt.select.call_args_list],
                         [('company', False), ('personal', False)])

    def test_missing_supervisor_process_start_is_retried(self):
        saved = {'pid': os.getpid(), 'pid_start': None}
        with patch.object(supervisor, 'process_start', side_effect=[None, 'recovered']):
            self.monitor(saved, [{'company': 2}, {'company': 2}])
        self.assertEqual(saved['pid_start'], 'recovered')
