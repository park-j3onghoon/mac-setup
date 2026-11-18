import unittest
from unittest.mock import patch

from service import running


class ServiceTest(unittest.TestCase):
    def test_reused_pid_and_stale_heartbeat_are_not_healthy(self):
        """PID가 살아 있어도 시작 시각과 최근 heartbeat가 모두 일치해야 준비 상태다."""
        state = {'pid': 4321, 'pid_start': 'original', 'updated_at': 1000, 'status': 'ready'}
        with patch('service.time.time', return_value=1001), \
                patch('service.process_start', return_value='original'):
            self.assertTrue(running(state))
            self.assertFalse(running({**state, 'updated_at': 800}))
            self.assertFalse(running({**state, 'pid_start': 'reused'}))
            self.assertFalse(running({**state, 'pid_start': None}))
            self.assertFalse(running({**state, 'status': 'failed'}))


if __name__ == '__main__':
    unittest.main()
