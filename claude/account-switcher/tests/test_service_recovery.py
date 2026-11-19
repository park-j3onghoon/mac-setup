import subprocess
import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from api import ApiError
from compatibility import IncompatibleLayout
from helpers import NOW, make_app
from macos import system_awake
from measurement import Measurement, observe, summarize
from switcher import halts_keychain_work, install_service, measure_and_review, run


class ServiceRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.app = make_app(self.root)
        self.state = self.app.state

    def test_invalid_grant_stops_until_refresh_token_changes(self):
        account = self.app.config['fallback']
        bundle = self.app.vault.read(account)
        self.app.api.refresh = Mock(side_effect=ApiError('token refresh', 400, 0, 'invalid_grant'))
        for _ in range(2):
            with self.assertRaises(ApiError):
                self.app.refresh_inactive(account, self.app.vault.read(account), NOW)
        self.assertEqual(self.app.api.refresh.call_count, 1)
        bundle['oauth']['refreshToken'] = 'new-grant'
        self.app.api.refresh.side_effect = None
        self.app.api.refresh.return_value = bundle['oauth']
        self.assertNotIn('rejected_refresh', self.app.refresh_inactive(account, bundle, NOW))
        self.assertEqual(self.app.api.refresh.call_count, 2)

    def test_rate_limit_survives_new_measurement_instance(self):
        with patch('switcher.observe', return_value={'retry_after_seconds': 1800}) as query, \
                patch('switcher.review_if_due'):
            for _ in range(2):
                meter = Mock()
                meter.record.return_value = {}
                measure_and_review(self.app, meter, None, 60)
        query.assert_called_once()
        self.assertEqual(self.state.load('measurement_error')['retry_after_seconds'], 1800)

    def test_measurement_write_error_and_clean_ticks(self):
        with patch('switcher.review_if_due'):
            meter = Mock()
            meter.record.side_effect = OSError('disk')
            measure_and_review(self.app, meter, {'reason': 'ready'}, 60)
            self.assertEqual(self.state.load('measurement_error')['stage'], 'record')
            meter.record.side_effect = None
            with patch.object(self.state, 'save', wraps=self.state.save) as writes:
                for _ in range(3):
                    measure_and_review(self.app, meter, {'reason': 'ready'}, 60)
            self.assertEqual(writes.call_count, 1)

    def test_corrupt_measurement_state_does_not_block_startup_or_review(self):
        (self.state.root / 'measurement_latest.json').write_text('{')
        meter = Measurement(self.state, self.root)
        self.assertFalse(meter.previous)
        directory = self.state.root / 'measurements'
        directory.mkdir()
        (directory / '2026-11-19.jsonl').write_text('{}\n')
        self.assertEqual(summarize(self.state)['quality']['malformed_rows'], 1)

    def test_settle_prevents_inactive_measurement_refresh(self):
        self.app.vault.read_active_for_measurement = self.app.vault.read_active
        self.state.save('runtime', {'settle_until': NOW + 15})
        account = self.app.config['fallback']
        bundle = self.app.vault.read(account)
        bundle['oauth']['expiresAt'] = 0
        self.app.vault.write(account, bundle)
        with patch('measurement.time.time', return_value=NOW):
            report = observe(self.app)
        self.assertEqual(report['errors'][account], 'inactive_token_needs_refresh')
        self.assertEqual(self.app.api.refreshes, 0)

    def test_timeout_after_bootstrap_can_be_retried(self):
        with patch('switcher.Path.home', return_value=self.root), \
                patch.object(self.app, 'tick', return_value={'errors': {}, 'target': 'active'}), \
                patch('switcher.subprocess.run', side_effect=[
                    subprocess.TimeoutExpired('bootstrap', 10), Mock(returncode=1),
                    Mock(returncode=0)]) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                install_service(self.app)
            install_service(self.app)
        self.assertEqual([c.args[0][1] for c in run.call_args_list], ['bootstrap', 'print', 'bootstrap'])

    def test_unknown_power_state_and_incompatible_layout_halt(self):
        self.assertTrue(system_awake(Mock(return_value=Mock(returncode=1, stdout=''))))
        self.assertTrue(halts_keychain_work(IncompatibleLayout('changed'), awake=lambda: False))

    def test_daemon_reclaims_crashed_helper_lock_after_startup(self):
        event = threading.Event()
        at = [0]
        orphan = self.state.root / 'restart-finished.lock'
        def tick(*_):
            if at[0] == 0:
                orphan.touch()
                at[0] = 3601
            else:
                self.assertFalse(orphan.exists())
                event.set()
            return None, 0, None
        with patch('switcher.threading.Event', return_value=event), patch('switcher.signal.signal'), \
                patch('switcher.time.monotonic', side_effect=lambda: at[0]), \
                patch('switcher.tick_once', side_effect=tick), patch('switcher.measure_and_review', return_value=0):
            run(self.app, False)
