import io
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import refresh_hook
from refresh import SessionEnded
from storage import State, SwitcherError

# Before setUp replaces it, so the once-a-minute rule itself can be tested.
SWEEP_IF_DUE = refresh_hook.sweep_if_due


def restart_stub(limited=False, needed=False, interrupted=False):
    """A SelfRestart class whose checks answer as given; an exception given for needed is raised
    as a slow ps raises it."""
    checks = Mock(limited=Mock(return_value=limited), needed=Mock(side_effect=[needed]),
                  interrupted=Mock(return_value=interrupted))
    checks.pending.return_value = {}
    checks.receipt = 'handoff-test'
    return Mock(return_value=checks)


class HookTests(unittest.TestCase):
    def test_the_hook_loads_no_network_or_service_modules(self):
        """훅은 모든 세션의 매 턴 끝에 돌므로 HTTP·TLS 모듈과 서비스 코드를 불러오지 않는다."""
        script = ('import sys, refresh_hook; '
                  'print(sorted(m for m in ("http.client", "ssl", "service") if m in sys.modules))')

        result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1], check=True, timeout=30)

        self.assertEqual(result.stdout.strip(), '[]')

    def test_ended_session_is_a_successful_noop_for_the_stop_hook(self):
        """등록이 이미 사라진 세션은 Stop 훅 오류를 만들지 않는다."""
        with patch.object(refresh_hook, 'SelfRestart', restart_stub(needed=SessionEnded())), \
                patch('subprocess.Popen') as popen:
            self.assertEqual(refresh_hook.hook(), 0)
        popen.assert_not_called()

    def test_finishing_helper_does_not_break_the_next_helpers_lock(self):
        """다음 도우미가 잠금을 얻은 직후 이전 도우미가 끝나도 세 번째 도우미는 진입하지 못한다."""
        original = State.lock
        holders = []

        @contextmanager
        def first_lock(state, name, **options):
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
                with original(State(self.state_dir), refresh_hook.helper_lock('--helper', 'fixture', 'surface')):
                    pass
        finally:
            for holder in holders:
                holder.__exit__(None, None, None)

    def setUp(self):
        stubs = [('hook_ancestors', [11]), ('switch_pending', 123), ('sweep_if_due', None)]
        for name, value in stubs:
            mocked = patch.object(refresh_hook, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)
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

    def test_managed_marker_only_suppresses_its_own_session(self):
        for owner, calls in [('abc-123', 0), ('different-session', 1)]:
            with self.subTest(owner=owner), patch.dict(os.environ, MAC_SETUP_MANAGED_CLAUDE_PID='123'), \
                    patch.object(refresh_hook, 'read_json', return_value={'sessionId': owner}), \
                    patch.object(refresh_hook, 'SelfRestart', restart_stub(needed=True)), \
                    patch('subprocess.Popen') as popen, \
                    patch('sys.stdin', io.StringIO('{"session_id":"abc-123"}')):
                refresh_hook.hook()
                self.assertEqual(popen.call_count, calls)

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

    def test_hook_starts_a_resume_helper_for_a_turn_an_interruption_cut(self):
        """잠자기나 연결 끊김으로 끊긴 턴이면 이어하기 도우미를 띄우고, 전환 뒤 재시작도 필요하면 재시작 도우미도 띄운다."""
        resume, restart = ['--resume', 'abc-123', 'S-1'], ['--helper', 'abc-123', 'S-1']
        for needed, modes in ((False, [resume]), (True, [resume, restart])):
            stub = restart_stub(needed=needed, interrupted=True)
            with self.subTest(needed=needed), patch.object(refresh_hook, 'SelfRestart', stub), \
                    patch('subprocess.Popen') as popen, \
                    patch('sys.stdin', io.StringIO('{"session_id":"abc-123"}')):
                refresh_hook.hook()
                self.assertEqual([call.args[0][-3:] for call in popen.call_args_list], modes)

    def test_a_failed_turn_is_judged_before_its_error_is_written(self):
        """실패 훅이 오류 항목보다 먼저 와도, 한도 문장이면 재시작 도우미를, 다른 실패면 이어하기 도우미를 띄운다."""
        limit = "You've hit your 5-hour limit · resets 7:30pm (Asia/Seoul)"
        for message, modes in ((limit, ['--helper']), ('API Error: Connection refused', ['--resume'])):
            payload = {'session_id': 'abc-123', 'hook_event_name': 'StopFailure',
                       'error': 'server_error', 'last_assistant_message': message}
            stdin = io.StringIO(json.dumps(payload))
            with self.subTest(modes=modes), patch.object(refresh_hook, 'SelfRestart', restart_stub()), \
                    patch('subprocess.Popen') as popen, patch('sys.stdin', stdin):
                refresh_hook.hook()
                self.assertEqual([call.args[0][-3] for call in popen.call_args_list], modes)

    def test_resume_helper_waits_its_turn_and_logs_what_it_did(self):
        """이어하기 도우미는 같은 세션의 앞선 이어하기 도우미가 끝나기를 기다렸다가 결과를 기록한다."""
        with patch.object(refresh_hook, 'SelfRestart') as restart, \
                patch.object(State, 'lock', wraps=State(self.state_dir).lock) as lock:
            restart.return_value.receipt = 'handoff-0123'
            restart.return_value.resume.return_value = 'resumed'
            refresh_hook.helper('fixture', 'surface', '--resume')
        self.assertEqual((lock.call_args.args[-1], lock.call_args.kwargs),
                         (refresh_hook.helper_lock('--resume', 'fixture', 'surface'),
                          {'blocking': True}))
        restart.return_value.run.assert_not_called()
        log = (self.state_dir / refresh_hook.LOG).read_text()
        self.assertEqual(json.loads(log)['outcome'], 'resumed')

    def test_sweep_starts_a_helper_only_for_a_stopped_session_no_helper_holds(self):
        """멈춘 세션마다 도우미를 띄우되, 이미 그 세션을 맡은 도우미가 있으면 띄우지 않는다."""
        state = State(self.state_dir)
        stuck = [('fixture', 'S-9', 4242, '--helper')]
        with patch.object(refresh_hook, 'stuck_sessions', return_value=stuck), \
                patch('subprocess.Popen') as popen:
            refresh_hook.sweep(state)
            with state.lock(refresh_hook.helper_lock('--helper', 'fixture', 'S-9')):
                refresh_hook.sweep(state)
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(popen.call_args.args[0][-3:], ['--helper', 'fixture', 'S-9'])
        environment = popen.call_args.kwargs['env']
        self.assertEqual((environment['CLAUDE_SWITCHER_REGISTRY_PID'],
                          environment['ACCOUNT_SWITCHER_STATE_DIR']), ('4242', str(state.root)))

    def test_turn_ends_start_a_sweep_at_most_once_a_minute(self):
        """어느 세션이든 턴이 끝나면 멈춘 세션 찾기를 띄우되 1분에 한 번만 띄운다."""
        state = State(self.state_dir)
        with patch('subprocess.Popen') as popen, \
                patch.object(refresh_hook.time, 'time', side_effect=[100, 130, 161]):
            for _ in range(3):
                SWEEP_IF_DUE(state)
        self.assertEqual([call.args[0][2:] for call in popen.call_args_list],
                         [['--sweep'], ['--sweep']])

    def test_an_unknown_terminal_setting_is_logged_and_starts_nothing(self):
        """설정의 터미널 이름이 repo에 없으면 훅은 아무것도 띄우지 않고 재시작 기록에 설정 오류를 남긴다."""
        # given
        State(self.state_dir).save('config', {'terminal': 'tmux'})
        with patch.object(refresh_hook, 'SelfRestart', restart_stub(needed=True)), \
                patch('subprocess.Popen') as popen:
            # when
            result = refresh_hook.hook()
        # then
        popen.assert_not_called()
        log = (self.state_dir / refresh_hook.LOG).read_text()
        self.assertEqual((result, json.loads(log)['outcome']), (0, 'config_error:terminal'))

    def test_an_unreadable_settings_file_is_not_logged_as_a_terminal_error(self):
        """설정 파일을 못 읽으면 다른 훅 오류처럼 조용히 넘기고, 터미널 이름 오류로 기록하지 않는다."""
        # given
        state = State(self.state_dir)
        (state.root / 'config.json').write_text('{"terminal": ')
        with patch.object(refresh_hook, 'SelfRestart', restart_stub(needed=True)), \
                patch('subprocess.Popen') as popen:
            # when
            result = refresh_hook.hook()
        # then
        popen.assert_not_called()
        self.assertEqual((result, (state.root / refresh_hook.LOG).exists()), (0, False))

    def test_the_helper_gets_the_terminal_the_hook_chose(self):
        """훅이 고른 터미널 이름을 도우미에 넘겨, 그 사이 설정이 바뀌어도 둘이 같은 터미널을 쓴다."""
        # given
        State(self.state_dir).save('config', {'terminal': 'cmux'})
        with patch.object(refresh_hook, 'SelfRestart', restart_stub(needed=True)), \
                patch('subprocess.Popen') as popen:
            # when
            refresh_hook.hook()
        # then
        self.assertEqual(popen.call_args.kwargs['env']['CLAUDE_SWITCHER_TERMINAL'], 'cmux')

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
