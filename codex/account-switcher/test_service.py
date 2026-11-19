from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

import service
from service import running


class ServiceTest(unittest.TestCase):
    def test_supervisor_is_registered_once_with_automatic_restart(self):
        """첫 실행이 감독 복구를 등록하고 다음 실행은 살아 있는 작업을 재시작하지 않는다."""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            loaded = [False]
            commands = []

            def launchctl(arguments, **kwargs):
                commands.append(arguments)
                if arguments[1] == 'bootstrap':
                    loaded[0] = True
                    return Mock(returncode=0)
                return Mock(returncode=0 if loaded[0] else 113)

            with patch('service.Path.home', return_value=home), \
                    patch('service.subprocess.run', side_effect=launchctl):
                service.install_service()
                service.install_service()

            destination = home / 'Library/LaunchAgents/local.codex-account-switcher.plist'
            configuration = plistlib.loads(destination.read_bytes())
            self.assertTrue(configuration['KeepAlive'])
            self.assertTrue(configuration['AbandonProcessGroup'])
            self.assertEqual(sum(command[1] == 'bootstrap' for command in commands), 1)
            self.assertFalse(any(command[1] in ('bootout', 'kickstart') for command in commands))
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

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
