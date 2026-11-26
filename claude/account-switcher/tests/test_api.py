from datetime import datetime, timezone
from io import BytesIO
import tempfile
import subprocess
import sys
import unittest
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch

from api import Anthropic, ApiError, NoRedirect, parse_usage
from switchcore.policy import PriorityPolicy
from helpers import NOW
from storage import SwitcherError, directory_lock
from pathlib import Path


class ApiTests(unittest.TestCase):
    def test_weekly_breakdown_is_not_a_quota_window(self):
        """실제 응답의 주간 내역 필드를 모델별 한도로 오인하지 않는다."""
        # given
        data = {'five_hour': {'utilization': 12, 'resets_at': NOW + 300},
                'seven_day': {'utilization': 30, 'resets_at': NOW + 86400},
                'seven_day_breakdown': {'as_of': '2033-05-18',
                                        'window_started_at': '2033-05-11', 'rows': []}}
        # when
        reading = parse_usage(data, NOW)
        # then
        self.assertTrue(PriorityPolicy(95, 60).available(reading, NOW))
        self.assertEqual(len(reading.windows), 2)

    def test_refresh_failure_only_retains_a_recognized_oauth_error(self):
        api = Anthropic()
        for code, expected in [('invalid_grant', 'invalid_grant'), ('unknown-private-value', None)]:
            with self.subTest(code=code):
                error = HTTPError('https://platform.claude.com/v1/oauth/token', 400, '', {},
                                  BytesIO(('{"error":"' + code + '"}').encode()))
                with patch.object(api.opener, 'open', side_effect=error), self.assertRaises(ApiError) as ctx:
                    api.refresh({'refreshToken': 'fixture'}, NOW)
                self.assertEqual(ctx.exception.oauth_error, expected)
                self.assertNotIn(code, str(ctx.exception))

    def test_server_lock_blocks_an_account_with_low_usage(self):
        """사용률이 낮아도 서버가 사용을 막은 계정은 선택하지 않는다."""
        # given
        data = {'five_hour': {'utilization': 0, 'resets_at': NOW + 300,
                              'locked_reason': 'quota_locked'}}
        # when
        reading = parse_usage(data, NOW)
        # then
        self.assertFalse(PriorityPolicy(95, 60).available(reading, NOW))

    def test_parses_server_reset_time(self):
        """초기화 시각을 로컬 추측이 아닌 서버 값으로 보존한다."""
        # given
        data = {'five_hour': {'utilization': 95, 'resets_at': '2033-05-18T03:38:20Z'}}
        expected = datetime(2033, 5, 18, 3, 38, 20, tzinfo=timezone.utc).timestamp()
        # when
        reading = parse_usage(data, NOW)
        # then
        self.assertEqual(reading.windows[0].resets_at, expected)

    def test_missing_all_windows_is_not_unlimited(self):
        """사용량 필드가 사라지면 무제한 계정으로 해석하지 않는다."""
        # given
        data = {'five_hour': None, 'seven_day': None}
        # when & then
        with self.assertRaises(ApiError):
            parse_usage(data, NOW)

    def test_scoped_weekly_limit_prevents_selection(self):
        """모델별 주간 한도가 소진된 계정은 복귀 대상으로 삼지 않는다."""
        # given
        data = {'five_hour': {'utilization': 0}, 'limits': [
            {'kind': 'weekly_scoped', 'scope': {'model': {'display_name': 'Opus'}},
             'percent': 100, 'resets_at': NOW + 86400}]}
        # when
        reading = parse_usage(data, NOW)
        # then
        self.assertFalse(PriorityPolicy(95, 60).available(reading, NOW))

    def test_null_quota_remains_unknown(self):
        """서버의 null 사용률을 0%로 바꾸지 않는다."""
        # given
        data = {'five_hour': {'utilization': None}}
        # when
        reading = parse_usage(data, NOW)
        # then
        self.assertFalse(PriorityPolicy(95, 60).available(reading, NOW))

    def test_redirect_does_not_forward_authorization(self):
        """인증 요청이 다른 주소로 리다이렉트되면 따라가지 않는다."""
        # given
        request = Request('https://api.anthropic.com/api/oauth/usage',
                          headers={'Authorization': 'Bearer test-secret'})
        # when
        redirected = NoRedirect().redirect_request(request, None, 302, '', {},
                                                    'https://other.example/steal')
        # then
        self.assertIsNone(redirected)

    def test_rejects_non_anthropic_origin(self):
        """허용된 공급자 주소 밖으로 인증을 보내지 않는다."""
        # given
        api = Anthropic()
        # when & then
        with self.assertRaises(SwitcherError):
            api.request('https://api.anthropic.com.other.example/', token='test-secret')

    def test_existing_claude_lock_is_never_stolen(self):
        """Claude가 보유한 잠금을 오래됐다는 이유로 빼앗지 않는다."""
        # given
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '.oauth_refresh.lock'
            path.mkdir()
            # when & then
            with self.assertRaises(SwitcherError):
                with directory_lock(path, timeout=0):
                    self.fail('must not enter')
            self.assertTrue(path.is_dir())

    def test_dead_switcher_lock_is_recovered_but_replacement_claude_lock_is_kept(self):
        """죽은 switcher의 잠금만 회수하며 같은 경로에 새로 생긴 Claude 잠금은 지킨다."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '.oauth_refresh.lock'
            code = ('from storage import directory_lock; from pathlib import Path; import os, sys\n'
                    'with directory_lock(Path(sys.argv[1])): os._exit(0)\n')
            subprocess.run([sys.executable, '-B', '-c', code, str(path)], check=True)
            self.assertTrue(path.is_dir())

            with directory_lock(path, timeout=0):
                self.assertTrue(path.is_dir())
                with self.assertRaises(SwitcherError):
                    with directory_lock(path, timeout=0):
                        self.fail('must preserve the live switcher lock')
            self.assertFalse(path.exists())

            subprocess.run([sys.executable, '-B', '-c', code, str(path)], check=True)
            path.rename(path.with_name('old-switcher-lock'))
            path.mkdir()
            with self.assertRaises(SwitcherError):
                with directory_lock(path, timeout=0):
                    self.fail('must preserve the replacement lock')
            self.assertTrue(path.is_dir())

    def test_owner_record_failure_releases_the_new_directory_lock(self):
        """소유 기록 쓰기에 실패해도 방금 만든 잠금을 남기지 않는다."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / '.oauth_refresh.lock'
            with patch('storage.os.write', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    with directory_lock(path, timeout=0):
                        self.fail('recording failed')
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
