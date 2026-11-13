import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from measurement import Measurement, summarize
from monitoring import DAY, review_if_due, start
from storage import State, SwitcherError, write_text


NOW = 2_000_000_000.0


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = State(Path(self.tmp.name) / 'state')
        self.state.save('config', {'primary': 'personal@example.com', 'threshold': 90})

    def append(self, at, delta=3, seconds=60, model='claude-opus-5-5', failed=False):
        row = {'captured_at': at, 'token_interval_seconds': seconds,
               'token_account_estimate': 'personal@example.com',
               'usage': {} if failed else {'personal@example.com': {'checked_at': at}},
               'errors': {'personal@example.com': 'http_429'} if failed else {},
               'tokens': {'read_errors': 0, 'by_model': {model: {'output_tokens': 100}}},
               'quota_deltas': [] if failed else [{'account': 'personal@example.com',
                   'window': 'five_hour', 'valid': True, 'saturated': False,
                   'seconds': seconds, 'start_percent': 50, 'end_percent': 50 + delta,
                   'delta_pp': delta}]}
        directory = self.state.root / 'measurements'
        directory.mkdir(exist_ok=True)
        with (directory / 'test.jsonl').open('a') as stream:
            stream.write(json.dumps(row) + '\n')

    def test_start_schedules_fourteen_days_and_retries_do_not_extend_period(self):
        first = start(self.state, 14, NOW)
        self.assertEqual(first['ends_at'], NOW + 14 * DAY)
        self.assertEqual(first['next_review_at'], NOW + DAY)
        self.assertEqual(start(self.state, 14, NOW + 50), first)
        self.assertTrue(Path(first['last_report']).exists())

    def test_daily_review_excludes_old_and_cross_boundary_intervals(self):
        start(self.state, 14, NOW)
        self.append(NOW - 1, delta=30)
        self.append(NOW + 30, delta=20)
        self.append(NOW + 65, delta=11)
        plan = review_if_due(self.state, NOW + DAY)
        report = json.loads(Path(plan['last_report']).with_suffix('.json').read_text())
        self.assertEqual(report['summary']['samples'], 2)
        self.assertEqual(report['primary_five_hour']['intervals'], 1)
        self.assertEqual(report['primary_five_hour']['max_delta_pp'], 11)
        self.assertEqual(report['finding'], 'observed_margin_exceeded')
        self.assertEqual(plan['next_review_at'], NOW + 2 * DAY)

    def test_query_failures_are_reported_as_insufficient_evidence(self):
        start(self.state, 14, NOW)
        self.append(NOW + 60, failed=True)
        plan = review_if_due(self.state, NOW + DAY)
        report = json.loads(Path(plan['last_report']).with_suffix('.json').read_text())
        self.assertEqual(report['finding'], 'insufficient_active_primary_data')
        self.assertEqual(report['summary']['quality']['failed_samples'], 1)
        self.assertEqual(report['summary']['quality']['empty_usage_samples'], 1)

    def test_other_model_does_not_supply_opus55_calibration_evidence(self):
        start(self.state, 14, NOW)
        self.append(NOW + 60, delta=3, model='claude-sonnet-5-5')
        plan = review_if_due(self.state, NOW + DAY)
        report = json.loads(Path(plan['last_report']).with_suffix('.json').read_text())
        self.assertEqual(report['finding'], 'insufficient_active_primary_data')

    def test_late_final_review_archives_only_requested_period_and_stops_collection(self):
        start(self.state, 14, NOW)
        self.append(NOW + 60, delta=3)
        self.append(NOW + 15 * DAY, delta=15)
        plan = review_if_due(self.state, NOW + 16 * DAY)
        self.assertEqual(plan['status'], 'complete')
        self.assertEqual(Path(plan['last_report']).name, 'final.md')
        report = json.loads(Path(plan['last_report']).with_suffix('.json').read_text())
        self.assertEqual(report['period_end'], NOW + 14 * DAY)
        self.assertEqual(report['summary']['samples'], 1)
        self.assertEqual(report['finding'], 'no_exceedance_observed')
        self.assertEqual(review_if_due(self.state, NOW + 17 * DAY), plan)
        meter = Measurement(self.state, Path(self.tmp.name) / 'projects')
        meter.tokens = Mock()
        self.assertIsNone(meter.record({}, NOW + 16 * DAY))
        meter.tokens.sample.assert_not_called()

    def test_reports_do_not_run_before_due_time(self):
        plan = start(self.state, 14, NOW)
        self.append(NOW + 60)
        self.assertEqual(review_if_due(self.state, NOW + 600), plan)

    def test_text_report_writer_refuses_symlink(self):
        target = Path(self.tmp.name) / 'keep'
        target.write_text('keep me')
        path = self.state.root / 'report.md'
        path.symlink_to(target)
        with self.assertRaises(SwitcherError):
            write_text(path, 'replace')
        self.assertEqual(target.read_text(), 'keep me')

    def test_invalid_period_does_not_create_a_schedule(self):
        with self.assertRaises(SwitcherError):
            start(self.state, 31, NOW)
        self.assertEqual(self.state.load('monitoring'), {})


if __name__ == '__main__':
    unittest.main()
