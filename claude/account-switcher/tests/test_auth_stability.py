import contextlib
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api import ApiError
from helpers import NOW, make_app
from macos import KeychainError, NativeKeychain, TransientKeychainError
from service import validate_config
from storage import LockBusy, State, SwitcherError, directory_lock
from switchcore.policy import PriorityPolicy
from switchcore.quota import Window, Usage
import storage
import switcher


class AuthStabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.app = make_app(self.root)
        self.state = self.app.state
        self.primary, self.fallback = self.app.accounts

    def test_halt_applies_to_manual_tick(self):
        self.state.save('halt', {'reason': 'access denied'})
        with self.assertRaises(SwitcherError):
            switcher.run_app_command(SimpleNamespace(command='once', apply=True), self.state, self.app)
        self.assertEqual(self.app.vault.active_writes, 0)

    def test_preference_replaced_during_request(self):
        self.state.save('preference', {'preferred': self.fallback, 'requested_at': NOW})
        self.app.api.before_usage = lambda: self.state.save(
            'preference', {'preferred': self.primary, 'requested_at': NOW + 1})
        self.app.tick(apply=True, now=NOW)
        self.assertEqual(self.app.vault.active_writes, 0)

    def test_current_profile_401_still_checks_standby(self):
        original = self.app.api.profile
        def profile(oauth):
            if oauth == self.app.vault.read(self.primary)['oauth']:
                raise ApiError('profile', 401)
            return original(oauth)
        self.app.api.profile = profile
        report = self.app.tick(apply=True, now=NOW)
        self.assertIn(self.fallback, report['usage'])
        self.assertEqual(report['errors'][self.primary], 'http_401')

    def test_public_backup_metadata_survives_finish(self):
        with patch.object(self.app.vault, 'delete', side_effect=OSError('not saved')):
            with self.assertRaises(OSError):
                self.app.tick(apply=True, now=NOW)
        _, account = self.app.live.read()
        self.app.live.write_account(dict(account, displayName='New name'))
        self.app.recover()
        self.assertEqual(self.app.live.read()[1]['displayName'], 'New name')

    def test_timeout_in_only_one_account_keeps_other_available(self):
        self.app.api.failed_tokens.add('token-work')
        self.app.tick(apply=True, now=NOW)
        report = self.app.tick(apply=True, now=NOW + 1)
        self.assertIn(self.primary, report['usage'])
        self.assertFalse(report['usage'][self.primary].get('stale'))

    def test_profile_and_usage_have_independent_retry_windows(self):
        self.app.api.profile = Mock(side_effect=ApiError('profile', 429, 800))
        with self.assertRaises(ApiError):
            self.app.verify_identity(self.app.vault.read(self.primary), NOW)
        reading = self.app.read_usage(self.primary, self.app.vault.read(self.primary)['oauth'], NOW)
        self.assertTrue(reading.verified(NOW, 90))

    def test_read_only_tick_does_not_set_writer_heartbeat(self):
        self.app.writer_daemon = True
        self.app.tick(apply=True, now=NOW)
        self.assertEqual(self.state.load('runtime')['observed_at'], NOW)
        self.app.writer_daemon = False
        self.app.tick(now=NOW)
        self.app.tick(now=NOW + 120)
        self.assertEqual(self.state.load('runtime')['observed_at'], NOW)
        self.assertEqual(self.state.load('last_observation')['observed_at'], NOW + 120)

    def test_known_exhaustion_overrides_unknown_second_window(self):
        reads = {self.primary: Usage(NOW, (Window('five_hour', 100, None), Window('seven_day', None, None))),
                 self.fallback: Usage(NOW, (Window('five_hour', 10, None),))}
        self.assertEqual(PriorityPolicy(90, 60).choose((self.primary, self.fallback), self.primary,
                                                       reads, NOW).target, self.fallback)

    def test_rejects_two_roles_for_same_email_domain(self):
        with self.assertRaises(SwitcherError):
            validate_config(dict(self.app.config, fallback=self.primary.replace('example', 'EXAMPLE')))

    def test_policy_setting_names_a_built_in_rule_or_is_left_out(self):
        """설정에 규칙 이름이 없으면 지금 규칙이고, repo에 없는 이름은 쓸 수 있는 이름과 함께 거부한다."""
        validate_config(dict(self.app.config, policy='priority'))
        with self.assertRaisesRegex(SwitcherError, r'policy=rules\.py:Mine \(choose from: priority\)'):
            validate_config(dict(self.app.config, policy='rules.py:Mine'))

    def test_mixed_case_domain_uses_existing_saved_account_keys(self):
        actual = self.app.live.read()[1]
        self.app.live.write_account(dict(actual, emailAddress=self.primary.replace('example', 'EXAMPLE')))
        self.app.capture(self.primary)
        self.assertTrue(self.app.tick(True, NOW + self.app.config['settle_seconds'] + 1)['switched'])
        self.assertEqual(self.app.vault.read(self.primary)['account']['emailAddress'], self.primary.replace('example', 'EXAMPLE'))

    def test_interrupted_browser_retains_recoverable_previous_login(self):
        def browser(*args, **kwargs):
            self.assertEqual(self.app.vault.read('__transaction__')['previous'],
                             self.app.vault.read(self.primary))
            self.app.live.write_account({'emailAddress': 'third@example.com'})
            self.app.vault.active['claudeAiOauth'] = {'accessToken': 'third'}
            raise KeyboardInterrupt()
        with patch('switcher.subprocess.run', side_effect=browser), self.assertRaises(KeyboardInterrupt):
            switcher.enroll(self.app, 'fallback')
        with self.assertRaisesRegex(SwitcherError, 'restore-enrollment'):
            self.app.tick(apply=True, now=NOW)
        self.assertEqual(self.app.live.read()[1]['emailAddress'], 'third@example.com')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(switcher.tick_once(self.app, True, None)[0])
        self.assertEqual(self.app.vault.active_writes, 0)
        switcher.run_app_command(SimpleNamespace(command='restore-enrollment'), self.state, self.app)
        self.assertEqual(self.app.live.read()[1]['emailAddress'], self.primary)

    def test_active_at_renewal_is_not_rotated(self):
        self.app.api.percent['token-personal'] = 10
        bundle = self.app.vault.read(self.fallback)
        bundle['oauth']['expiresAt'] = 0
        self.app.vault.write(self.fallback, bundle)
        def activate():
            self.app.live.write_account(bundle['account'])
            self.app.vault.active['claudeAiOauth'] = bundle['oauth']
        self.app.api.before_usage = activate
        self.app.tick(apply=True, now=NOW)
        self.assertEqual(self.app.api.refreshes, 0)
        self.assertEqual(self.app.live.read()[0]['claudeAiOauth'], self.app.vault.read(self.fallback)['oauth'])

    def test_split_native_login_does_not_rotate_partially_published_account(self):
        target = self.app.vault.read(self.fallback)
        self.app.vault.active['claudeAiOauth'] = target['oauth']
        with self.assertRaisesRegex(SwitcherError, 'generation changed'):
            self.app.refresh_inactive(self.fallback, target, NOW)
        self.assertEqual(self.app.api.refreshes, 0)

    def test_rotated_token_storage_retries_and_crash_fails_closed(self):
        bundle = self.app.vault.read(self.fallback)
        write = self.app.vault.write
        attempts = []
        def save(email, updated):
            if updated['oauth']['refreshToken'] == 'rotated-refresh-token':
                attempts.append(1)
                if len(attempts) < 3:
                    raise KeychainError('unavailable')
            write(email, updated)
        with patch.object(self.app.vault, 'write', side_effect=save), patch('service.time.sleep'):
            renewed = self.app.refresh_inactive(self.fallback, bundle, NOW)
        self.assertEqual(self.app.vault.read(self.fallback), renewed)
        self.assertEqual((len(attempts), self.app.api.refreshes), (3, 1))
        with patch.object(self.app.api, 'refresh', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.app.refresh_inactive(self.fallback, renewed, NOW)
        with patch.object(self.app.api, 'refresh') as again, self.assertRaises(ApiError) as error:
            self.app.refresh_inactive(self.fallback, self.app.vault.read(self.fallback), NOW)
        again.assert_not_called()
        self.assertEqual(error.exception.oauth_error, 'rotation_uncertain')
        report = self.app.tick(True, NOW)
        self.assertFalse(report['switched'])
        self.assertEqual(report['oauth_errors'][self.fallback], 'rotation_uncertain')

    def test_native_write_failure_preserves_keychain_halt(self):
        with patch.object(self.app.vault, 'write_active', side_effect=KeychainError('native write failed')), contextlib.redirect_stdout(io.StringIO()):
            switcher.tick_once(self.app, True, None)
        self.assertEqual(self.state.load('halt')['error_type'], 'KeychainError')

    def test_response_received_but_successor_lost_requires_reauthentication(self):
        original = self.app.vault.write
        def crash_on_successor(name, entry):
            if entry['oauth']['refreshToken'] == 'rotated-refresh-token':
                raise KeyboardInterrupt()
            original(name, entry)
        with patch.object(self.app.vault, 'write', side_effect=crash_on_successor), self.assertRaises(KeyboardInterrupt):
            self.app.refresh_inactive(self.fallback, self.app.vault.read(self.fallback), NOW)
        self.assertEqual(self.app.api.refreshes, 1)
        report = self.app.tick(True, NOW)
        self.assertEqual(report['oauth_errors'][self.fallback], 'rotation_uncertain')
        self.assertEqual(self.app.api.refreshes, 1)

    def test_observer_does_not_hold_writer_and_records_its_mode(self):
        stop = Mock()
        stop.is_set.return_value = True
        with self.state.lock('daemon'), patch('switcher.threading.Event', return_value=stop), patch('switcher.signal.signal'):
            switcher.run(self.app, False)
        self.assertFalse(self.state.load('service_settings'))
        self.assertEqual(self.state.load('observer_settings')['mode'], 'observe')

    def test_different_state_dirs_contend_for_the_same_writer(self):
        stop = Mock()
        stop.is_set.return_value = True
        foreign = State(self.root / 'other-state')
        with foreign.lock('claude-account-writer', directory=self.app.live.home), patch('switcher.threading.Event', return_value=stop), patch('switcher.signal.signal'), self.assertRaises(LockBusy):
            switcher.run(self.app, True)

    def test_installation_checks_current_writer_ownership(self):
        with self.state.lock('claude-account-writer', directory=self.app.live.home) as fd:
            os.write(fd, json.dumps({'state_dir': str(self.state.root.resolve())}).encode())
            self.assertEqual(switcher.writer_status(self.app), 'writer_running')
        self.assertEqual(switcher.writer_status(self.app), 'waiting_for_writer')

    def test_abandoned_login_expires_and_releases_lock(self):
        def timed_out(command, timeout):
            self.assertGreater(timeout, 0)
            raise subprocess.TimeoutExpired(command, timeout)
        with patch('switcher.subprocess.run', side_effect=timed_out), self.assertRaisesRegex(SwitcherError, 'timed out'):
            switcher.enroll(self.app, 'fallback')
        with self.state.lock():
            self.assertIsNone(self.app.vault.read('__transaction__'))

    def test_malformed_preference_keeps_last_valid_request(self):
        self.state.save('preference', {'preferred': self.fallback})
        self.assertEqual(self.app.preference()['preferred'], self.fallback)
        (self.state.root / 'preference.json').write_text('{')
        self.assertEqual(self.app.preference()['preferred'], self.fallback)
        self.app.tick(apply=True, now=NOW)
        self.state.save('preference', {'preferred': self.primary})
        self.assertEqual(self.app.preference()['preferred'], self.primary)

    def test_invalid_optional_deadline_does_not_interrupt_tick(self):
        self.state.save('measurement_error', {'retry_at': 'tomorrow'})
        meter = Mock()
        with patch('switcher.review_if_due'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(switcher.measure_and_review(self.app, meter, {'reason': 'ok'}, 60), 60)
        meter.record.assert_called_once()

    def test_install_accepts_exhausted_but_successful_quota_results(self):
        self.app.api.percent = dict.fromkeys(self.app.api.percent, 100)
        with patch('switcher.Path.home', return_value=self.root), patch('switcher.subprocess.run', return_value=Mock(returncode=0)) as run, contextlib.redirect_stdout(io.StringIO()):
            switcher.install_service(self.app)
        self.assertEqual(run.call_args.args[0][1], 'bootstrap')

    def test_partial_plist_is_never_published(self):
        def partial(value, stream):
            stream.write(b'partial')
            raise KeyboardInterrupt()
        with patch('switcher.Path.home', return_value=self.root), patch('switcher.plistlib.dump', side_effect=partial), self.assertRaises(KeyboardInterrupt):
            switcher.install_service(self.app)
        destination = self.root / 'Library/LaunchAgents' / (switcher.LABEL + '.plist')
        self.assertFalse(destination.exists())

    def test_old_empty_service_plist_is_repaired_when_not_loaded(self):
        directory = self.root / 'Library/LaunchAgents'
        directory.mkdir(parents=True)
        destination = directory / (switcher.LABEL + '.plist')
        destination.touch(mode=0o600)
        replies = [Mock(returncode=1), Mock(returncode=0)]
        with patch('switcher.Path.home', return_value=self.root), patch('switcher.subprocess.run', side_effect=replies), contextlib.redirect_stdout(io.StringIO()):
            switcher.install_service(self.app)
        with destination.open('rb') as file:
            self.assertEqual(switcher.plistlib.load(file)['Label'], switcher.LABEL)

    def test_uninstall_matches_state_and_executable(self):
        with patch('switcher.Path.home', return_value=self.root), patch('switcher.subprocess.run', return_value=Mock(returncode=0)) as run, contextlib.redirect_stdout(io.StringIO()):
            switcher.install_service(self.app)
            run.reset_mock()
            with self.assertRaisesRegex(SwitcherError, 'another'):
                switcher.uninstall_service(State(self.root / 'other-state'))
            run.assert_not_called()
            switcher.uninstall_service(self.state)
            self.assertEqual(run.call_args.args[0][1], 'bootout')

    def test_status_uses_no_profile_credentials(self):
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': '/different'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(switcher.main(['--state-dir', str(self.state.root), 'status']), 0)

    def test_moved_namespace_preserves_legacy_keychain_address(self):
        original = self.state.root
        before = hashlib.sha256(str(original.resolve()).encode()).hexdigest()[:16]
        self.assertEqual(switcher.vault_namespace(self.state), before)
        moved = original.rename(self.root / 'moved')
        self.assertEqual(switcher.vault_namespace(State(moved)), before)

    def test_migrate_already_moved_legacy_vault_without_changing_credentials(self):
        old = self.root / 'old-state-dir'
        expected = hashlib.sha256(str(old.resolve()).encode()).hexdigest()[:16]
        store = Mock()
        store.read.side_effect = lambda name: {'exists': True} if name == self.primary else None
        with patch('switcher.Keychain'), patch('switcher.Vault', return_value=store):
            self.assertEqual(switcher.vault_namespace(self.state, old), expected)
        store.write.assert_not_called()
        self.assertEqual(switcher.vault_namespace(self.state), expected)

    def test_inactive_401_refreshes_even_without_expiry(self):
        saved = self.app.vault.read(self.fallback)
        del saved['oauth']['expiresAt']
        self.app.vault.write(self.fallback, saved)
        original = self.app.api.usage
        def usage(oauth, now):
            if oauth['accessToken'] == 'token-work':
                raise ApiError('usage', 401)
            return original(oauth, now)
        self.app.api.usage = usage
        self.assertTrue(self.app.tick(True, NOW)['switched'])
        self.assertEqual(self.app.api.refreshes, 1)

    def test_enrollment_restore_marker_stays_stable_after_delete_failure(self):
        previous = self.app.vault.read(self.primary)
        target = self.app.vault.read(self.fallback)
        self.app.live.write_account(target['account'])
        self.app.vault.active['claudeAiOauth'] = target['oauth']
        with patch('service.time.time', return_value=NOW), patch.object(self.app.vault, 'delete', side_effect=OSError()), self.assertRaises(OSError):
            self.app.restore_enrollment(previous, target['account'])
        with patch('service.time.time', return_value=NOW + 100):
            self.app.recover()
        self.assertEqual(self.state.load('session_refresh')['since'], NOW)

    def test_log_rotation_preserves_open_launchd_descriptor(self):
        for name in ('service.log','service-error.log'):
            with (self.state.root / name).open('ab') as destination:
                destination.write(b'0123456789')
                destination.flush()
                with patch('switcher.LOG_BYTES', 4):
                    switcher.rotate_logs(self.state)
                destination.write(b'end')
            self.assertEqual((self.state.root / name).read_bytes(), b'end')
            self.assertEqual((self.state.root / (name + '.1')).read_bytes(), b'6789')

    def test_locked_keychain_rechecks_without_launching_security(self):
        keychain = Mock(allow_interaction=False)
        keychain.locked.side_effect = [True, False]
        runner = Mock(return_value=Mock(returncode=0, stdout=b'{}'))
        native = NativeKeychain(keychain, 'fixture', runner)
        with self.assertRaises(TransientKeychainError) as error:
            native.read()
        self.assertFalse(switcher.halts_keychain_work(error.exception))
        runner.assert_not_called()
        self.assertEqual(native.read(), {})

    def test_manual_measurement_honors_measurement_and_legacy_deadlines(self):
        for name, field in [('measurement_error','retry_at'), ('runtime','retry_after')]:
            self.state.save(name, {field: NOW + 60})
            with patch('switcher.time.time', return_value=NOW), patch('switcher.observe') as query, contextlib.redirect_stdout(io.StringIO()):
                switcher.run_app_command(SimpleNamespace(command='measure-once'), self.state, self.app)
            query.assert_not_called()
            self.state.save(name, {})

    def test_doctor_fails_for_invalid_saved_bundle(self):
        self.app.compatibility = {'version': 'fixture'}
        self.app.vault.write(self.fallback, {})
        with contextlib.redirect_stdout(io.StringIO()) as result:
            self.assertEqual(switcher.doctor(self.app), 1)
        self.assertFalse(json.loads(result.getvalue())['registered'][self.fallback])

    def test_just_expired_window_gets_near_term_poll(self):
        self.state.save('runtime', {'active': self.primary, 'usage': {self.primary: {
            'checked_at': NOW - 1, 'windows': [{'percent': 10, 'resets_at': NOW}]}}})
        self.assertLessEqual(self.app.next_delay(NOW), 60)

    def test_released_native_lock_acquired_in_same_call(self):
        path = self.root / '.native.lock'
        path.mkdir()
        original = storage.directory_identity
        removed = []
        def released(current):
            if current == path and not removed:
                removed.append(True)
                path.rmdir()
            return original(current)
        with patch('storage.directory_identity', side_effect=released), directory_lock(path, timeout=0):
            self.assertTrue(path.is_dir())
