import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from helpers import NOW, make_app
from storage import SwitcherError, read_json


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = make_app(self.directory.name)

    def test_dry_run_does_not_write_live_credentials(self):
        """사전 확인은 전환을 제안해도 현재 인증을 변경하지 않는다."""
        # given
        app = self.app
        # when
        report = app.tick(now=NOW)
        # then
        self.assertEqual(report['target'], 'work@example.com')
        self.assertEqual(app.vault.active_writes, 0)

    def test_switch_reuses_the_verified_target_usage_without_duplicate_api_calls(self):
        app = self.app
        app.api.usage = Mock(wraps=app.api.usage)
        app.tick(apply=True, now=NOW)
        self.assertEqual(app.api.usage.call_count, 2)

    def test_changed_target_token_rejects_the_previous_usage_reading(self):
        app = self.app
        original = app.api.usage

        def change_after_read(oauth, now):
            reading = original(oauth, now)
            if oauth['accessToken'] == 'token-work':
                updated = app.vault.read('work@example.com')
                updated['oauth']['accessToken'] = 'token-work-newer'
                app.vault.write('work@example.com', updated)
            return reading

        app.api.usage = change_after_read
        with self.assertRaises(SwitcherError):
            app.tick(apply=True, now=NOW)
        self.assertEqual(app.vault.active_writes, 0)

    def test_verified_token_identity_is_cached_until_token_or_account_changes(self):
        app = self.app
        app.api.profile = Mock(wraps=app.api.profile)
        b = app.vault.read('personal@example.com')
        app.verify_identity(b)
        app.verify_identity(b)
        self.assertEqual(app.api.profile.call_count, 1)
        b['oauth']['accessToken'] += '-renewed'
        app.verify_identity(b)
        self.assertEqual(app.api.profile.call_count, 2)

    def test_switch_preserves_mcp_credentials(self):
        """전환 시 계정 OAuth만 바꾸고 MCP 인증은 유지한다."""
        # given
        app = self.app
        # when
        report = app.tick(apply=True, now=NOW)
        # then
        self.assertTrue(report['switched'])
        self.assertEqual(app.vault.active['mcpOAuth'], {'keep': 'independent-connector-secret'})

    def test_switch_preserves_unrelated_global_config(self):
        """계정 메타데이터를 교체해도 기존 MCP 설정은 유지한다."""
        # given
        app = self.app
        # when
        app.tick(apply=True, now=NOW)
        # then
        self.assertEqual(read_json(app.live.config)['mcpServers'],
                         {'existing': {'command': 'keep-me'}})

    def test_switch_saves_latest_outgoing_token(self):
        """처음 등록한 값이 아닌 현재 Claude가 갱신한 토큰을 보관한다."""
        # given
        app = self.app
        app.vault.active['claudeAiOauth']['refreshToken'] = 'latest-native-refresh'
        # when
        app.tick(apply=True, now=NOW)
        # then
        self.assertEqual(app.vault.read('personal@example.com')['oauth']['refreshToken'],
                         'latest-native-refresh')

    def test_disk_failure_restores_original_login(self):
        """인증 교체 뒤 설정 저장이 실패하면 원래 계정으로 복구한다."""
        # given
        app = self.app
        app.live.fail_next_config_write = True
        # when & then
        with self.assertRaises(SwitcherError):
            app.tick(apply=True, now=NOW)
        self.assertEqual(app.vault.active['claudeAiOauth']['accessToken'], 'token-personal')
        self.assertEqual(read_json(app.live.config)['oauthAccount']['emailAddress'],
                         'personal@example.com')

    def test_process_death_is_recovered_from_keychain_journal(self):
        """프로세스가 인증 쓰기 직후 죽어도 다음 실행이 전환을 마무리한다."""
        # given
        app = self.app
        app.vault.crash_after_write = True
        # when
        with self.assertRaises(KeyboardInterrupt):
            app.tick(apply=True, now=NOW)
        app.recover()
        # then
        self.assertEqual(read_json(app.live.config)['oauthAccount']['emailAddress'],
                         'work@example.com')
        self.assertIsNone(app.vault.read('__transaction__'))
        self.assertEqual(app.state.load('runtime')['active'], 'work@example.com')

    def test_recovery_does_not_overwrite_a_newer_login(self):
        """중단 이후 다른 로그인이 생겼으면 오래된 복구 기록으로 덮어쓰지 않는다."""
        # given
        app = self.app
        app.vault.crash_after_write = True
        with self.assertRaises(KeyboardInterrupt):
            app.tick(apply=True, now=NOW)
        app.vault.active['claudeAiOauth']['accessToken'] = 'new-external-login'
        # when & then
        with self.assertRaises(SwitcherError):
            app.recover()
        self.assertEqual(app.vault.active['claudeAiOauth']['accessToken'], 'new-external-login')

    def test_target_ownership_mismatch_prevents_switch(self):
        """저장된 인증의 실제 소유자가 다르면 교체하지 않는다."""
        # given
        app = self.app
        app.api.profile_overrides['token-work'] = {
            'email': 'other@example.com', 'uuid': 'other'}
        # when & then
        with self.assertRaises(SwitcherError):
            app.tick(apply=True, now=NOW)
        self.assertEqual(app.vault.active_writes, 0)

    def test_native_refresh_during_preflight_prevents_overwrite(self):
        """사용량 조회 중 Claude가 새 토큰을 쓰면 이전 값으로 덮어쓰지 않는다."""
        # given
        app = self.app
        def renewed_login():
            app.vault.active['claudeAiOauth']['accessToken'] = 'new-native-generation'
        app.api.before_usage = renewed_login
        # when & then
        with self.assertRaises(SwitcherError):
            app.tick(apply=True, now=NOW)
        self.assertEqual(app.vault.active['claudeAiOauth']['accessToken'],
                         'new-native-generation')
        self.assertEqual(app.vault.active_writes, 0)

    def test_expired_inactive_successor_survives_usage_failure(self):
        """토큰 갱신 뒤 사용량 조회가 실패해도 갱신된 인증을 잃지 않는다."""
        # given
        app = self.app
        saved = app.vault.read('work@example.com')
        saved['oauth']['expiresAt'] = (NOW - 1) * 1000
        app.vault.write('work@example.com', saved)
        app.api.failed_tokens.add('token-work-new')
        # when
        report = app.tick(apply=True, now=NOW)
        # then
        self.assertFalse(report['switched'])
        self.assertEqual(app.vault.read('work@example.com')['oauth']['refreshToken'],
                         'rotated-refresh-token')

    def test_unenrolled_account_blocks_activation(self):
        """두 계정을 등록하기 전에는 자동 교체를 허용하지 않는다."""
        # given
        app = self.app
        app.state.save('roster', {})
        # when & then
        with self.assertRaises(SwitcherError):
            app.tick(apply=True, now=NOW)
        self.assertEqual(app.vault.active_writes, 0)

    def test_keychain_secrets_never_reach_state_files(self):
        """사용량과 복귀 시각 파일에 토큰이나 MCP 비밀 값이 남지 않는다."""
        # given
        app = self.app
        # when
        app.tick(apply=True, now=NOW)
        contents = ''.join(p.read_text() for p in app.state.root.glob('*.json'))
        # then
        self.assertNotIn('token-personal', contents)
        self.assertNotIn('token-work', contents)
        self.assertNotIn('independent-connector-secret', contents)

    def test_primary_returns_after_settling(self):
        """캐시 안정화 뒤 개인 계정이 회복되면 회사 잔량과 무관하게 복귀한다."""
        # given
        app = self.app
        app.tick(apply=True, now=NOW)
        app.api.percent['token-personal'] = 0
        # when
        report = app.tick(apply=True, now=NOW + 46)
        # then
        self.assertTrue(report['switched'])
        self.assertEqual(read_json(app.live.config)['oauthAccount']['emailAddress'],
                         'personal@example.com')

    def test_does_not_switch_again_during_cache_settling(self):
        """직전 계정의 캐시가 남아 있는 동안 재전환하지 않는다."""
        # given
        app = self.app
        app.tick(apply=True, now=NOW)
        app.api.percent['token-personal'] = 0
        # when
        report = app.tick(apply=True, now=NOW + 1)
        # then
        self.assertFalse(report['switched'])
        self.assertEqual(report['reason'], 'waiting_for_credential_cache')

    def test_reset_timestamp_controls_next_wakeup(self):
        """평소 점검 주기보다 초기화 시각이 빠르면 그 직후에 깨어난다."""
        # given
        app = self.app
        app.state.save('runtime', {'usage': {'personal@example.com': {
            'windows': [{'resets_at': NOW + 10}]}}})
        # when
        delay = app.next_delay(NOW)
        # then
        self.assertEqual(delay, 12)

    def test_poll_interval_uses_the_active_account_usage(self):
        """다음 조회 시각은 지금 쓰는 계정의 사용률로 정한다. 쓰지 않는 계정이 기준에 가까워도 앞당기지 않는다."""
        # given
        app = self.app
        later = NOW + 86400
        app.state.save('runtime', {'active': 'personal@example.com', 'usage': {
            'personal@example.com': {'windows': [{'percent': 20, 'resets_at': later}]},
            'work@example.com': {'windows': [{'percent': 88, 'resets_at': later}]}}})
        # when
        delay = app.next_delay(NOW)
        # then
        self.assertEqual(delay, 540)

    def test_metadata_rate_limit_is_backed_off(self):
        """조회 서버의 제한 응답은 계정 한도 소진으로 오해하지 않는다."""
        # given
        app = self.app
        app.api.failed_tokens.update(('token-personal', 'token-work'))
        # when
        report = app.tick(apply=True, now=NOW)
        # then
        self.assertFalse(report['switched'])
        self.assertGreaterEqual(app.next_delay(NOW), 300)


if __name__ == '__main__':
    unittest.main()
