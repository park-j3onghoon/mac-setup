"""cmux, the default terminal: its surface is the pane (cmux 0.64.22)."""

import json
from pathlib import Path
import subprocess

from .terminal import TerminalUnavailable


CMUX_PATHS = ('/opt/homebrew/bin/cmux', '/Applications/cmux.app/Contents/Resources/bin/cmux')


def find_cmux():
    return next((path for path in CMUX_PATHS if Path(path).is_file()), None)


class CmuxTerminal:
    def __init__(self, *, runner=subprocess.run, path=None):
        self.runner, self.path = runner, path or find_cmux()

    def pane_in(self, environment):
        return environment.get('CMUX_SURFACE_ID') or None

    def read_screen(self, pane, lines):
        result = self._run('read-screen', '--surface', pane, '--lines', str(lines))
        if result.returncode:
            raise TerminalUnavailable('Could not read the terminal screen')
        return result.stdout

    def submit(self, pane, text):
        # cmux dispatches the paste and its submit key together on its main actor. It has no
        # empty-input precondition, so only text typed after the caller's last look can mix in.
        result = self._run('rpc', 'terminal.paste', json.dumps({
            'surface_id': pane, 'text': text, 'submit_key': 'enter'}))
        if result.returncode:
            raise OSError(f'cmux rpc failed: status={result.returncode}')
        if json.loads(result.stdout).get('submitted') is not True:
            raise OSError('cmux accepted the paste without confirming submission')

    def _run(self, *args):
        return self.runner([self.path, *args], capture_output=True, text=True, timeout=10, check=False)
