import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from managed_session import claim_continuation, run_session, resume_options, switch_target
from refresh import CONTINUE_PROMPT
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
            with patch('managed_session.process_children', return_value={}):
                for entry, need in [(end, False), (dict(end, isApiErrorMessage=True), True),
                                    ({'type': 'assistant', 'message': {'stop_reason':'tool_use'}}, True),
                                    ({'type': 'user', 'message': {'content':'unfinished'}}, True)]:
                    log.write_text(json.dumps(entry))
                    self.assertEqual(switch_target(4242, 9, 11, home)[2], need)
                self.assertIsNone(switch_target(4242, 10.1, 11, home))
                log.write_text('{"type":"system"}')
                self.assertIsNone(switch_target(4242, 9, 11, home))

    def test_only_unfinished_work_gets_the_recovery_prompt(self):
        cases = [('busy', None, True), ('idle', None, False), ('busy', 'end_turn', False),
                 ('idle', 'tool_use', True)]
        for status, final_reason, recovery in cases:
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
                # A real subprocess owns the registry entry, receives SIGTERM and exits before resume.
                fixture = root / 'claude'
                fixture.write_text(f'''#!{sys.executable}
import json, os, pathlib, signal, sys, time
root = pathlib.Path({directory!r})
with (root / "calls").open("a") as out:
    out.write(json.dumps([sys.argv[1:], os.environ.get("CLAUDE_CODE_RESUME_INTERRUPTED_TURN")]) + "\\n")
if "--resume" in sys.argv:
    sys.exit(0)
def exit_on_switch(*_):
    if {final_reason!r}:
        with (root / "config/projects/project" / ({sid!r} + ".jsonl")).open("a") as transcript:
            transcript.write(json.dumps({{"uuid":"final", "type":"assistant",
                                         "message":{{"stop_reason":{final_reason!r}}}}}) + "\\n")
    sys.exit(0)
signal.signal(signal.SIGTERM, exit_on_switch)
session = {{"pid": os.getpid(), "kind": "interactive", "sessionId": {sid!r}, "status": {status!r},
           "startedAt": time.time()*1000, "cwd": {directory!r}}}
(root / "config/sessions" / (str(os.getpid()) + ".json")).write_text(json.dumps(session))
time.sleep(8)
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
                    with patch('managed_session.background_work', return_value=False), \
                         patch('managed_session.process_children', return_value={}):
                        rc = run_session(str(fixture), ['--effort', 'max', 'old task'],
                                         ['--effort', 'max'], state, home, interval=.03)
                finally:
                    change.join(4)
                self.assertEqual(rc, 0)
                first, resumed = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
                self.assertEqual(first[0], ['--effort', 'max', 'old task'])
                self.assertEqual(resumed[0], ['--effort', 'max', '--resume', sid]
                                 + (['--', CONTINUE_PROMPT] if recovery else []))
                self.assertEqual(resumed[1], '0')
