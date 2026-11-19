"""Opt-in cross-process check with a disposable, non-secret Keychain item."""

import getpass
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
import uuid

from macos import Keychain


@unittest.skipUnless(sys.platform == 'darwin' and
                     os.environ.get('CLAUDE_SWITCHER_TEST_KEYCHAIN') == '1',
                     'Opt-in macOS Keychain interoperability test')
class NativeKeychainTests(unittest.TestCase):
    def test_native_cli_reads_after_switcher_updates_existing_item(self):
        """전환기가 기존 항목을 갱신한 뒤 별도 Apple CLI 프로세스도 같은 값을 읽는다."""
        # given
        service = 'local.mac-setup.claude-account-switcher.test.' + uuid.uuid4().hex
        account = getpass.getuser()
        before = {'dummy': 'before'}
        after = {'dummy': 'after', 'unicode': '검증', 'large': 'x' * 8192}
        python_app = Path(sys.prefix) / 'Resources/Python.app'
        if not python_app.exists():
            python_app = Path(sys.executable).resolve()
        python_app = python_app.resolve()
        args = ['add-generic-password', '-U', '-a', account, '-s', service,
                '-T', '/usr/bin/security', '-T', str(python_app),
                '-w', json.dumps(before)]
        command = ' '.join(shlex.quote(a) for a in args) + '\n'
        created = subprocess.run(['/usr/bin/security', '-i'], input=command,
                                 capture_output=True, text=True, timeout=5)
        self.assertEqual(created.returncode, 0)
        try:
            # when
            keychain = Keychain()
            keychain.replace_existing(service, account, after)
            native = subprocess.run(['/usr/bin/security', 'find-generic-password',
                                     '-a', account, '-s', service, '-w'],
                                    capture_output=True, text=True, timeout=5)
            # then
            self.assertEqual(native.returncode, 0)
            self.assertEqual(json.loads(native.stdout), after)
        finally:
            subprocess.run(['/usr/bin/security', 'delete-generic-password',
                            '-a', account, '-s', service], capture_output=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
