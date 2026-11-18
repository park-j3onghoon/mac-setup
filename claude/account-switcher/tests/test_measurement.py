import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from helpers import NOW, make_app
from macos import KeychainError, Vault
from measurement import Measurement, TokenTail, observe, quota_deltas, summarize
from storage import State


def event(key, at, output=3, cached=10, content='private conversation text'):
    return {'type': 'assistant', 'timestamp': datetime.fromtimestamp(at, timezone.utc).isoformat(),
            'message': {'id': key, 'model': 'claude-opus-5-5', 'content': content,
                        'usage': {'input_tokens': 1, 'cache_creation_input_tokens': 2,
                                  'cache_read_input_tokens': cached, 'output_tokens': output}}}


def snapshot(at, percent, reset=NOW + 5000, **extra):
    return {'observed_at': at, 'captured_at': at, 'active': 'personal@example.com',
            'switched': False, 'errors': {}, 'usage': {'personal@example.com': {
                'checked_at': at, 'windows': [{'name': 'five_hour', 'percent': percent,
                                             'resets_at': reset, 'blocked': False}]}}, **extra}


class TokenTailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = time.time()
        self.tail = TokenTail(self.root, self.now)

    def append(self, name, rows, at):
        p = self.root / name
        with p.open('a') as stream:
            for row in rows:
                stream.write(json.dumps(row) + '\n')
        os.utime(p, (at, at))
        return p

    def test_stream_fragments_and_fork_copies_are_counted_once(self):
        self.append('a.jsonl', [event('a', self.now)], self.now)
        self.assertTrue(self.tail.sample(self.now)['baseline'])
        a = event('a', self.now + 30, output=5)
        b = event('b', self.now + 50, output=7, cached=20)
        self.append('a.jsonl', [a, a, b], self.now + 60)
        counts = self.tail.sample(self.now + 60)['by_model']['claude-opus-5-5']
        self.assertEqual(counts, {'input_tokens': 1, 'cache_creation_input_tokens': 2,
                                 'cache_read_input_tokens': 20, 'output_tokens': 9, 'requests': 1})
        self.append('fork.jsonl', [a, b], self.now + 120)
        counts = self.tail.sample(self.now + 120)['by_model']['claude-opus-5-5']
        self.assertEqual(sum(counts.values()), 0)

    def test_partial_json_line_is_retried_without_losing_tokens(self):
        p = self.append('a.jsonl', [], self.now)
        self.tail.sample(self.now)
        raw = json.dumps(event('a', self.now + 50))
        p.write_text(raw[:len(raw)//2])
        os.utime(p, (self.now + 60, self.now + 60))
        self.assertEqual(self.tail.sample(self.now + 60)['by_model'], {})
        with p.open('a') as stream:
            stream.write(raw[len(raw)//2:] + '\n')
        os.utime(p, (self.now + 120, self.now + 120))
        self.assertEqual(self.tail.sample(self.now + 120)['by_model']['claude-opus-5-5']['requests'], 1)

    def test_truncated_file_does_not_recount_a_previous_response(self):
        p = self.append('a.jsonl', [event('a', self.now, content='x' * 500)], self.now)
        self.tail.sample(self.now)
        p.write_text(json.dumps(event('a', self.now)) + '\n' +
                     json.dumps(event('b', self.now + 50)) + '\n')
        os.utime(p, (self.now + 60, self.now + 60))
        counts = self.tail.sample(self.now + 60)['by_model']['claude-opus-5-5']
        self.assertEqual(counts['requests'], 1)
        self.assertEqual(counts['cache_read_input_tokens'], 10)

    def test_startup_does_not_treat_historical_tokens_as_current_usage(self):
        self.append('a.jsonl', [event('a', self.now - 20, output=10000)], self.now)
        self.assertEqual(self.tail.sample(self.now)['by_model'], {})
        self.append('a.jsonl', [event('a', self.now + 10, output=10002)], self.now + 60)
        self.assertEqual(self.tail.sample(self.now + 60)['by_model']['claude-opus-5-5']['output_tokens'], 2)

    def test_directory_cache_keeps_appends_and_discovers_new_files_immediately(self):
        """목록은 재사용하되 기존 대화 append와 새 하위 폴더의 첫 요청은 빠짐없이 센다."""
        self.append('a.jsonl', [event('a', self.now)], self.now)
        self.tail.sample(self.now)
        self.append('a.jsonl', [event('b', self.now + 30)], self.now + 30)
        with patch('measurement.os.scandir', wraps=os.scandir) as scan:
            counts = self.tail.sample(self.now + 30)['by_model']['claude-opus-5-5']
        self.assertEqual(counts['requests'], 1)
        self.assertEqual(scan.call_count, 0)
        (self.root / 'new-project').mkdir()
        self.append('new-project/new.jsonl', [event('c', self.now + 60)], self.now + 60)

        counts = self.tail.sample(self.now + 60)['by_model']['claude-opus-5-5']

        self.assertEqual(counts['requests'], 1)

    def test_deleted_and_inactive_file_offsets_expire_without_losing_resumed_usage(self):
        """삭제·2시간 비활성 파일 offset은 지우고 다시 쓰인 오래된 대화의 새 요청은 센다."""
        removed = self.append('removed.jsonl', [event('a', self.now)], self.now)
        self.append('old.jsonl', [event('b', self.now)], self.now)
        self.tail.sample(self.now)
        removed.unlink()

        self.tail.sample(self.now + 7201)

        self.assertFalse(self.tail.files)
        self.append('old.jsonl', [event('c', self.now + 7202)], self.now + 7202)
        counts = self.tail.sample(self.now + 7202)['by_model']['claude-opus-5-5']
        self.assertEqual(counts['requests'], 1)


class QuotaDeltaTests(unittest.TestCase):
    def test_delta_and_duration_are_actual_observations(self):
        d = quota_deltas(snapshot(NOW, 70), snapshot(NOW + 63, 76, reset=NOW + 5000.4))[0]
        self.assertTrue(d['valid'])
        self.assertEqual((d['delta_pp'], d['seconds']), (6, 63))

    def test_reset_and_decreasing_counter_are_rejected(self):
        for following in (snapshot(NOW + 60, 1, reset=NOW + 23000),
                          snapshot(NOW + 60, 69), snapshot(NOW + 6000, 71)):
            self.assertFalse(quota_deltas(snapshot(NOW, 70), following)[0]['valid'])

    def test_saturated_counter_is_marked_as_incomplete_evidence(self):
        self.assertTrue(quota_deltas(snapshot(NOW, 98), snapshot(NOW + 60, 100))[0]['saturated'])


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = State(Path(self.tmp.name) / 'state')
        self.projects = Path(self.tmp.name) / 'projects'
        self.projects.mkdir()
        self.meter = Measurement(self.state, self.projects)
        self.meter.tokens = TokenTail(self.projects, NOW)

    def test_history_pairs_tokens_and_usage_without_saving_content(self):
        self.meter.record(snapshot(NOW, 70), NOW)
        p = self.projects / 'a.jsonl'
        p.write_text(json.dumps(event('a', NOW + 50)) + '\n')
        os.utime(p, (NOW + 60, NOW + 60))
        row = self.meter.record(snapshot(NOW + 60, 73), NOW + 60)
        self.assertEqual(row['token_account_estimate'], 'personal@example.com')
        self.assertEqual(row['quota_deltas'][0]['delta_pp'], 3)
        summary = summarize(self.state)
        self.assertEqual(summary['windows'][0]['max_delta_pp'], 3)
        files = list((self.state.root / 'measurements').glob('*.jsonl'))
        self.assertEqual(len(files), 1)
        raw = files[0].read_text()
        self.assertNotIn('private conversation text', raw)
        self.assertNotIn('"id":"a"', raw)
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)

    def test_account_swap_excludes_token_attribution(self):
        self.meter.record(snapshot(NOW, 70), NOW)
        row = self.meter.record(snapshot(NOW + 60, 73, switched=True), NOW + 60)
        self.assertIsNone(row['token_account_estimate'])
        self.assertEqual(row['quota_deltas'][0]['delta_pp'], 3)

    def test_failed_account_read_is_not_reused_as_fresh_data(self):
        self.meter.record(snapshot(NOW, 70), NOW)
        row = self.meter.record(snapshot(NOW + 60, 70, errors={'personal@example.com': 'http_429'}), NOW + 60)
        self.assertEqual(row['usage'], {})
        self.assertEqual(row['quota_deltas'], [])

    def test_long_gap_is_not_reported_as_one_minute_peak(self):
        self.meter.record(snapshot(NOW, 70), NOW)
        row = self.meter.record(snapshot(NOW + 600, 90), NOW + 600)
        self.assertIsNone(row['token_account_estimate'])
        self.assertEqual(summarize(self.state)['windows'], [])


class ObserverTests(unittest.TestCase):
    def test_measurement_refreshes_only_inactive_account_and_does_not_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp)
            app.vault.read_active_for_measurement = app.vault.read_active
            b = app.vault.read('work@example.com')
            b['oauth']['expiresAt'] = (NOW - 1) * 1000
            app.vault.write('work@example.com', b)
            with patch('measurement.time.time', return_value=NOW):
                result = observe(app)
            self.assertEqual(app.api.refreshes, 1)
            self.assertEqual(app.vault.active_writes, 0)
            self.assertEqual(result['source'], 'measurement_only')
            self.assertEqual(set(result['usage']), set(app.accounts))

    def test_native_reader_refuses_to_open_a_prompt_without_existing_grant(self):
        keychain = Mock()
        keychain.read.side_effect = KeychainError('no UI allowed')
        with self.assertRaises(KeychainError):
            Vault(keychain, 'test').read_active_for_measurement()
        keychain.read.assert_called_once()

    def test_native_reader_uses_framework_without_a_secret_subprocess(self):
        keychain = Mock()
        keychain.read.return_value = {'secret': 'sensitive'}
        self.assertEqual(Vault(keychain, 'test').read_active_for_measurement(), {'secret': 'sensitive'})
        keychain.read.assert_called_once_with('Claude Code-credentials', Vault(keychain, 'test').username)

    def test_denied_native_read_uses_saved_account_without_refreshing_active_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp)
            app.vault.read_active_for_measurement = Mock(side_effect=KeychainError('no UI allowed'))
            with patch('measurement.time.time', return_value=NOW):
                result = observe(app)
                observe(app)
            self.assertEqual(set(result['usage']), set(app.accounts))
            self.assertEqual(app.api.refreshes, 0)
            self.assertEqual(app.vault.active_writes, 0)


if __name__ == '__main__':
    unittest.main()
