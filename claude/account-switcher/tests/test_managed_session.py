import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from managed_session import (claim_continuation, finish_receipt, recovery_message, run_session,
                             resume_options, switch_target)
from storage import State


class ManagedSessionTests(unittest.TestCase):
    def test_resuming_keeps_options_and_drops_initial_prompt_and_session_selectors(self):
        self.assertEqual(resume_options(['--model', 'opus', '--effort=max', '--fork-session',
                                         '-r', 'before', '--', 'old task']),
                         ['--model', 'opus', '--effort=max'])
        self.assertEqual(resume_options(['--allowedTools', 'Read', 'Edit', '--add-dir=../notes',
                                         '--', 'old task']),
                         ['--allowedTools', 'Read', 'Edit', '--add-dir=../notes'])
        for args in (['auth', 'login'], ['-p', 'request'], ['--bg'], ['--worktree', 'new'],
                     ['--unknown-option'], ['--settings', '/custom/settings.json']):
            with self.subTest(args=args):
                self.assertIsNone(resume_options(args))

    def test_shared_session_can_get_one_recovery_per_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / 'state')
            gate = threading.Barrier(2)
            results = []
            def claim():
                gate.wait()
                results.append(claim_continuation(state, 'same', 10))
            threads = [threading.Thread(target=claim) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(sorted(results), [False, True])
            self.assertTrue(claim_continuation(state, 'same', 11))
            self.assertFalse(claim_continuation(state, 'late', 10))

    def test_claim_is_durable_before_a_recovery_process_can_start(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / 'state')
            calls = []
            with patch.object(state, 'save', side_effect=OSError('storage unavailable')), patch('managed_session.notice'):
                claim_continuation(state, 'example', 10, launch=calls.append)
            self.assertEqual(calls, [False])

    def test_receipt_is_confirmed_only_by_an_actual_user_message(self):
        with tempfile.TemporaryDirectory() as directory, patch('managed_session.notice'):
            root = Path(directory)
            state = State(root / 'state')
            projects = root / 'projects'
            project = projects / 'one'
            project.mkdir(parents=True)
            path = project / 'same.jsonl'
            expected = recovery_message('same', 10)
            path.write_text(json.dumps({'type': 'assistant', 'message': {'content': expected}}))
            calls = []
            claim_continuation(state, 'same', 10, launch=calls.append, projects=projects)
            claim_continuation(state, 'same', 10, launch=calls.append, projects=projects)
            self.assertEqual(calls, [True, False])
            finish_receipt(state, 'same', 10, projects, clean_exit=True)
            self.assertEqual(state.load('resume_prompts')['pending'], [])
            claim_continuation(state, 'same', 10, launch=calls.append, projects=projects)
            self.assertEqual(calls[-1], True)
            with path.open('a') as stream:
                stream.write('\n' + json.dumps({'type': 'user', 'message': {'content': [{'type': 'text', 'text': expected}]}}))
            finish_receipt(state, 'same', 10, projects, clean_exit=False)
            self.assertEqual(state.load('resume_prompts')['sessions'], ['same'])
            claim_continuation(state, 'same', 10, launch=calls.append, projects=projects)
            self.assertEqual(calls[-1], False)

    def test_ambiguous_abnormal_exit_keeps_claim_for_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory, patch('managed_session.notice') as alert:
            root = Path(directory)
            state = State(root / 'state')
            calls = []
            claim_continuation(state, 'same', 10, launch=calls.append)
            finish_receipt(state, 'same', 10, root / 'absent', clean_exit=False)
            claim_continuation(state, 'same', 10, launch=calls.append)
            self.assertEqual(calls, [True, False])
            self.assertIn('same', state.load('resume_prompts')['pending'])
            self.assertTrue(alert.called)

    def test_explicit_exec_failure_releases_reservation_before_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / 'state')
            with self.assertRaises(FileNotFoundError):
                claim_continuation(state, 'same', 10, launch=Mock(side_effect=FileNotFoundError()))
            self.assertFalse(state.load('resume_prompts')['pending'])
            launch = Mock()
            claim_continuation(state, 'same', 10, launch=launch)
            launch.assert_called_once_with(True)

    def test_new_event_after_clock_rollback_can_receive_a_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(Path(directory) / 'state')
            state.save('session_refresh', {'since': 300})
            self.assertTrue(claim_continuation(state, 'same', 300))
            state.save('session_refresh', {'since': 110})
            self.assertTrue(claim_continuation(state, 'same', 110))
            self.assertFalse(claim_continuation(state, 'same', 300))

    def test_fresh_launch_ignores_an_existing_event_when_clock_catches_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = State(root / 'state')
            state.save('session_refresh', {'since': 200})
            child = Mock()
            child.wait.side_effect = [subprocess.TimeoutExpired('fixture', .1), 0]
            with patch('managed_session.subprocess.Popen', return_value=child) as launch, \
                 patch('managed_session.time.time', side_effect=[100, 201]), \
                 patch('managed_session.switch_target') as target:
                self.assertEqual(run_session('fixture', [], [], state, root, .1), 0)
            target.assert_not_called()
            launch.assert_called_once()

    def test_slow_explicit_shutdown_reports_the_owned_pid_and_does_not_start_a_second_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = State(root / 'state')
            hooks = {}
            def set_signal(sig, handler):
                previous = hooks.get(sig)
                hooks[sig] = handler
                return previous
            child = Mock(pid=4242)
            child.poll.return_value = None
            steps = iter(['signal', 'wait', 'exit'])
            def wait(timeout):
                step = next(steps)
                if step == 'signal':
                    hooks[signal.SIGTERM](signal.SIGTERM, None)
                if step == 'exit':
                    return -signal.SIGTERM
                raise subprocess.TimeoutExpired('fixture', timeout)
            child.wait.side_effect = wait
            with patch('managed_session.subprocess.Popen', return_value=child) as launch, \
                 patch('managed_session.signal.signal', side_effect=set_signal), \
                 patch('managed_session.time.monotonic', side_effect=[0, 0, 11]), \
                 patch('managed_session.notice') as notice:
                self.assertEqual(run_session('fixture', [], [], state, root, .1), 143)
            child.send_signal.assert_called_once_with(signal.SIGTERM)
            self.assertIn('4242', notice.call_args.args[0])
            launch.assert_called_once()

    def test_read_only_errors_unfinished_tools_and_recent_completed_agents(self):
        sid = 'a828b6ac-3183-4bc2-a662-ab93319eb565'
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / 'sessions').mkdir()
            project = home / 'projects' / 'project'
            agents = project / sid / 'subagents'
            agents.mkdir(parents=True)
            registry = home / 'sessions/4242.json'
            registry.write_text(json.dumps({'sessionId': sid, 'pid': 4242, 'startedAt': 10000,
                                            'kind': 'interactive', 'status': 'idle', 'cwd': directory}))
            log = project / (sid + '.jsonl')
            end = {'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'content': []}}
            (agents / 'finished.jsonl').write_text(json.dumps(end))
            (agents / 'finished.meta.json').write_text(json.dumps({'finished': True}))
            with patch('managed_session.process_children', return_value={}):
                for entry, need in [(end, False), (dict(end, isApiErrorMessage=True), True),
                                    ({'type': 'assistant', 'message': {'stop_reason':'tool_use'}}, True),
                                    ({'type': 'user', 'message': {'content':'unfinished'}}, True)]:
                    log.write_text(json.dumps(entry))
                    self.assertEqual(switch_target(4242, 9, 11, home)[2], need)
                self.assertIsNone(switch_target(4242, 10.1, 11, home))
                with patch('managed_session.time.time', return_value=11):
                    for event in [11.001, float('inf'), float('nan'), True, '11', 9]:
                        self.assertIsNone(switch_target(4242, 9, event, home))
                    self.assertIsNotNone(switch_target(4242, 9, 11, home))
                log.write_text('{"type":"system"}')
                self.assertIsNone(switch_target(4242, 9, 11, home))

    def test_only_unfinished_work_gets_the_recovery_prompt(self):
        cases = [('busy', None, False, True), ('idle', None, False, False), ('busy', 'end_turn', False, False),
                 ('idle', 'tool_use', False, True), ('busy', 'end_turn', True, True)]
        for status, final_reason, background, recovery in cases:
            with self.subTest(status=status, final_reason=final_reason), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = State(root / 'state')
                home = root / 'config'
                (home / 'sessions').mkdir(parents=True)
                project = home / 'projects' / 'project'
                project.mkdir(parents=True)
                sid = 'a828b6ac-3183-4bc2-a662-ab93319eb565'
                (project / (sid + '.jsonl')).write_text(json.dumps({
                    'uuid': 'original', 'type': 'assistant', 'message': {'content': [], 'stop_reason': 'end_turn'},
                }) + '\n')
                # The native CLI keeps its input and chooses when to exit after the handoff notice.
                fixture = root / 'claude'
                fixture.write_text(f'''#!{sys.executable}
import json, os, pathlib, signal, sys, time
root = pathlib.Path({directory!r})
with (root / "calls").open("a") as out:
    out.write(json.dumps([sys.argv[1:], os.environ.get("CLAUDE_CODE_RESUME_INTERRUPTED_TURN")]) + "\\n")
if "--resume" in sys.argv:
    if "--" in sys.argv:
        with (root / "config/projects/project" / ({sid!r} + ".jsonl")).open("a") as transcript:
            transcript.write(json.dumps({{"type": "user", "message": {{"content": sys.argv[-1]}}}}) + "\\n")
    sys.exit(0)
def exit_on_switch(*_):
    if {final_reason!r}:
        with (root / "config/projects/project" / ({sid!r} + ".jsonl")).open("a") as transcript:
            transcript.write(json.dumps({{"uuid":"final", "type":"assistant",
                                         "message":{{"stop_reason":{final_reason!r}}}}}) + "\\n")
    sys.exit(0)
signal.signal(signal.SIGTERM, lambda *_: (root / 'unexpected-termination').touch())
session = {{"pid": os.getpid(), "kind": "interactive", "sessionId": {sid!r}, "status": {status!r},
           "startedAt": time.time()*1000, "cwd": {directory!r}}}
(root / "config/sessions" / (str(os.getpid()) + ".json")).write_text(json.dumps(session))
for _ in range(400):
    if (root / 'voluntary-exit').exists():
        exit_on_switch()
    time.sleep(.01)
sys.exit(77)
''')
                fixture.chmod(0o700)

                def switch():
                    for _ in range(200):
                        if list((home / 'sessions').glob('*.json')):
                            state.save('session_refresh', {'since': time.time()})
                            return
                        time.sleep(.015)

                change = threading.Thread(target=switch)
                change.start()
                try:
                    def on_notice(message):
                        if '/exit' in message:
                            (root / 'voluntary-exit').touch()
                    with patch('managed_session.background_work', return_value=background), \
                         patch('managed_session.process_children', return_value={}), \
                         patch('managed_session.notice', side_effect=on_notice):
                        rc = run_session(str(fixture), ['--effort', 'max', 'old task'],
                                         ['--effort', 'max'], state, home, interval=.03)
                finally:
                    change.join(4)
                self.assertEqual(rc, 0)
                self.assertFalse((root / 'unexpected-termination').exists())
                first, resumed = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
                self.assertEqual(first[0], ['--effort', 'max', 'old task'])
                self.assertEqual(resumed[0], ['--effort', 'max', '--resume', sid]
                                 + (['--', recovery_message(sid, state.load('session_refresh')['since'])] if recovery else []))
                self.assertEqual(resumed[1], '0')
                if recovery:
                    self.assertEqual(state.load('resume_prompts')['sessions'], [sid])
