from pathlib import Path
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import stat
import threading
import tempfile
import unittest
from unittest.mock import Mock, patch

from policy import UsageUnavailable
from profiles import DEFAULT_SETTINGS, Profile, load_settings, registered_accounts
from runtime import Runtime
from switchcore.policy import PriorityPolicy


def login(home, workspace):
    home.mkdir(exist_ok=True)
    claims = {'exp': 1e12, 'https://api.openai.com/auth': {
        'chatgpt_account_id': workspace, 'chatgpt_plan_type': 'fixture'}}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    (home / 'auth.json').write_text(json.dumps({'tokens': {'access_token': f'x.{payload}.x'}}))


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / 'account-switcher'
        self.folder.mkdir()
        self.path = self.folder / 'config.json'

    def write(self, value):
        self.path.write_text(json.dumps(value))

    def test_without_a_file_the_built_in_settings_apply(self):
        """설정 파일이 없으면 지금 값(회사와 개인 홈, 90%, 지금 Codex 규칙)으로 돈다."""
        settings = load_settings(self.path)

        self.assertIs(settings, DEFAULT_SETTINGS)

    def test_a_file_sets_the_homes_threshold_and_rule(self):
        """설정 파일은 홈 바로 아래 폴더 이름, 기준, repo 안 규칙 이름을 받고 빠진 값은 기본값이다."""
        self.write({'homes': {'company': '.codex-work'}, 'threshold': 95, 'policy': 'priority'})

        settings = load_settings(self.path)

        self.assertEqual(settings.homes, {'company': Path.home() / '.codex-work',
                                          'personal': Path.home() / '.codex'})
        self.assertEqual((settings.threshold, type(settings.policy), settings.policy.threshold),
                         (95, PriorityPolicy, 95))

    def test_the_folder_is_closed_to_others_before_it_is_read(self):
        """다른 사용자도 열 수 있는 폴더(0755)는 읽기 전에 0700으로 닫는다."""
        self.folder.chmod(0o755)
        self.write({'threshold': 80})

        settings = load_settings(self.path)

        self.assertEqual((stat.S_IMODE(self.folder.stat().st_mode), settings.threshold), (0o700, 80))

    def test_a_linked_or_foreign_file_is_refused(self):
        """설정은 token을 읽을 홈을 고르므로 링크이거나 내 소유가 아니면 읽지 않는다."""
        real = self.folder / 'real.json'
        real.write_text('{}')
        self.path.symlink_to(real)
        with self.assertRaisesRegex(UsageUnavailable, 'not a link'):
            load_settings(self.path)
        self.path.unlink()
        self.write({})
        with patch('profiles.os.getuid', return_value=os.getuid() + 1), \
                self.assertRaisesRegex(UsageUnavailable, 'your own file'):
            load_settings(self.path)

    def test_an_invalid_value_names_what_to_fix(self):
        """잘못 쓴 값은 시작을 막고 어느 값을 어떻게 고칠지 알려 준다."""
        cases = (({'theshold': 95}, 'keys: homes, threshold, policy'),
                 ({'homes': {'company': 'work/codex'}}, 'homes.company=work/codex'),
                 ({'homes': {'company': '.codex-auto'}}, 'homes.company=.codex-auto'),
                 ({'homes': {'company': '.codex'}}, 'company and personal must differ'),
                 ({'threshold': True}, 'threshold (a number from 1 to 100)'),
                 ({'policy': 'rules.py:Mine'}, 'policy=rules.py:Mine'))
        for value, message in cases:
            with self.subTest(value=value):
                self.write(value)
                with self.assertRaisesRegex(UsageUnavailable, re.escape(message)):
                    load_settings(self.path)

    def test_a_home_holding_another_workspace_waits_for_registration(self):
        """홈을 다른 워크스페이스 폴더로 바꾸면 그 이름을 다시 등록할 때까지 그 계정 token을 쓰지 않는다."""
        old, new = self.root / 'old', self.root / 'new'
        login(old, 'first')
        login(new, 'second')
        registered_accounts({'company': old}, self.root)

        with self.assertRaisesRegex(UsageUnavailable, 'company workspace changed'):
            Profile('company', new, bindings_dir=self.root).tokens()
        registered_accounts({'company': new}, self.root, registration=('company', 'second'))
        tokens = Profile('company', new, bindings_dir=self.root).tokens()

        self.assertEqual(tokens['chatgptAccountId'], 'second')


class ProfileTest(unittest.TestCase):
    def test_wrong_shaped_login_only_disables_that_profile(self):
        """null 또는 다른 형태의 로그인도 보조 계정 오류로 격리한다."""
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            for content in ('null', '{"tokens": null}', '{"tokens":{"access_token":null}}'):
                with self.subTest(content=content):
                    (home / 'auth.json').write_text(content)
                    profile = Profile('personal', home)
                    self.assertIsNone(profile.account_id)
                    with self.assertRaises(UsageUnavailable):
                        profile.tokens()

    def test_duplicate_workspaces_cannot_be_automatic_candidates(self):
        """두 프로필이 같은 워크스페이스이면 현재 연결을 유지하고 후보를 만들지 않는다."""
        from supervisor import collect
        profiles = {name: Mock(account_id='same') for name in ('company', 'personal')}
        for profile in profiles.values():
            profile.usage.return_value = {'used_percent': 10}
        snapshots, errors = collect(profiles)
        self.assertEqual(snapshots, {})
        self.assertEqual(set(errors.values()), {'DuplicateWorkspace'})

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
        def refreshed(method, *args, **kwargs):
            if method == 'account/read':
                credential['expires'] = 9_999_999_999
                return {}
            return {'accountId': 'company', 'rateLimits': {'primary': {'usedPercent': 10}}}
        healthy.request.side_effect = refreshed
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
