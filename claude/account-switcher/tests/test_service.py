import json
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from helpers import NOW, make_app
from storage import SwitcherError, read_json


class ServiceTests(unittest.TestCase):
    def test_sleep_during_usage_query_does_not_accept_stale_capacity(self):
        """절전 뒤에는 주기 시작 시각으로 오래된 사용량을 승인하지 않는다."""
        clock = [NOW]
        usage = self.app.api.usage

        def slow_usage(oauth, now):
            result = usage(oauth, now)
            if oauth['accessToken'] == 'token-work':
                clock[0] += 120
            return result

        self.app.api.usage = slow_usage
        with patch('service.time.time', side_effect=lambda: clock[0]):
            self.app.tick(apply=True)
        self.assertEqual(self.app.vault.active_writes, 0)

    def test_commit_rechecks_capacity_after_waiting_for_claude_lock(self):
        """정상 사용량을 읽었어도 잠금 대기 중 오래되면 인증 쓰기 전에 재검사한다."""
        clock = [NOW]
        locked = self.app.live.locked
        calls = [0]

        @contextmanager
        def delayed_lock():
            calls[0] += 1
            if calls[0] == 3:
                clock[0] += 120
            with locked():
                yield

        with patch.object(self.app.live, 'locked', delayed_lock), \
                patch('service.time.time', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(SwitcherError, 'capacity'):
                self.app.tick(apply=True)
        self.assertEqual(self.app.vault.active_writes, 0)

    def test_settle_window_starts_when_credentials_are_committed(self):
        """조회가 지연돼도 교체 후 캐시 대기 시간은 실제 교체 시각부터 보장한다."""
        clock = [NOW]
        usage = self.app.api.usage

        def slow_usage(oauth, now):
            result = usage(oauth, now)
            if oauth['accessToken'] == 'token-work':
                clock[0] += 20
            return result

        self.app.api.usage = slow_usage
        with patch('service.time.time', side_effect=lambda: clock[0]):
            self.app.tick(apply=True)
        runtime = self.app.state.load('runtime')
        self.assertEqual(runtime['switched_at'], NOW + 20)
        self.assertEqual(runtime['settle_until'], NOW + 65)

    def test_switch_metadata_failure_is_recovered_with_session_marker(self):
        """인증 교체 뒤 runtime 저장이 실패해도 다음 복구가 세션 재시작 신호까지 남긴다."""
        app = self.app
        expected = app.vault.read('personal@example.com')
        save = app.state.save

        def fail_runtime(name, value):
            if name == 'runtime':
                raise OSError('synthetic state failure')
            save(name, value)

        with patch.object(app.state, 'save', side_effect=fail_runtime):
            with self.assertRaises(OSError):
                app.switch_to(expected, 'work@example.com', NOW)
        app.recover()

        self.assertEqual(app.state.load('runtime')['active'], 'work@example.com')
        self.assertEqual(app.state.load('session_refresh')['since'], NOW)
        self.assertIsNone(app.vault.read('__transaction__'))

    def test_session_marker_failure_keeps_recoverable_switch(self):
        """재시작 신호 저장 실패 뒤에도 복구 기록이 남아 같은 전환 시각으로 재시도한다."""
        app = self.app
        save = app.state.save

        def fail_marker(name, value):
            if name == 'session_refresh':
                raise OSError('synthetic marker failure')
            save(name, value)

        with patch.object(app.state, 'save', side_effect=fail_marker):
            with self.assertRaises(OSError):
                app.switch_to(app.vault.read('personal@example.com'), 'work@example.com', NOW)
        app.recover()

        self.assertEqual(app.state.load('session_refresh')['since'], NOW)
        self.assertEqual(app.live.read()[1]['emailAddress'], 'work@example.com')
        self.assertIsNone(app.vault.read('__transaction__'))

    def test_manual_switch_does_not_wait_for_credential_cache(self):
        """수동 전환은 직전 교체의 캐시 대기 시간에도 선택한 로그인으로 바꾼다."""
        app = self.app
        app.state.save('runtime', {'active': 'personal@example.com', 'settle_until': NOW + 45})
        app.state.save('preference', {'preferred': 'work@example.com', 'requested_at': NOW,
                                      'immediate': True})

        report = app.tick(apply=True, now=NOW)

        self.assertTrue(report['switched'])
        self.assertEqual(app.state.load('runtime')['active'], 'work@example.com')
        self.assertEqual(app.live.read()[1]['emailAddress'], 'work@example.com')

    def test_manual_request_survives_a_temporary_usage_failure(self):
        """사용량 조회 실패는 즉시 전환 요청의 완료로 처리하지 않는다."""
        from api import ApiError
        app = self.app
        app.state.save('runtime', {'active': 'personal@example.com', 'settle_until': NOW + 300})
        app.state.save('preference', {'preferred': 'work@example.com', 'requested_at': NOW,
                                      'immediate': True})
        usage = app.api.usage

        def unavailable(oauth, now):
            if oauth['accessToken'] == 'token-work':
                raise ApiError('usage', 500, 0)
            return usage(oauth, now)

        app.api.usage = unavailable
        app.tick(apply=True, now=NOW)
        app.api.usage = usage
        report = app.tick(apply=True, now=NOW + 1)
        self.assertTrue(report['switched'])

    def test_dry_run_preserves_the_pending_manual_switch(self):
        """사전 확인이 수동 선택을 소비하지 않아 다음 실제 전환도 대기 없이 적용된다."""
        app = self.app
        app.state.save('runtime', {'active': 'personal@example.com', 'settle_until': NOW + 45})
        app.state.save('preference', {'preferred': 'work@example.com', 'requested_at': NOW,
                                      'immediate': True})

        app.tick(apply=False, now=NOW)
        report = app.tick(apply=True, now=NOW + 1)

        self.assertTrue(report['switched'])
        self.assertEqual(app.state.load('runtime')['active'], 'work@example.com')

    def test_dashboard_personal_preference_uses_existing_capacity_checks(self):
        """개인 ID를 선택하면 여유가 있을 때 유지하고, 한도에 닿으면 회사로 전환한다."""
        app = self.app
        app.state.save('preference', {'preferred': 'personal@example.com', 'requested_at': NOW})
        app.api.percent['token-personal'] = 10

        report = app.tick(apply=True, now=NOW)

        self.assertEqual(report['target'], 'personal@example.com')
        self.assertFalse(report['switched'])
        self.assertEqual(app.state.load('runtime')['preference_at'], NOW)
        app.api.percent['token-personal'] = 95
        report = app.tick(apply=True, now=NOW + 1)
        self.assertEqual(report['target'], 'work@example.com')
        self.assertTrue(report['switched'])

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

    def test_external_login_replaces_the_recorded_active_account(self):
        """다른 프로그램이 회사 계정으로 로그인하면 다음 주기에 실제 계정을 기록한다."""
        app = self.app
        app.state.save('runtime', {'active': 'personal@example.com'})
        external = app.vault.read('work@example.com')
        app.vault.active['claudeAiOauth'] = external['oauth']
        app.live.write_account(external['account'])

        report = app.tick(apply=True, now=NOW)

        self.assertEqual(report['active'], 'work@example.com')
        self.assertFalse(report['switched'])
        self.assertEqual(app.state.load('runtime')['active'], 'work@example.com')
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

    def test_identity_cache_retains_only_the_latest_token_per_account(self):
        """토큰이 여러 번 갱신돼도 계정당 최신 identity 하나만 보유하고 이전 토큰은 다시 검증한다."""
        app = self.app
        app.api.profile = Mock(wraps=app.api.profile)
        bundle = app.vault.read('personal@example.com')
        original = bundle['oauth']['accessToken']
        for version in range(100):
            bundle['oauth']['accessToken'] = original + '-' + str(version)
            app.verify_identity(bundle)

        self.assertEqual(len(app._verified_identities), 1)
        bundle['oauth']['accessToken'] = original + '-0'
        app.verify_identity(bundle)
        self.assertEqual(app.api.profile.call_count, 101)

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
        app.api.profile_overrides['new-external-login'] = {
            'email': 'other@example.com', 'uuid': 'uuid-other@example.com'}
        # when & then
        with self.assertRaises(SwitcherError):
            app.recover()
        self.assertEqual(app.vault.active['claudeAiOauth']['accessToken'], 'new-external-login')

    def test_recovery_keeps_the_targets_renewed_token_after_an_interrupted_swap(self):
        """교체 직후 중단되어도 대상 계정이 갱신한 최신 인증으로 전환을 마무리한다."""
        app = self.app
        app.vault.crash_after_write = True
        with self.assertRaises(KeyboardInterrupt):
            app.tick(apply=True, now=NOW)
        renewed = app.api.refresh(app.vault.active['claudeAiOauth'], NOW + 1)
        app.vault.active['claudeAiOauth'] = renewed

        app.recover()

        self.assertEqual(app.live.read()[1]['emailAddress'], 'work@example.com')
        self.assertEqual(app.vault.read('work@example.com')['oauth'], renewed)
        self.assertEqual(app.vault.active['claudeAiOauth'], renewed)
        self.assertEqual(app.state.load('session_refresh')['since'], NOW)
        self.assertIsNone(app.vault.read('__transaction__'))

    def test_recovery_rechecks_login_after_network_verification(self):
        """복구 소유자 확인 중 다시 바뀐 인증에는 이전 결과를 적용하지 않는다."""
        app = self.app
        app.vault.crash_after_write = True
        with self.assertRaises(KeyboardInterrupt):
            app.tick(apply=True, now=NOW)
        app.vault.active['claudeAiOauth'] = app.api.refresh(app.vault.active['claudeAiOauth'], NOW)
        profile = app.api.profile

        def replace(oauth):
            app.vault.active['claudeAiOauth']['refreshToken'] = 'newer-generation'
            return profile(oauth)

        app.api.profile = replace
        with self.assertRaises(SwitcherError):
            app.recover()
        self.assertEqual(app.live.read()[1]['emailAddress'], 'personal@example.com')
        self.assertIsNotNone(app.vault.read('__transaction__'))

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
