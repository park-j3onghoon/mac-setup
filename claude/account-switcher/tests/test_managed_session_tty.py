"""A real terminal keeps its native editor and chooses the handoff boundary."""

import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest

from storage import State


SESSION_ID = 'a828b6ac-3183-4bc2-a662-ab93319eb565'
FIXTURE = r"""
import json, os, pathlib, signal, sys, termios, time, tty
root = pathlib.Path(os.environ['CLAUDE_TEST_ROOT'])
sid = os.environ['CLAUDE_TEST_SESSION']
if '--resume' in sys.argv:
    (root / 'resumed').write_text(json.dumps(sys.argv[1:]))
    sys.exit(0)
def timed_out(*args):
    os._exit(70)
signal.signal(signal.SIGALRM, timed_out)
signal.alarm(12)
signal.signal(signal.SIGTERM, lambda *_: (root / 'unexpected-sigterm').touch())
saved = termios.tcgetattr(0)
tty.setraw(0)
registry = dict(pid=os.getpid(), kind='interactive', status='idle', sessionId=sid,
                startedAt=time.time()*1000, cwd=str(root))
(root / 'config' / 'sessions' / f'{os.getpid()}.json').write_text(json.dumps(registry))
os.write(1, b'NATIVE READY')
draft = bytearray()
try:
    while True:
        key = os.read(0, 1)
        if key == b'\r':
            if draft == b'/exit':
                break
            (root / 'submitted').write_bytes(draft)
            draft.clear()
        else:
            draft.extend(key)
            if draft.endswith(b'citation'):
                os.write(1, b'DRAFT IN EDITOR')
finally:
    termios.tcsetattr(0, termios.TCSANOW, saved)
"""


def wait_output(fd, part):
    output = b''
    deadline = time.monotonic() + 6
    while part not in output:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise AssertionError(f'missing terminal output {part!r}: {output!r}')
        output += os.read(fd, 4096)


class TerminalHandoffTests(unittest.TestCase):
    def test_editor_draft_survives_until_user_submits_and_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'config'
            (home / 'sessions').mkdir(parents=True)
            project = home / 'projects' / 'one'
            project.mkdir(parents=True)
            (project / (SESSION_ID + '.jsonl')).write_text(json.dumps({
                'uuid': 'prior', 'type': 'assistant', 'message': {'stop_reason': 'end_turn'}}))
            fixture = root / 'claude'
            fixture.write_text(f'#!{sys.executable}\n' + FIXTURE)
            fixture.chmod(0o700)
            state = State(root / 'state')
            driver = ('from pathlib import Path; import sys; import managed_session as m; '
                      'p=Path(sys.argv[1]); m.process_children=lambda _:{}; '
                      'sys.exit(m.run_session(str(p / "claude"), [], [], m.State(p / "state"), p / "config", .02))')
            master, slave = pty.openpty()
            self.addCleanup(os.close, master)
            try:
                process = subprocess.Popen([sys.executable, '-B', '-c', driver, str(root)],
                    cwd=Path(__file__).resolve().parents[1], stdin=slave, stdout=slave, stderr=slave,
                    env=dict(os.environ, CLAUDE_TEST_ROOT=directory, CLAUDE_TEST_SESSION=SESSION_ID))
            finally:
                os.close(slave)
            try:
                wait_output(master, b'NATIVE READY')
                os.write(master, b'unsent citation')
                wait_output(master, b'DRAFT IN EDITOR')
                state.save('session_refresh', {'since': time.time()})
                wait_output(master, b'/exit')
                self.assertIsNone(process.poll())
                self.assertFalse((root / 'submitted').exists())
                self.assertFalse((root / 'resumed').exists())
                os.write(master, b'\r/exit\r')
                self.assertEqual(process.wait(timeout=6), 0)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
            self.assertFalse((root / 'unexpected-sigterm').exists())
            self.assertEqual((root / 'submitted').read_text(), 'unsent citation')
            self.assertEqual(json.loads((root / 'resumed').read_text()), ['--resume', SESSION_ID])
