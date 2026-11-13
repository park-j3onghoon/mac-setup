from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from helpers import make_app
from storage import SwitcherError
from switcher import main


class EnrollmentTests(unittest.TestCase):
    def test_wrong_browser_account_is_reported_before_reading_new_secret(self):
        """브라우저가 기존 계정으로 인증하면 대상 계정으로 잘못 등록하지 않는다."""
        # given
        with tempfile.TemporaryDirectory() as temporary:
            app = make_app(temporary)
            app.state.save('config', app.config)
            result = subprocess.CompletedProcess([], 0)
            # when & then
            with patch('switcher.build', return_value=app), \
                    patch('switcher.subprocess.run', return_value=result):
                with self.assertRaisesRegex(SwitcherError, 'different account'):
                    main(['--state-dir', str(app.state.root), 'enroll', 'fallback'])
            self.assertEqual(app.vault.active_writes, 0)


if __name__ == '__main__':
    unittest.main()
