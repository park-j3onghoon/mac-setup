from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch

from policy import UsageUnavailable
from profiles import Profile
from runtime import Runtime


class ProfileTest(unittest.TestCase):
    def test_missing_fallback_preserves_current_account_and_can_recover(self):
        """보조 로그인 파일 오류는 정상 서버 관찰을 막지 않고 파일 복구 후 다시 조회한다."""
        restored = [False]

        def credentials(home):
            if home.name == 'personal' and not restored[0]:
                raise UsageUnavailable('fixture login missing')
            return {'accessToken': 'fixture', 'chatgptAccountId': home.name,
                    'chatgptPlanType': 'fixture', 'expires': 9_999_999_999}

        with patch('profiles.credentials', side_effect=credentials):
            profiles = {name: Profile(name, Path('/fixture') / name) for name in ('company', 'personal')}
            server = Runtime(profiles)
            server.client = Mock(closed=False)
            server.client.request.return_value = {'account': {'type': 'chatgpt'},
                'workspaceRouting': {'chatgptAccountId': 'company'}}
            server.observe_account()
            self.assertEqual(server.active, 'company')
            with self.assertRaises(UsageUnavailable):
                profiles['personal'].usage()

            restored[0] = True
            profiles['personal'].client = Mock(closed=False)
            profiles['personal'].client.request.return_value = {
                'accountId': 'personal', 'rateLimits': {'primary': {'usedPercent': 10}}}
            result = profiles['personal'].usage()

        self.assertEqual(result['used_percent'], 10)
        self.assertEqual(profiles['personal'].account_id, 'personal')

    def test_concurrent_forced_refreshes_share_one_successful_refresh(self):
        """같은 토큰을 갱신하려고 동시에 대기한 요청은 한 번의 성공 결과를 공유한다."""
        barrier, mutex = threading.Barrier(8), threading.Lock()
        class BatchedLock:
            def __enter__(self):
                barrier.wait(timeout=3)
                mutex.acquire()

            def __exit__(self, *args):
                mutex.release()

        credential = {'accessToken': 'old', 'chatgptAccountId': 'company',
                      'chatgptPlanType': 'fixture', 'expires': 9_999_999_999}
        with patch('profiles.credentials', side_effect=lambda _: dict(credential)):
            profile = Profile('company', Path('/unused'))
            profile.lock = BatchedLock()
            profile.client = Mock(closed=False)
            profile.client.request.side_effect = lambda *args, **kwargs: credential.update(accessToken='new')
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: profile.tokens(force=True), range(8)))

        self.assertTrue(all(result['accessToken'] == 'new' for result in results))
        profile.client.request.assert_called_once()

    def test_failed_refresh_reconnects_on_next_usage_lookup(self):
        """갱신 요청이 실패한 연결을 버리고 다음 조회에서는 새 연결로 사용량을 읽는다."""
        credential = {'accessToken': 'synthetic', 'chatgptAccountId': 'company',
                      'chatgptPlanType': 'fixture', 'expires': 0}
        broken = Mock(closed=False)
        broken.request.side_effect = UsageUnavailable('synthetic failure')
        healthy = Mock(closed=False)
        healthy.request.side_effect = [{}, {'accountId': 'company',
            'rateLimits': {'primary': {'usedPercent': 10}}}]
        with patch('profiles.credentials', side_effect=lambda _: dict(credential)), \
                patch('profiles.Rpc', return_value=healthy):
            profile = Profile('company', Path('/unused'))
            profile.client = broken

            with self.assertRaises(UsageUnavailable):
                profile.usage()
            result = profile.usage()

        self.assertEqual(result['used_percent'], 10)
        broken.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
