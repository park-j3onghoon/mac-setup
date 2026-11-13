import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import refresh_hook
from refresh import record_switch
from storage import State


class NeededRestart:
    def __init__(self, *args, **kwargs):
        pass

    def needed(self):
        return True


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_dir = Path(self.tmp.name) / 'state'
        self.state = State(self.state_dir)
        env = {'ACCOUNT_SWITCHER_STATE_DIR': str(self.state_dir), 'CMUX_SURFACE_ID': 'S-1'}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        stdin = patch('sys.stdin', io.StringIO(json.dumps({'session_id': 'abc-123'})))
        stdin.start()
        self.addCleanup(stdin.stop)

    def test_hook_starts_a_detached_helper_when_a_restart_is_needed(self):
        """전환 뒤 아직 재시작 안 한 세션이면 훅은 분리된 도우미를 띄우고 바로 끝낸다."""
        # given
        record_switch(self.state, time.time() - 10)
        with patch.object(refresh_hook, 'SelfRestart', NeededRestart), \
                patch('subprocess.Popen') as popen:
            # when
            refresh_hook.hook()
        # then
        self.assertEqual(popen.call_args.args[0][-3:], ['--helper', 'abc-123', 'S-1'])

    def test_hook_does_nothing_without_a_pending_switch(self):
        """기록된 전환이 없으면 세션 기록도 읽지 않고 바로 끝낸다."""
        # given
        with patch.object(refresh_hook, 'SelfRestart', NeededRestart), \
                patch('subprocess.Popen') as popen:
            # when
            refresh_hook.hook()
        # then
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
