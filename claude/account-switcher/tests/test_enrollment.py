import contextlib
import io
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from helpers import NOW, make_app
from refresh import switch_pending
from storage import SwitcherError
from switcher import main


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app = make_app(temporary.name)
        self.app.state.save('config', self.app.config)

    def browser_signs_in(self, email):
        """공식 로그인이 브라우저에서 email 계정으로 끝나 live 로그인이 그 계정으로 바뀐 것처럼 꾸민다."""
        def official_login(*_args, **_kwargs):
            signed_in = self.app.vault.read(email)
            self.app.vault.active['claudeAiOauth'] = signed_in['oauth']
            self.app.live.write_account(signed_in['account'])
            return subprocess.CompletedProcess([], 0)
        return official_login

    def enroll(self, role, official_login):
        with patch('switcher.build', return_value=self.app), \
                patch('switcher.subprocess.run', side_effect=official_login), \
                patch('switcher.time.time', return_value=NOW), \
                contextlib.redirect_stdout(io.StringIO()):
            main(['--state-dir', str(self.app.state.root), 'enroll', role])

    def test_wrong_browser_account_is_reported_before_reading_new_secret(self):
        """브라우저가 기존 계정으로 인증하면 대상 계정으로 잘못 등록하지 않는다."""
        # when & then
        with self.assertRaisesRegex(SwitcherError, 'different account'):
            self.enroll('fallback', self.browser_signs_in('personal@example.com'))
        self.assertEqual(self.app.vault.active_writes, 0)

    def test_enrolling_another_account_restarts_open_sessions(self):
        """열린 세션은 나가는 계정의 로그인을 메모리에 들고 있으므로, 다른 계정을 등록하면 계정 전환처럼 재시작할 시각을 남긴다."""
        # when
        self.enroll('fallback', self.browser_signs_in('work@example.com'))
        # then
        self.assertEqual(switch_pending(self.app.state, NOW + 60), NOW)

    def test_reenrolling_the_live_account_keeps_open_sessions(self):
        """지금 쓰는 계정을 다시 등록하면 열린 세션의 계정이 그대로라 재시작할 시각을 남기지 않는다."""
        # when
        self.enroll('primary', self.browser_signs_in('personal@example.com'))
        # then
        self.assertIsNone(switch_pending(self.app.state, NOW + 60))

    def test_capture_does_not_save_a_refresh_token_replaced_during_verification(self):
        """소유자 확인 중 갱신 토큰만 바뀌어도 이전 인증을 등록하지 않는다."""
        original = self.app.api.profile

        def rotate(oauth):
            self.app.vault.active['claudeAiOauth']['refreshToken'] = 'latest-refresh'
            return original(oauth)

        self.app.api.profile = rotate
        with self.assertRaisesRegex(SwitcherError, 'retry capture'):
            self.app.capture('personal@example.com')
        self.app.capture('personal@example.com')
        saved = self.app.vault.read('personal@example.com')
        self.assertEqual(saved['oauth']['refreshToken'], 'latest-refresh')


if __name__ == '__main__':
    unittest.main()
