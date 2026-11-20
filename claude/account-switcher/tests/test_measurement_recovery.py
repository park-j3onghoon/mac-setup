import json
from pathlib import Path
import tempfile
import time
import unittest
from datetime import datetime, timezone

from measurement import Measurement, TokenTail, summarize
from monitoring import DAY, review_if_due, start, render
from storage import State
from test_measurement import event, snapshot


class MeasurementRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = State(self.root / 'state')
        self.projects = self.root / 'projects'
        self.projects.mkdir()
        self.now = time.time()

    def test_damaged_nested_row_is_ignored_without_losing_following_sample(self):
        directory = self.state.root / 'measurements'
        directory.mkdir()
        path = directory / 'history.jsonl'
        path.write_text(json.dumps({'captured_at': self.now, 'tokens': None}) + '\n')
        Measurement(self.state, self.projects).record(snapshot(self.now, 5), self.now)
        summary = summarize(self.state)
        self.assertEqual((summary['samples'], summary['quality']['malformed_rows']), (1, 1))

    def test_restart_after_torn_append_keeps_next_row(self):
        directory = self.state.root / 'measurements'
        directory.mkdir()
        day = datetime.fromtimestamp(self.now, timezone.utc).strftime('%Y-%m-%d')
        (directory / f'{day}.jsonl').write_bytes(b'{"captured_at":')
        Measurement(self.state, self.projects).record(snapshot(self.now, 5), self.now)
        self.assertEqual(summarize(self.state)['samples'], 1)

    def test_large_complete_and_incrementally_published_record_keep_usage(self):
        tail = TokenTail(self.projects, self.now)
        tail.sample(self.now)
        for idx in range(2):
            raw = json.dumps(event(str(idx), self.now, output=11, content='x' * (2 << 20))).encode()
            path = self.projects / f'{idx}.jsonl'
            if idx:
                path.write_bytes(raw[:-200])
                self.assertFalse(tail.sample(self.now)['by_model'])
                with path.open('ab') as stream:
                    stream.write(raw[-200:] + b'\n')
            else:
                path.write_bytes(raw + b'\n')
            row = tail.sample(self.now)
            self.assertEqual(row['by_model']['claude-opus-5-5']['output_tokens'], 11)
            self.assertEqual(row['read_errors'], 0)

    def test_large_future_record_retries_from_its_first_byte(self):
        tail = TokenTail(self.projects, self.now)
        tail.sample(self.now)
        raw = json.dumps(event('future', self.now + 30, output=7, content='x' * (2 << 20)))
        (self.projects / 'future.jsonl').write_text(raw + '\n')
        self.assertFalse(tail.sample(self.now)['by_model'])
        self.assertEqual(tail.sample(self.now + 30)['by_model']['claude-opus-5-5']['output_tokens'], 7)

    def test_delayed_reports_have_scheduled_cutoffs_and_running_threshold(self):
        self.state.save('config', {'primary': 'p', 'threshold': 80})
        self.state.save('service_settings', {'loaded_at': self.now - 1, 'threshold': 90})
        p = start(self.state, 5, self.now)
        plan = review_if_due(self.state, self.now + 3 * DAY + 300)
        daily = [json.loads(path.read_text()) for path in Path(p['last_report']).parent.glob('????-??-??.json')]
        self.assertEqual(sorted(r['period_end'] for r in daily), [self.now + n * DAY for n in range(4)])
        self.assertEqual({r['switch_threshold'] for r in daily}, {90})
        self.assertEqual(plan['next_review_at'], self.now + 4 * DAY)

    def test_changing_threshold_and_model_specific_limit_are_visible(self):
        self.state.save('config', {'primary': 'personal@example.com', 'threshold': 80})
        start(self.state, 3, self.now)
        meter = Measurement(self.state, self.projects)
        for offset, threshold in [(0, 90), (60, 85)]:
            row = snapshot(self.now + offset, 4 + offset / 60)
            row['switch_threshold'] = threshold
            for reading in row['usage'].values():
                reading['windows'][0]['name'] = 'seven_day_opus'
            meter.record(row, self.now + offset)
        review = review_if_due(self.state, self.now + DAY)
        report = json.loads(Path(review['last_report']).with_suffix('.json').read_text())
        self.assertEqual(report['finding'], 'threshold_changed')
        self.assertIn('seven_day_opus', render(report))
        self.assertIn('85%, 90%', render(report))
