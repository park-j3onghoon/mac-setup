import io
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import refresh_hook
from storage import State, SwitcherError


def restart_stub(limited=False, needed=False):
    """A SelfRestart class whose checks answer as given; an exception given for needed is raised
    as a slow ps raises it."""
    checks = Mock(limited=Mock(return_value=limited), needed=Mock(side_effect=[needed]))
    return Mock(return_value=checks)


class HookTests(unittest.TestCase):
    def test_finishing_helper_does_not_break_the_next_helpers_lock(self):
        """다음 도우미가 잠금을 얻은 직후 이전 도우미가 끝나도 세 번째 도우미는 진입하지 못한다."""
        original = State.lock
        holders = []

        @contextmanager
        def first_lock(state, name):
            with original(state, name):
                yield
            second = original(state, name)
            second.__enter__()
            holders.append(second)

        try:
            with patch.object(State, 'lock', first_lock), patch.object(refresh_hook, 'SelfRestart') as restart:
                restart.return_value.run.return_value = 'restarted'
                refresh_hook.helper('fixture', 'surface')

            with self.assertRaises(SwitcherError):
                with original(State(self.state_dir), 'restart-fixture'):
                    pass
        finally:
            for holder in holders:
                holder.__exit__(None, None, None)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_dir = Path(self.tmp.name) / 'state'
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
        with patch.object(refresh_hook, 'SelfRestart', restart_stub(needed=True)), \
                patch('subprocess.Popen') as popen:
            # when
            refresh_hook.hook()
        # then
        self.assertEqual(popen.call_args.args[0][-3:], ['--helper', 'abc-123', 'S-1'])

    def test_hook_starts_a_helper_for_a_limit_stop_before_the_switch(self):
        """한도에 멈춘 세션은 전환 판정(ps)을 거치지 않고 도우미를 띄워, 전환이 아직 없거나 ps가 느려도 도우미가 다음 전환을 기다리게 한다."""
        # given
        restart = restart_stub(limited=True, needed=subprocess.TimeoutExpired('/bin/ps', 5))
        with patch.object(refresh_hook, 'SelfRestart', restart), \
                patch('subprocess.Popen') as popen:
            # when
            refresh_hook.hook()
        # then
        self.assertEqual(popen.call_args.args[0][-3:], ['--helper', 'abc-123', 'S-1'])

    def test_hook_does_nothing_without_a_restart_or_a_limit_stop(self):
        """재시작 대상도 아니고 한도에 멈추지도 않았으면 도우미를 띄우지 않고 바로 끝낸다."""
        # given
        with patch.object(refresh_hook, 'SelfRestart', restart_stub()), \
                patch('subprocess.Popen') as popen:
            # when
            refresh_hook.hook()
        # then
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
