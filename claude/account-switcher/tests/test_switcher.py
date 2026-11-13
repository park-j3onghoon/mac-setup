import contextlib
import io
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from compatibility import FAILURE
from helpers import make_app
from macos import KeychainError
from storage import SwitcherError
from refresh import switch_pending
from switcher import (HALT_POLL_SECONDS, halts_keychain_work, record_if_switched,
                      run_state_command, tick_once)


class KeychainHaltRuleTests(unittest.TestCase):
    def test_keychain_error_halts(self):
        """키체인 읽기·쓰기 실패는 모든 Claude 세션의 승인창으로 번질 수 있어 자동 재시도를 멈춘다."""
        # when
        halted = halts_keychain_work(KeychainError('Native Claude credential read failed'))
        # then
        self.assertTrue(halted)

    def test_compatibility_failure_halts(self):
        """호환성 검사는 Claude Code로 로그인 정보를 읽으므로, 실패하면 같은 이유로 멈춘다."""
        # when
        halted = halts_keychain_work(SwitcherError(FAILURE))
        # then
        self.assertTrue(halted)

    def test_unrelated_switcher_error_keeps_retrying(self):
        """키체인과 무관한 오류(다른 계정으로 로그인됨 등)는 다음 주기에 다시 시도한다."""
        # when
        halted = halts_keychain_work(
            SwitcherError('Current Claude login is outside the configured account roster'))
        # then
        self.assertFalse(halted)


class KeychainHaltServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = make_app(self.tmp.name)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def test_keychain_error_during_tick_saves_a_halt(self):
        """주기 실행 중 키체인 오류가 나면 halt를 남겨 다음 주기부터 로그인 정보를 읽지 않게 한다."""
        # given
        self.app.tick = Mock(side_effect=KeychainError('Native Claude credential read failed'))
        # when
        tick_once(self.app, True, None)
        # then
        self.assertEqual(self.app.state.load('halt')['error_type'], 'KeychainError')

    def test_halted_service_skips_the_tick(self):
        """halt가 남아 있으면 tick을 부르지 않고 긴 간격으로 기다린다."""
        # given
        self.app.state.save('halt', {'reason': 'Native Claude credential read failed'})
        self.app.tick = Mock()
        # when
        report, delay, _ = tick_once(self.app, True, None)
        # then
        self.app.tick.assert_not_called()
        self.assertEqual((report, delay), (None, HALT_POLL_SECONDS))

    def test_resume_clears_the_halt(self):
        """resume 명령은 남은 halt를 지워 서비스가 다음 주기에 다시 돌게 한다."""
        # given
        self.app.state.save('halt', {'reason': 'Native Claude credential read failed'})
        # when
        run_state_command(SimpleNamespace(command='resume'), self.app.state)
        # then
        self.assertEqual(self.app.state.load('halt'), {})


class RecordSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = make_app(self.tmp.name).state

    def test_switch_is_recorded_for_session_restarts(self):
        """계정을 바꾼 보고는 그 시각을 남겨, 각 세션의 훅이 그 전에 시작된 세션을 다시 띄우게 한다."""
        # when
        record_if_switched(self.state, {'switched': True, 'observed_at': 1_000.0})
        # then
        self.assertEqual(switch_pending(self.state, 1_060.0), 1_000.0)

    def test_report_without_a_switch_records_nothing(self):
        """계정을 바꾸지 않은 보고는 재시작할 시각을 남기지 않는다."""
        # when
        record_if_switched(self.state, {'switched': False, 'observed_at': 1_000.0})
        # then
        self.assertIsNone(switch_pending(self.state, 1_060.0))


if __name__ == '__main__':
    unittest.main()
