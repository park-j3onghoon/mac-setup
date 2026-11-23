import contextlib
import io
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from compatibility import FAILURE
from helpers import NOW, make_app
from macos import KeychainError, system_awake
from storage import SwitcherError
from refresh import switch_pending
from switcher import (HALT_POLL_SECONDS, halts_keychain_work,
                      run, run_state_command, tick_once)


class PreferencePollingTests(unittest.TestCase):
    def test_new_preference_wakes_polling_but_preserves_retry_after(self):
        """새 ID 요청은 대기를 깨우되 서버가 정한 재시도 시각까지 기다린다."""
        for retry_after, expected in ((0, 2), (10, 10)):
            with self.subTest(retry_after=retry_after), tempfile.TemporaryDirectory() as folder:
                app = make_app(folder)
                app.state.save('runtime', {'retry_after': retry_after})
                clock, ticks = [0], []
                stop = Mock()
                stop.is_set.side_effect = lambda: len(ticks) >= 2

                def wait(seconds):
                    clock[0] += seconds
                    app.state.save('preference', {'preferred': 'personal@example.com', 'requested_at': 1})

                def tick(*args):
                    ticks.append(clock[0])
                    return None, 60, None

                stop.wait.side_effect = wait
                with patch('switcher.threading.Event', return_value=stop), patch('switcher.signal.signal'), \
                        patch('switcher.time.monotonic', side_effect=lambda: clock[0]), \
                        patch('switcher.time.time', side_effect=lambda: clock[0]), \
                        patch('switcher.tick_once', side_effect=tick), patch('switcher.Measurement'), \
                        patch('switcher.measure_and_review', return_value=60):
                    run(app, True)

                self.assertEqual(ticks, [0, expected])

    def test_usage_request_reads_once_soon_but_preserves_retry_after(self):
        """대시보드의 지금 확인 요청은 대기를 깨워 한도를 바로 읽되, 서버가 정한 재시도 시각을 지키고 같은 요청으로 두 번 읽지 않는다."""
        for retry_after, expected in ((0, [0, 2, 62]), (10, [0, 10, 70])):
            with self.subTest(retry_after=retry_after), tempfile.TemporaryDirectory() as folder:
                app = make_app(folder)
                app.state.save('runtime', {'retry_after': retry_after})
                clock, ticks = [0], []
                stop = Mock()
                stop.is_set.side_effect = lambda: len(ticks) >= 3

                def wait(seconds):
                    clock[0] += seconds
                    app.state.save('usage_request', {'requested_at': 1})

                def tick(*args):
                    ticks.append(clock[0])
                    return None, 60, None

                stop.wait.side_effect = wait
                with patch('switcher.threading.Event', return_value=stop), patch('switcher.signal.signal'), \
                        patch('switcher.time.monotonic', side_effect=lambda: clock[0]), \
                        patch('switcher.time.time', side_effect=lambda: clock[0]), \
                        patch('switcher.tick_once', side_effect=tick), patch('switcher.Measurement'), \
                        patch('switcher.measure_and_review', return_value=60):
                    run(app, True)

                self.assertEqual(ticks, expected)


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
        halted = halts_keychain_work(SwitcherError(FAILURE), awake=lambda: True)
        # then
        self.assertTrue(halted)

    def test_compatibility_failure_during_dark_wake_keeps_retrying(self):
        """뚜껑을 닫은 채 잠깐 깬 다크 웨이크(그래픽 없음)에서 난 호환성 검사 실패는 승인창과 무관해 멈추지 않고 다음 주기에 다시 검사한다."""
        # when
        halted = halts_keychain_work(SwitcherError(FAILURE), awake=lambda: False)
        # then
        self.assertFalse(halted)

    def test_dark_wake_is_read_from_the_system_capabilities(self):
        """pmset이 알려 주는 시스템 기능에 Graphics가 없으면 다크 웨이크로 본다."""
        # given
        cases = (('Current System Capabilities are: CPU Graphics Audio Network', True),
                 ('Current System Capabilities are: CPU Network', False))
        for output, expected in cases:
            with self.subTest(output=output):
                runner = Mock(return_value=Mock(returncode=0, stdout=output))
                # when
                awake = system_awake(runner)
                # then
                self.assertEqual(awake, expected)

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
        self.app = make_app(self.tmp.name)
        self.state = self.app.state

    def test_switch_is_recorded_for_session_restarts(self):
        """계정을 바꾼 보고는 그 시각을 남겨, 각 세션의 훅이 그 전에 시작된 세션을 다시 띄우게 한다."""
        # when
        self.app.tick(apply=True, now=NOW)
        # then
        self.assertEqual(switch_pending(self.state, NOW + 60), NOW)

    def test_report_without_a_switch_records_nothing(self):
        """계정을 바꾸지 않은 보고는 재시작할 시각을 남기지 않는다."""
        # when
        self.app.api.percent['token-personal'] = 20
        self.app.tick(apply=True, now=NOW)
        # then
        self.assertIsNone(switch_pending(self.state, NOW + 60))


if __name__ == '__main__':
    unittest.main()
