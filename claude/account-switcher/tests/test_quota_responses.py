from http.client import IncompleteRead
from io import BytesIO
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from api import Anthropic, ApiError, parse_usage
from switchcore.policy import PriorityPolicy
from switchcore.quota import Usage, Window


class MetadataRegressionTests(unittest.TestCase):
    def test_new_session_and_weekly_windows_both_bind_alongside_legacy_windows(self):
        response = {'five_hour': {'utilization': 5}, 'limits': [
            {'kind': 'session', 'percent': 100}, {'kind': 'weekly_all', 'percent': 35}]}
        reading = parse_usage(response, 1000)
        self.assertFalse(reading.available(1000, 90, 90))
        self.assertEqual(len({window.name for window in reading.windows}), 2)

    def test_server_backoff_is_a_lower_bound(self):
        api = Anthropic()
        error = HTTPError('fixture', 429, 'retry', {'Retry-After': '7200'}, BytesIO())
        with patch.object(api.opener, 'open', side_effect=error), self.assertRaises(ApiError) as raised:
            api.request('https://api.anthropic.com/fixture')
        self.assertGreaterEqual(raised.exception.retry_after, 7200)

    def test_interrupted_chunked_transfer_is_a_metadata_error(self):
        api = Anthropic()
        response = MagicMock()
        response.__enter__.return_value.read.side_effect = IncompleteRead(b'')
        with patch.object(api.opener, 'open', return_value=response), self.assertRaises(ApiError):
            api.request('https://api.anthropic.com/fixture')

    def test_polling_does_not_slow_as_the_threshold_approaches(self):
        policy = PriorityPolicy(90, 300)
        intervals = [policy.poll_seconds(Usage(1000, (Window('five_hour', p, None),)))
                     for p in (55, 75, 85, 86, 90)]
        self.assertEqual(intervals, sorted(intervals, reverse=True))
