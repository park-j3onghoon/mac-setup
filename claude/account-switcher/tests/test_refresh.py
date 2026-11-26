import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from refresh import (CONTINUE_PROMPT, READY_TIMEOUT_SECONDS, REFRESH_WINDOW_SECONDS,
                     RESUME_GAP_SECONDS, RESUME_PROMPT, SelfRestart, ended_with_limit_error,
                     input_ready, is_interruption, live_session, record_switch, stuck_sessions,
                     switch_pending)
from storage import State
from switchcore.cmux import CmuxTerminal

RULE = '─' * 40
SWITCHED_AT = 2_000_000_000.0
STARTED = 'Fri Nov 13 03:17:55 2026'
SURFACE = '60276FAD-6982-41D8-B120-828FA6E34BC8'
SESSION = 'aaaaaaaa-1111-2222-3333-444444444444'


def screen(prompt_line='❯', footer='  ⏵⏵ auto mode on (shift+tab to cycle)'):
    return '\n'.join(['⏺ 작업을 마쳤습니다.', '', RULE, prompt_line, RULE, '  work', footer])


def limit_choices():
    """Claude Code 2.1.325's usage-limit choices over a restarted session (2026-11-16 11:35)."""
    return '\n'.join(['  (send a prompt then to continue)', '▔' * 40,
                      '   What do you want to do?', '',
                      '   ❯ 1. Stop and wait for limit to reset',
                      '     2. Wait here, then continue automatically at 1:50pm',
                      '     3. Switch to usage credits', '     4. Upgrade your plan', '',
                      '   Enter to confirm · Esc to cancel'])


def limit_error(text="You've hit your 5-hour limit · resets 7:30pm (Asia/Seoul)"):
    return {'type': 'assistant', 'isApiErrorMessage': True,
            'message': {'model': '<synthetic>', 'content': [{'type': 'text', 'text': text}]}}


def limit_notice(text='Usage limit reached · continuing automatically at 3pm · esc to cancel'):
    """The system note Claude Code 2.1.330 writes when a turn stops at a limit after a wrap-up answer."""
    return {'type': 'system', 'subtype': 'informational', 'isMeta': False, 'content': text}


def interruption(kind='computer_slept', uuid='e0'):
    """The error Claude Code 2.1.330 writes when sleep or a lost connection cuts a response
    (2026-11-23 19:25)."""
    text = 'API Error: Your computer went to sleep mid-response.'
    return {'type': 'assistant', 'uuid': uuid, 'isApiErrorMessage': True, 'error': 'server_error',
            'apiError': kind, 'message': {'model': '<synthetic>', 'stop_reason': 'stop_sequence',
                                          'content': [{'type': 'text', 'text': text}]}}


def tool_call(uuid='t0'):
    return {'type': 'assistant', 'uuid': uuid, 'message': {
        'role': 'assistant', 'stop_reason': 'tool_use',
        'content': [{'type': 'tool_use', 'name': 'Bash'}]}}


def assistant_text(text):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'stop_reason': 'end_turn',
                                             'content': [{'type': 'text', 'text': text}]}}


def user_text(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def task_notification():
    text = '<task-notification>\n<status>failed</status>\n</task-notification>'
    return {'type': 'user', 'origin': {'kind': 'task-notification'}, 'promptSource': 'system',
            'message': {'role': 'user', 'content': text}}


class Clock:
    def __init__(self, now):
        self.now = now
        self.scheduled = []

    def __call__(self):
        return self.now

    def at(self, when, action):
        """Run action once sleep() passes when, as the service records a switch meanwhile."""
        self.scheduled.append((when, action))

    def sleep(self, seconds):
        self.now += seconds
        while self.scheduled and self.scheduled[0][0] <= self.now:
            self.scheduled.pop(0)[1]()


class SessionFixture:
    """A Claude config home with one registered session, its transcript and a state dir."""

    def __init__(self, root, status='idle', started_at=SWITCHED_AT - 600):
        self.home = Path(root) / 'claude'
        (self.home / 'sessions').mkdir(parents=True)
        (self.home / 'projects' / '-Users-test').mkdir(parents=True)
        self.state = State(Path(root) / 'state')
        self.clock = Clock(SWITCHED_AT + 60)
        self.register(status, started_at)

    def register(self, status, started_at):
        (self.home / 'sessions' / '101.json').write_text(json.dumps({
            'pid': 101, 'sessionId': SESSION, 'kind': 'interactive', 'procStart': STARTED,
            'status': status, 'startedAt': int(started_at * 1000)}))

    def started_at(self):
        return json.loads((self.home / 'sessions' / '101.json').read_text())['startedAt'] / 1000

    def transcript(self, *entries):
        path = self.home / 'projects' / '-Users-test' / f'{SESSION}.jsonl'
        path.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))

    def subagent(self, meta, written=None):
        """Subagent agent-abc's transcript and meta file, last written at written when given."""
        folder = self.home / 'projects' / '-Users-test' / SESSION / 'subagents'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'agent-abc.meta.json').write_text(json.dumps(meta))
        path = folder / 'agent-abc.jsonl'
        path.write_text(json.dumps(user_text('리뷰해 줘')) + '\n')
        if written is not None:
            os.utime(path, (written, written))

    def restart(self, runner):
        terminal = CmuxTerminal(runner=runner, path='/usr/local/bin/cmux')
        return SelfRestart(self.state, self.home, SESSION, SURFACE, terminal, runner,
                           sleep=self.clock.sleep, clock=self.clock)


class FakeRunner:
    """Answers ps and cmux like the real tools and records typed text. Typing `/restart`
    re-registers the session with a new startedAt, as Claude Code's exec restart does, and can
    bring up the usage-limit choices."""

    def __init__(self, fixture, children='', restarts=True, ps_timeouts=0, choices=False):
        self.fixture, self.children, self.restarts = fixture, children, restarts
        self.ps_timeouts, self.choices = ps_timeouts, choices
        self.screen_text = screen()
        self.typed = []

    def __call__(self, argv, **kwargs):
        if argv[0] == '/bin/ps' and self.ps_timeouts:
            self.ps_timeouts -= 1
            raise subprocess.TimeoutExpired(argv, kwargs.get('timeout'))
        if argv[0] == '/bin/ps':
            return Mock(returncode=0, stdout=self.children if '-ax' in argv else f'{STARTED}\n')
        if argv[1:3] == ['rpc', 'terminal.paste']:
            params = json.loads(argv[3])
            self.typed.append(params['text'])
            if params['text'] == '/restart' and self.restarts:
                self.fixture.register('idle', self.fixture.clock() + 1)
                if self.choices:
                    self.screen_text = limit_choices()
            return Mock(returncode=0, stdout=json.dumps({'submitted': True, 'surface_id': SURFACE}))
        return Mock(returncode=0, stdout=self.screen_text if argv[1] == 'read-screen' else '')


class FakeTerminal:
    """A terminal other than cmux: shows an empty prompt and records what it types. Typing
    `/restart` re-registers the session, as Claude Code's exec restart does."""

    def __init__(self, fixture):
        self.fixture, self.typed = fixture, []

    def pane_in(self, environment):
        return environment.get('FAKE_PANE')

    def read_screen(self, pane, lines):
        return screen()

    def submit(self, pane, text):
        self.typed.append((pane, text))
        if text == '/restart':
            self.fixture.register('idle', self.fixture.clock() + 1)


class InputReadyTests(unittest.TestCase):
    def test_an_error_hint_in_the_prompt_is_not_a_draft(self):
        """API 오류 뒤 빈 입력창에 흐리게 뜨는 안내는 초안이 아니다. 실제 화면은 ❯ 뒤에 줄바꿈 없는 공백이 온다."""
        self.assertTrue(input_ready(screen('❯\u00a0Resend your message to try again')))
        self.assertFalse(input_ready(screen('❯\u00a0Resend your message')))

    def test_paste_and_submit_use_one_rpc_without_a_timed_input_gap(self):
        """문자 입력과 Enter 사이 대기 없이 한 번의 cmux 요청으로 제출한다."""
        runner = Mock(side_effect=[Mock(returncode=0, stdout=screen()),
                                  Mock(returncode=0, stdout='{"submitted":true}')])
        restart = SelfRestart(None, '/fixture', SESSION, SURFACE,
                              CmuxTerminal(runner=runner, path='/fixture/cmux'), runner=runner, sleep=Mock())

        typed = restart.type('/restart')

        self.assertTrue(typed)
        restart.sleep.assert_not_called()
        mutation = runner.call_args_list[-1].args[0]
        self.assertEqual(mutation[1:3], ['rpc', 'terminal.paste'])
        self.assertEqual(json.loads(mutation[3]), {
            'surface_id': SURFACE, 'text': '/restart', 'submit_key': 'enter'})

    def test_partial_paste_does_not_retry_or_send_a_separate_enter(self):
        """붙여넣기만 수락되고 제출이 확인되지 않으면 명령이나 Enter를 다시 보내지 않는다."""
        runner = Mock(side_effect=[Mock(returncode=0, stdout=screen()),
                                  Mock(returncode=0, stdout='{"submitted":false}')])
        restart = SelfRestart(None, '/fixture', SESSION, SURFACE, CmuxTerminal(runner=runner, path='/fixture'),
                              runner=runner)

        with self.assertRaises(OSError):
            restart.type('/restart')

        self.assertEqual(runner.call_count, 2)

    def test_draft_typed_after_the_ready_check_is_left_alone(self):
        """준비 확인 뒤에 사용자가 초안을 쓰기 시작하면 마지막 화면 확인에서 멈추고 아무것도 넣지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SessionFixture(tmp)
            record_switch(fixture.state, SWITCHED_AT)
            runner = FakeRunner(fixture)
            def input_race(args, **kwargs):
                result = runner(args, **kwargs)
                if args[1] == 'read-screen':
                    runner.screen_text = screen(prompt_line='❯ my draft')
                return result

            outcome = fixture.restart(input_race).run()

            self.assertEqual((outcome, runner.typed), ('not_ready', []))
            self.assertIn('❯ my draft', runner.screen_text)

    def test_empty_input_box_is_ready(self):
        """입력창(❯)이 비어 있으면 명령을 넣어도 된다."""
        # when
        ready = input_ready(screen())
        # then
        self.assertTrue(ready)

    def test_draft_in_input_box_is_not_ready(self):
        """입력창에 쓰다 만 글이 있으면 명령이 그 뒤에 붙으므로 넣지 않는다."""
        # when
        ready = input_ready(screen(prompt_line='❯ 다음으로 api'))
        # then
        self.assertFalse(ready)

    def test_session_name_in_the_top_border_does_not_block(self):
        """이름을 붙인 세션은 입력창 위 테두리에 이름이 들어가도 빈 입력창으로 본다."""
        # given
        named = screen().replace(RULE, '─' * 30 + ' my-session repo 947 ─', 1)
        # when
        ready = input_ready(named)
        # then
        self.assertTrue(ready)

    def test_usage_limit_notice_under_the_input_box_does_not_block(self):
        """한도에 멈춘 세션은 입력창 아래에 한도 안내 두 줄이 더 붙어도 빈 입력창으로 본다(4723a670 화면)."""
        for wait in ('Continuing automatically at 3pm · Esc to cancel · /usage-credits to continue now',
                     'Set to continue automatically at 3pm · Esc or type to cancel'):
            limited = '\n'.join(['⏺ Usage limit reached · continuing automatically at 3pm · esc to cancel',
                                 RULE, '❯ ', RULE, '  ⚠ Usage limit reached · limit resets 3pm',
                                 f'    {wait}',
                                 '  project', '  ⏵⏵ auto mode on (shift+tab to cycle) · ← 2 agents'])

            ready = input_ready(limited)

            self.assertTrue(ready, wait)

    def test_agent_view_hint_in_the_footer_does_not_block(self):
        """상태줄의 「← 2 agents」는 새 세션에도 뜨는 안내라서 입력창 판정에 쓰지 않는다."""
        # when
        ready = input_ready(screen(footer='  ⏵⏵ auto mode on (shift+tab to cycle) · ← 2 agents'))
        # then
        self.assertTrue(ready)


class LimitErrorTests(unittest.TestCase):
    def test_limit_error_as_newest_entry_is_detected(self):
        """마지막 응답이 사용 한도 오류이면 한도에 걸려 멈춘 세션으로 본다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            fixture = SessionFixture(tmp)
            fixture.transcript(user_text('작업해 줘'), limit_error())
            # when
            limited = ended_with_limit_error(fixture.home / 'projects', SESSION)
            # then
            self.assertTrue(limited)

    def test_limit_notice_after_a_wrap_up_answer_is_a_limit_stop(self):
        """모델이 한도 유예 안에 정리 답을 끝내면 그 뒤의 「Usage limit reached」 시스템 안내로 한도에 걸려 멈춘 세션으로 본다."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SessionFixture(tmp)
            fixture.transcript(user_text('작업해 줘'), assistant_text('사용량 한도에 도달해 여기서 멈춥니다.'),
                               limit_notice(), {'type': 'system', 'subtype': 'turn_duration'})

            limited = ended_with_limit_error(fixture.home / 'projects', SESSION)

            self.assertTrue(limited)

    def test_user_message_after_limit_error_is_not_a_limit_stop(self):
        """한도 오류 뒤에 사용자가 이미 다시 입력했으면 멈춘 세션으로 보지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            fixture = SessionFixture(tmp)
            fixture.transcript(limit_error(), user_text('이어서 해줘'))
            # when
            limited = ended_with_limit_error(fixture.home / 'projects', SESSION)
            # then
            self.assertFalse(limited)

    def test_task_notifications_after_limit_error_keep_the_limit_stop(self):
        """한도 오류 뒤에 백그라운드 작업 알림만 쌓였으면 사용자가 입력한 것이 아니므로 한도에 멈춘 세션으로 본다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            fixture = SessionFixture(tmp)
            fixture.transcript(user_text('작업해 줘'), limit_error(), task_notification())
            # when
            limited = ended_with_limit_error(fixture.home / 'projects', SESSION)
            # then
            self.assertTrue(limited)


class LiveSessionTests(unittest.TestCase):
    def test_reused_pid_is_not_a_live_session(self):
        """등록된 pid를 다른 프로세스가 재사용 중이면(시작 시각이 다르면) 세션으로 보지 않는다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            fixture = SessionFixture(tmp)
            runner = Mock(return_value=Mock(stdout='Sat Nov 14 01:00:00 2026\n'))
            # when
            session = live_session(fixture.home, SESSION, runner)
            # then
            self.assertIsNone(session)


class SwitchRecordTests(unittest.TestCase):
    def test_recent_switch_is_pending(self):
        """기록된 전환이 재시작 기간 안이면 그 전환 시각을 돌려준다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            state = State(Path(tmp) / 'state')
            record_switch(state, SWITCHED_AT)
            # when
            since = switch_pending(state, SWITCHED_AT + 60)
            # then
            self.assertEqual(since, SWITCHED_AT)

    def test_old_switch_is_not_pending(self):
        """재시작 기간이 지난 전환은 남은 세션을 토큰 만료 때 넘어오게 두고 무시한다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            state = State(Path(tmp) / 'state')
            record_switch(state, SWITCHED_AT)
            # when
            since = switch_pending(state, SWITCHED_AT + REFRESH_WINDOW_SECONDS + 1)
            # then
            self.assertIsNone(since)

    def test_switch_stays_pending_while_old_access_tokens_live(self):
        """전환 직전에 받은 액세스 토큰은 8시간 유효해 세션이 그때까지 예전 계정을 쓰므로, 전환 7시간 뒤에 끝난 턴도 재시작 대상이다."""
        with tempfile.TemporaryDirectory() as tmp:
            # given
            state = State(Path(tmp) / 'state')
            record_switch(state, SWITCHED_AT)
            # when
            since = switch_pending(state, SWITCHED_AT + 7 * 3600)
            # then
            self.assertEqual(since, SWITCHED_AT)


class SelfRestartTests(unittest.TestCase):
    def test_initial_failed_ps_does_not_mean_the_session_exited(self):
        """첫 ps 실패도 살아 있는 세션의 종료로 판단하지 않고 다음 확인에서 재시도한다."""
        fixture = self.fixture()
        normal = FakeRunner(fixture)
        failed = [False]
        def runner(argv, **kwargs):
            if argv[0] == '/bin/ps' and not failed[0]:
                failed[0] = True
                return Mock(returncode=1, stdout='')
            return normal(argv, **kwargs)
        with patch('refresh.os.kill'):
            outcome = fixture.restart(runner).run()
        self.assertEqual(outcome, 'restarted')
        self.assertEqual(normal.typed, ['/restart'])

    def test_exited_session_stops_helper_without_waiting_eight_hours(self):
        """한도 오류 기록이 남아 있어도 세션 프로세스가 종료되면 도우미도 끝난다."""
        fixture = self.fixture(status='waiting')
        fixture.transcript(user_text('작업해 줘'), limit_error())
        normal = FakeRunner(fixture, children='201 101 /bin/zsh\n')
        exited = [False]
        def exit_session():
            exited[0] = True
            (fixture.home / 'sessions' / '101.json').unlink()
        def runner(argv, **kwargs):
            if exited[0] and argv[0] == '/bin/ps':
                return Mock(returncode=1, stdout='')
            return normal(argv, **kwargs)
        started = fixture.clock()
        fixture.clock.at(started + 10, exit_session)

        with patch('os.kill', side_effect=ProcessLookupError):
            outcome = fixture.restart(runner).run()

        self.assertEqual(outcome, 'session_ended')
        self.assertLess(fixture.clock() - started, 60)
        self.assertEqual(normal.typed, [])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def fixture(self, **kwargs):
        fixture = SessionFixture(self.tmp.name, **kwargs)
        record_switch(fixture.state, SWITCHED_AT)
        fixture.transcript(user_text('정리해 줘'))
        return fixture

    def test_session_started_before_the_switch_needs_a_restart(self):
        """전환 전에 시작된 세션은 옛 계정 토큰을 들고 있으므로 재시작 대상이다."""
        # given
        fixture = self.fixture()
        # when
        needed = fixture.restart(FakeRunner(fixture)).needed()
        # then
        self.assertTrue(needed)

    def test_session_started_after_the_switch_needs_no_restart(self):
        """전환 뒤에 시작됐거나 이미 다시 뜬 세션은 새 계정이므로 재시작하지 않는다."""
        # given
        fixture = self.fixture(started_at=SWITCHED_AT + 30)
        # when
        needed = fixture.restart(FakeRunner(fixture)).needed()
        # then
        self.assertFalse(needed)

    def test_idle_session_is_restarted_with_the_builtin_command(self):
        """쉬는 세션에는 자기 cmux 창의 빈 입력창으로 `/restart`와 Enter를 넣는다."""
        # given
        fixture = self.fixture()
        runner = FakeRunner(fixture)
        # when
        outcome = fixture.restart(runner).run()
        # then
        self.assertEqual((outcome, runner.typed), ('restarted', ['/restart']))

    def test_a_terminal_other_than_cmux_restarts_the_session_the_same_way(self):
        """cmux가 아닌 터미널도 창 읽기와 한 번에 넣기를 구현하면 같은 흐름으로 세션을 다시 띄운다."""
        # given
        fixture = self.fixture()
        terminal = FakeTerminal(fixture)
        restart = SelfRestart(fixture.state, fixture.home, SESSION, 'pane-7', terminal, FakeRunner(fixture),
                              sleep=fixture.clock.sleep, clock=fixture.clock)
        # when
        outcome = restart.run()
        # then
        self.assertEqual((outcome, terminal.typed), ('restarted', [('pane-7', '/restart')]))

    def test_a_failed_screen_read_is_checked_again(self):
        """화면을 한 번 못 읽으면 아직 준비 안 된 것으로 보고 다시 본 뒤 `/restart`를 넣는다."""
        # given
        fixture = self.fixture()
        runner = FakeRunner(fixture)
        failures = [Mock(returncode=1, stdout='')]

        def flaky(argv, **kwargs):
            if argv[0] != '/bin/ps' and argv[1] == 'read-screen' and failures:
                return failures.pop()
            return runner(argv, **kwargs)
        # when
        outcome = fixture.restart(flaky).run()
        # then
        self.assertEqual((outcome, runner.typed, failures), ('restarted', ['/restart'], []))

    def test_busy_session_is_not_restarted(self):
        """작업 중인 세션은 기다리다가 시간이 지나도 끝나지 않으면 아무것도 넣지 않고 포기한다."""
        # given
        fixture = self.fixture(status='busy')
        runner = FakeRunner(fixture)
        # when
        outcome = fixture.restart(runner).run()
        # then
        self.assertEqual((outcome, runner.typed), ('not_ready', []))

    def test_session_with_a_background_shell_is_not_restarted(self):
        """자식 셸(백그라운드 Bash·Monitor)이 돌면 재시작이 그 작업을 끊으므로 넣지 않는다."""
        # given
        fixture = self.fixture()
        runner = FakeRunner(fixture, children='201 101 /bin/zsh\n')
        # when
        fixture.restart(runner).run()
        # then
        self.assertEqual(runner.typed, [])

    def test_waiting_background_work_backs_off_process_snapshots(self):
        """오래 도는 작업은 전체 ps를 매 3초 반복하지 않고 점차 30초까지 늦춘다."""
        fixture = self.fixture()
        runner = Mock(wraps=FakeRunner(fixture, children='201 101 /bin/zsh\n'))

        outcome = fixture.restart(runner).run()

        self.assertEqual(outcome, 'not_ready')
        snapshots = [call for call in runner.call_args_list if '-ax' in call.args[0]]
        self.assertLessEqual(len(snapshots), 30)

    def test_limit_stopped_session_waits_out_long_background_work(self):
        """한도에 멈춘 세션은 다시 시도할 턴 끝이 없으므로, 백그라운드 셸이 10분 넘게 돌아도 끝날 때까지 기다렸다가 다시 띄우고 이어서 넣는다."""
        # given
        fixture = self.fixture(status='waiting')
        fixture.transcript(user_text('작업해 줘'), limit_error())
        runner = FakeRunner(fixture, children='201 101 /bin/zsh\n')
        shell_ends = fixture.clock() + 20 * 60
        fixture.clock.at(shell_ends, lambda: setattr(runner, 'children', ''))
        # when
        fixture.restart(runner).run()
        # then
        self.assertEqual(runner.typed, ['/restart', CONTINUE_PROMPT])
        self.assertGreater(fixture.started_at(), shell_ends)

    def test_receipt_of_a_limit_stopped_session_waits_out_long_background_work(self):
        """앞선 도우미의 대기 기록을 이어받은 한도 멈춤 세션도 백그라운드 셸이 10분 넘게 돌면 끝날 때까지 기다렸다가 다시 띄우고 이어서 넣는다."""
        fixture = self.fixture(status='waiting')
        fixture.transcript(user_text('작업해 줘'), limit_error())
        runner = FakeRunner(fixture, children='201 101 /bin/zsh\n')
        restart = fixture.restart(runner)
        fixture.state.save(restart.receipt, {'phase': 'waiting', 'pid': 101, 'procStart': STARTED,
                                             'startedAt': int(fixture.started_at() * 1000),
                                             'since': SWITCHED_AT})
        shell_ends = fixture.clock() + 20 * 60
        fixture.clock.at(shell_ends, lambda: setattr(runner, 'children', ''))

        outcome = restart.run()

        self.assertEqual((outcome, runner.typed),
                         ('restarted_and_continued', ['/restart', CONTINUE_PROMPT]))

    def test_limit_stopped_session_with_endless_background_work_is_left_alone(self):
        """한도에 멈춘 세션이라도 백그라운드 셸이 재시작 기간(8시간)과 그 뒤 이어하기 대기(8시간) 내내 돌면 아무것도 넣지 않는다."""
        # given
        fixture = self.fixture(status='waiting')
        fixture.transcript(user_text('작업해 줘'), limit_error())
        runner = FakeRunner(fixture, children='201 101 /bin/zsh\n')
        # when
        outcome = fixture.restart(runner).run()
        # then
        self.assertEqual((outcome, runner.typed), ('continuation_deferred', []))
        self.assertEqual(fixture.clock(), SWITCHED_AT + 2 * REFRESH_WINDOW_SECONDS)

    def test_work_that_outlasts_the_window_ends_in_a_continue_without_a_restart(self):
        """11-25 ai봇: 하위 작업이 재시작 기간을 넘겨 돌았으면, 끝난 뒤 재시작 없이 이어하기만 넣는다.
        그때는 세션 토큰이 만료돼 다음 요청에서 바뀐 로그인을 읽는다."""
        fixture = self.fixture()
        fixture.transcript(user_text('리뷰해 줘'), limit_error())
        runner = FakeRunner(fixture, children='201 101 /bin/zsh\n')
        work_ends = SWITCHED_AT + REFRESH_WINDOW_SECONDS + 2 * 3600
        fixture.clock.at(work_ends, lambda: setattr(runner, 'children', ''))

        outcome = fixture.restart(runner).run()

        self.assertEqual((outcome, runner.typed), ('continued_after_window', [CONTINUE_PROMPT]))
        self.assertGreaterEqual(fixture.clock(), work_ends)

    def test_a_limit_stop_found_after_the_window_is_continued_once(self):
        """재시작 기간이 지난 뒤 한도 멈춤을 처음 보면 이어하기만 넣고, 그 뒤 또 멈춘 것에는 다시 넣지 않는다."""
        for entries, expected in (
                ([user_text('작업해 줘'), limit_error()],
                 ('continued_after_window', [CONTINUE_PROMPT])),
                ([user_text('작업해 줘'), limit_error(), user_text(CONTINUE_PROMPT), limit_error()],
                 ('continuation_already_tried', []))):
            with self.subTest(entries=len(entries)):
                fixture = SessionFixture(Path(self.tmp.name) / str(len(entries)))
                record_switch(fixture.state, SWITCHED_AT)
                fixture.clock.now = SWITCHED_AT + REFRESH_WINDOW_SECONDS + 60
                fixture.transcript(*entries)
                runner = FakeRunner(fixture)

                outcome = fixture.restart(runner).run()

                self.assertEqual((outcome, runner.typed), expected)

    def test_failed_process_snapshot_never_types_restart(self):
        """ps가 실패한 동안에는 작업 유무를 확정하지 않고 재시작을 보내지 않는다."""
        fixture = SessionFixture(self.tmp.name)
        record_switch(fixture.state, SWITCHED_AT)
        normal = FakeRunner(fixture)

        def runner(argv, **kwargs):
            if '-ax' in argv:
                return Mock(returncode=1, stdout='')
            return normal(argv, **kwargs)

        outcome = fixture.restart(runner).run()

        self.assertEqual(outcome, 'not_ready')
        self.assertEqual(normal.typed, [])

    def test_session_with_a_recently_written_subagent_is_not_restarted(self):
        """서브에이전트 기록이 계속 갱신되면 백그라운드 에이전트가 도는 것으로 보고 넣지 않는다."""
        # given
        fixture = self.fixture()
        fixture.subagent({}, written=SWITCHED_AT + 60 + READY_TIMEOUT_SECONDS)
        runner = FakeRunner(fixture)
        # when
        fixture.restart(runner).run()
        # then
        self.assertEqual(runner.typed, [])

    def test_limit_stopped_session_is_restarted_and_continued(self):
        """한도 오류로 멈춘 세션은 상태가 idle이 아니어도 다시 띄우고, 뜬 뒤 이어서 하라고 넣는다."""
        # given
        fixture = self.fixture(status='waiting')
        fixture.transcript(user_text('작업해 줘'), limit_error())
        runner = FakeRunner(fixture)
        # when
        fixture.restart(runner).run()
        # then
        self.assertEqual(runner.typed, ['/restart', CONTINUE_PROMPT])

    def test_limit_choices_over_the_restarted_session_remain_with_the_user(self):
        """다시 뜬 세션의 입력창을 한도 선택창이 가리면 선택창은 사용자에게 두고 이어하기를 넣지 않는다."""
        fixture = self.fixture(status='waiting')
        fixture.transcript(user_text('작업해 줘'), limit_error())
        runner = FakeRunner(fixture, choices=True)

        outcome = fixture.restart(runner).run()

        self.assertEqual((outcome, runner.typed), ('restarted_continuation_deferred', ['/restart']))
        self.assertEqual(runner.screen_text, limit_choices())

    def test_session_stopped_at_a_limit_before_the_switch_waits_for_it(self):
        """다음 전환보다 먼저 한도에 멈춘 세션은 전환기가 다음 조회(최대 9분 뒤)에서 계정을 바꿀 때까지 기다렸다가 다시 띄우고 이어서 넣는다."""
        # given
        fixture = self.fixture(status='waiting', started_at=SWITCHED_AT + 30)
        fixture.transcript(user_text('작업해 줘'), limit_error())
        next_switch = fixture.clock() + 9 * 60
        fixture.clock.at(next_switch, lambda: record_switch(fixture.state, next_switch))
        runner = FakeRunner(fixture)
        # when
        fixture.restart(runner).run()
        # then
        self.assertEqual(runner.typed, ['/restart', CONTINUE_PROMPT])
        self.assertGreater(fixture.started_at(), next_switch)

    def test_limit_stopped_session_without_a_switch_is_left_alone(self):
        """한도에 멈췄어도 전환이 끝내 오지 않으면(두 계정 모두 한도 등) 다시 띄워도 같은 계정이므로 아무것도 넣지 않는다."""
        # given
        fixture = self.fixture(status='waiting', started_at=SWITCHED_AT + 30)
        fixture.transcript(user_text('작업해 줘'), limit_error())
        runner = FakeRunner(fixture)
        # when
        outcome = fixture.restart(runner).run()
        # then
        self.assertEqual((outcome, runner.typed), ('no_switch', []))

    def test_restart_that_never_happens_is_reported(self):
        """`/restart`를 넣어도 등록 시작 시각이 그대로면 재시작 미확인으로 알리고 더 넣지 않는다."""
        # given
        fixture = self.fixture()
        runner = FakeRunner(fixture, restarts=False)
        # when
        outcome = fixture.restart(runner).run()
        # then
        self.assertEqual((outcome, runner.typed), ('restart_unconfirmed', ['/restart']))

    def test_slow_process_list_is_retried(self):
        """여러 세션이 한도에 함께 멈춰 ps가 시간 안에 끝나지 않아도 포기하지 않고 다음 확인에서 다시 띄운다."""
        # given
        fixture = self.fixture()
        runner = FakeRunner(fixture, ps_timeouts=2)
        # when
        outcome = fixture.restart(runner).run()
        # then
        self.assertEqual((outcome, runner.typed), ('restarted', ['/restart']))


class ResumeTests(unittest.TestCase):
    """응답이 잠자기나 연결 끊김으로 끊긴 세션에 이어하기 문구를 넣는 도우미."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.count = 0

    def fixture(self, *entries):
        self.count += 1
        fixture = SessionFixture(Path(self.tmp.name) / str(self.count))
        fixture.transcript(*entries)
        return fixture

    def test_only_interruptions_are_resumed_and_limits_or_credits_are_left_to_the_user(self):
        """잠자기, 연결 실패, 무응답, 스트림 멈춤만 이어서 하고 한도나 크레딧 오류는 사람에게 둔다."""
        for kind in ('computer_slept', 'connection_failed', 'no_response', 'stream_idle_timeout'):
            self.assertTrue(is_interruption(interruption(kind)), kind)
        for kind in ('usage_limit_reached', 'model_requires_usage_credits'):
            self.assertFalse(is_interruption(interruption(kind)), kind)
        self.assertFalse(is_interruption(tool_call()))

    def test_a_turn_cut_by_sleep_is_continued_once_the_lid_opens(self):
        """뚜껑을 닫은 채 잠깐 깬 동안(그래픽 없음)에는 넣지 않고, 완전히 깨어나 입력창이 비면 이어하기 문구를 한 번 넣는다."""
        fixture = self.fixture(user_text('작업해 줘'), tool_call(), interruption())
        normal = FakeRunner(fixture)
        normal.screen_text = screen('❯\u00a0Resend your message to try again')
        opened = fixture.clock() + 3600

        def runner(argv, **kwargs):
            if argv[0] == '/usr/bin/pmset':
                graphics = 'Graphics ' if fixture.clock() >= opened else ''
                capabilities = f'Current System Capabilities are: CPU {graphics}Network\n'
                return Mock(returncode=0, stdout=capabilities)
            return normal(argv, **kwargs)

        outcome = fixture.restart(runner).resume()

        self.assertEqual((outcome, normal.typed), ('resumed', [RESUME_PROMPT]))
        self.assertGreaterEqual(fixture.clock(), opened)

    def test_the_try_comes_30_seconds_after_the_error(self):
        """오류가 난 뒤 30초가 지나야 넣는다."""
        fixture = self.fixture(user_text('작업해 줘'), interruption('connection_failed'))
        normal, typed_at = FakeRunner(fixture), []

        def runner(argv, **kwargs):
            if argv[1:3] == ['rpc', 'terminal.paste']:
                typed_at.append(fixture.clock())
            return normal(argv, **kwargs)

        started = fixture.clock()
        fixture.restart(runner).resume()

        self.assertEqual(normal.typed, [RESUME_PROMPT])
        self.assertGreaterEqual(typed_at[0] - started, RESUME_GAP_SECONDS)

    def test_three_tries_at_one_stuck_point_or_ten_until_a_turn_ends_are_the_limit(self):
        """진행 없이 한 자리에서 3번, 정상으로 끝난 턴 뒤로 모두 10번을 넣었으면 더 넣지 않는다."""
        stuck = [user_text('작업해 줘'), interruption('connection_failed')]
        for i in range(3):
            stuck += [user_text(RESUME_PROMPT), interruption('connection_failed', f'e{i + 1}')]
        progressing = [assistant_text('끝났습니다.'), user_text('작업해 줘'), interruption()]
        for i in range(10):
            progressing += [user_text(RESUME_PROMPT), tool_call(f't{i}'),
                            interruption(uuid=f'e{i + 1}')]
        for entries in (stuck, progressing):
            with self.subTest(entries=len(entries)):
                fixture = self.fixture(*entries)
                runner = FakeRunner(fixture)

                outcome = fixture.restart(runner).resume()

                self.assertEqual((outcome, runner.typed), ('resume_gave_up', []))

    def test_a_normal_turn_end_or_progress_starts_the_count_again(self):
        """정상으로 끝난 턴 앞의 시도는 세지 않고, 이어서 일을 진행한 뒤 다시 멈추면 새 자리로 센다."""
        tries = [user_text(RESUME_PROMPT), interruption('connection_failed', 'r1'),
                 user_text(RESUME_PROMPT), interruption('connection_failed', 'r2'),
                 user_text(RESUME_PROMPT)]
        after_end = [user_text('작업해 줘'), interruption()] + tries + [
            assistant_text('끝났습니다.'), user_text('다음 작업'), interruption(uuid='last')]
        after_progress = [user_text('작업해 줘'), interruption()] + tries + [
            tool_call(), interruption(uuid='last')]
        for entries in (after_end, after_progress):
            with self.subTest(entries=len(entries)):
                fixture = self.fixture(*entries)
                runner = FakeRunner(fixture)

                outcome = fixture.restart(runner).resume()

                self.assertEqual((outcome, runner.typed), ('resumed', [RESUME_PROMPT]))

    def test_the_error_entry_written_after_the_hook_is_still_resumed(self):
        """실패 훅은 Claude Code가 오류 항목을 쓰기 전에 돌므로, 도우미는 30초 뒤 기록을 보고 판단한다."""
        fixture = self.fixture(user_text('작업해 줘'))
        runner = FakeRunner(fixture)
        fixture.clock.at(fixture.clock() + 1, lambda: fixture.transcript(
            user_text('작업해 줘'), interruption('connection_failed')))

        outcome = fixture.restart(runner).resume()

        self.assertEqual((outcome, runner.typed), ('resumed', [RESUME_PROMPT]))

    def test_a_session_continued_meanwhile_is_left_alone(self):
        """기다리는 동안 사용자가 직접 이어서 입력했으면 넣지 않는다."""
        fixture = self.fixture(user_text('작업해 줘'), interruption())
        runner = FakeRunner(fixture)
        fixture.clock.at(fixture.clock() + 10, lambda: fixture.transcript(
            user_text('작업해 줘'), interruption(), user_text('계속해')))

        outcome = fixture.restart(runner).resume()

        self.assertEqual((outcome, runner.typed), ('resume_superseded', []))

    def test_background_work_does_not_hold_back_the_resume_but_an_answer_or_a_draft_does(self):
        """이어하기는 재시작과 달리 백그라운드 작업을 끊지 않아 기다리지 않지만, 응답 중이거나 입력창에 초안이 있으면 넣지 않는다."""
        fixture = self.fixture(user_text('작업해 줘'), interruption())
        busy_shell = FakeRunner(fixture, children='201 101 /bin/zsh\n')
        self.assertEqual(fixture.restart(busy_shell).resume(), 'resumed')

        fixture = self.fixture(user_text('작업해 줘'), interruption())
        drafting = FakeRunner(fixture)
        drafting.screen_text = screen('❯ 아직 쓰는 중')
        outcome = fixture.restart(drafting).resume()
        self.assertEqual((outcome, drafting.typed), ('resume_not_ready', []))

        fixture = self.fixture(user_text('작업해 줘'), interruption())
        fixture.register('busy', fixture.started_at())
        answering = FakeRunner(fixture)
        outcome = fixture.restart(answering).resume()
        self.assertEqual((outcome, answering.typed), ('resume_not_ready', []))


class StuckSessionTests(unittest.TestCase):
    """훅이 다시 오지 않는 멈춘 세션을 찾는다(11-25 ai봇)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.count = 0

    def found(self, *entries, environment=f'claude CMUX_SURFACE_ID={SURFACE} TERM=xterm',
              window_open=True, ps_status=0):
        self.count += 1
        fixture = SessionFixture(Path(self.tmp.name) / str(self.count))
        record_switch(fixture.state, SWITCHED_AT)
        fixture.transcript(*entries)

        def runner(argv, **kwargs):
            return Mock(returncode=ps_status, stdout='' if ps_status else environment + '\n')
        now = SWITCHED_AT + (60 if window_open else REFRESH_WINDOW_SECONDS + 60)
        with patch('refresh.time.time', return_value=now):
            return stuck_sessions(fixture.home, fixture.state, CmuxTerminal(), runner)

    def test_a_limit_stop_or_a_cut_turn_in_a_cmux_surface_is_found(self):
        self.assertEqual(self.found(user_text('작업해 줘'), limit_error()),
                         [(SESSION, SURFACE, 101, '--helper')])
        self.assertEqual(self.found(user_text('작업해 줘'), interruption()),
                         [(SESSION, SURFACE, 101, '--resume')])

    def test_sessions_a_helper_cannot_continue_are_left_out(self):
        """끝난 턴, cmux 밖이나 관리 실행기 세션, 이어하기를 다 쓴 끊김, 기간이 지나 한 번 넣은 한도 멈춤은 뺀다."""
        cut = [user_text('작업해 줘'), interruption()]
        for i in range(3):
            cut += [user_text(RESUME_PROMPT), interruption(uuid=f'e{i + 1}')]
        retried = [user_text('작업해 줘'), limit_error(), user_text(CONTINUE_PROMPT), limit_error()]
        self.assertEqual(self.found(user_text('작업해 줘'), assistant_text('끝났습니다.')), [])
        outside = 'claude TERM=xterm'
        self.assertEqual(self.found(user_text('작업해 줘'), limit_error(), environment=outside), [])
        managed = f'claude CMUX_SURFACE_ID={SURFACE} MAC_SETUP_MANAGED_CLAUDE_PID=7'
        self.assertEqual(self.found(user_text('작업해 줘'), limit_error(), environment=managed), [])
        self.assertEqual(self.found(*cut), [])
        self.assertEqual(self.found(*retried, window_open=False), [])
        # Within the window a restart can still move it to the new account.
        self.assertEqual(self.found(*retried), [(SESSION, SURFACE, 101, '--helper')])

    def test_a_session_whose_process_ended_is_left_out(self):
        """등록 파일이 남아 있어도 프로세스가 끝나 그 환경을 읽지 못하면 뺀다."""
        self.assertEqual(self.found(user_text('작업해 줘'), limit_error(), ps_status=1), [])

if __name__ == '__main__':
    unittest.main()
