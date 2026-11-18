from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from policy import UsageUnavailable
from profiles import Profile


class ProfileTest(unittest.TestCase):
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
