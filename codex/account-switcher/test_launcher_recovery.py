"""Recovery contracts at the command and service boundaries."""
import base64
from contextlib import ExitStack, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

import launcher
import service
import state
from policy import DEFAULT_POLICY, UsageUnavailable
from profiles import DEFAULT_SETTINGS, Settings
from switchcore.policy import StrictPriorityPolicy


class LauncherRecoveryTests(unittest.TestCase):
    def test_directory_is_an_option_only_before_separator(self):
        self.assertFalse(launcher.has_directory_option(['--', '-C shopping list']))
        self.assertFalse(launcher.has_directory_option(['--model', '-Ctest', 'prompt']))
        self.assertTrue(launcher.has_directory_option(['resume', '--cd=/work']))
        self.assertTrue(launcher.has_directory_option(['-C/work']))

    def test_doctor_needs_no_auth_file(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(launcher, 'raise_file_limit'), \
                patch.object(launcher, 'load_settings', return_value=DEFAULT_SETTINGS), \
                patch.object(Path, 'is_file', return_value=False), patch.object(os, 'execve') as run:
            launcher.main(['doctor'])
        self.assertEqual(run.call_args.args[1][-1], 'doctor')

    def test_timeout_is_a_service_error(self):
        with patch('service.subprocess.run', side_effect=subprocess.TimeoutExpired('launchctl', 10)):
            with self.assertRaises(UsageUnavailable):
                service.job_status('fixture')

    def test_old_supervisor_state_is_not_readiness_for_a_replacement_socket(self):
        with patch.object(service, 'peer_process', return_value=(12, 'new')):
            self.assertFalse(service.matches_runtime(Mock(), {'runtime_pid': 10, 'runtime_pid_start': 'old'}))
            self.assertTrue(service.matches_runtime(Mock(), {'runtime_pid': 12, 'runtime_pid_start': 'new'}))

    def test_update_timeout_still_updates_second_product(self):
        with patch('launcher.subprocess.run', side_effect=[
            subprocess.TimeoutExpired('update', 300), Mock(returncode=0)
        ]) as run, patch('launcher.report_runtime_update', return_value=True):
            self.assertEqual(launcher.update_clis(), 1)
        self.assertEqual(run.call_count, 2)

    def test_stopped_supervisor_with_unverified_existing_socket_cannot_confirm_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'server.sock'
            path.touch()
            with patch('runtime.SOCKET', path), patch('launcher.load', return_value={}), \
                    patch('service.running', return_value=False), \
                    patch('launcher.server_version', side_effect=ConnectionRefusedError):
                self.assertFalse(launcher.report_runtime_update())


class DirectSelectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.homes = {name: self.home / name for name in ('company', 'personal')}
        for name, path in self.homes.items():
            path.mkdir()
            self.login(name, name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(launcher, 'RUNTIME', self.home))
        self.settings = Settings(self.homes, 90, DEFAULT_POLICY)
        stack.enter_context(patch.object(launcher, 'load_settings', return_value=self.settings))

    def login(self, name, workspace):
        claims = {'exp': 1e12, 'https://api.openai.com/auth': {
            'chatgpt_account_id': workspace, 'chatgpt_plan_type': 'fixture'}}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
        (self.homes[name] / 'auth.json').write_text(json.dumps({'tokens': {'access_token': f'x.{payload}.x'}}))

    def sample(self, name, used, observed=1, **additional):
        return {'account_id': name, 'used_percent': used, 'observed_at': observed, 'windows': {}, **additional}

    def test_broken_unused_profile_allows_healthy_company_only(self):
        (self.homes['personal'] / 'auth.json').write_text('{')
        with patch.object(launcher, 'read_snapshot', return_value=self.sample('company', 5)) as read:
            self.assertEqual(launcher.direct_usages({}, self.settings), {'company': 5})
        self.assertEqual([call.args[1] for call in read.call_args_list], [self.homes['company']])

    def test_known_duplicate_rejected_without_quota_call(self):
        self.login('personal', 'company')
        with patch.object(launcher, 'read_snapshot') as read, self.assertRaisesRegex(UsageUnavailable, 'duplicated'):
            launcher.direct_usages({}, self.settings)
        read.assert_not_called()

    def test_needed_profile_must_have_a_readable_registered_login(self):
        with patch.object(launcher, 'read_snapshot', return_value=self.sample('company', 94)):
            (self.homes['personal'] / 'auth.json').write_text('{')
            with self.assertRaisesRegex(UsageUnavailable, 'personal login is unavailable'):
                launcher.direct_usages({}, self.settings)
            (self.homes['company'] / 'auth.json').write_text('{')
            with self.assertRaisesRegex(UsageUnavailable, 'company login is unavailable'):
                launcher.direct_usages({}, self.settings)

    def test_direct_rejects_unregistered_workspace_change(self):
        with patch.object(launcher, 'read_snapshot', return_value=self.sample('company', 1)):
            self.assertEqual(launcher.direct_usages({}, self.settings), {'company': 1})
            self.login('company', 'replacement')
            with self.assertRaisesRegex(UsageUnavailable, 'needs registration'):
                launcher.direct_usages({}, self.settings)

    def test_direct_and_supervisor_history_keep_independent_blocks(self):
        direct = self.sample('company', 100, 10, ordinary_usage_allowed=False)
        state.save(direct, self.home / 'direct-usage-company.json')
        saved = {'accounts': {'company': self.sample('company', 100, 20, spend_control_reached=True)}}
        def run(company):
            with patch.object(launcher, 'read_snapshot', side_effect=[company, self.sample('personal', 4)]):
                return launcher.direct_usages(saved, self.settings)
        self.assertEqual(run(self.sample('company', 3, 30)), {'company': 100, 'personal': 4})
        self.assertEqual(run(self.sample('company', 3, 35, ordinary_usage_allowed=True)),
                         {'company': 100, 'personal': 4})
        self.assertEqual(run(self.sample('company', 3, 40, spend_control_reached=False)), {'company': 3})

    def test_newer_unknown_observation_cannot_erase_direct_block(self):
        saved = {'accounts': {'company': self.sample('company', 3, 20, ordinary_usage_allowed=None)}}
        with patch.object(launcher, 'read_snapshot', side_effect=[
                self.sample('company', 100, 10, ordinary_usage_allowed=False), self.sample('personal', 1),
                self.sample('company', 2, 30), self.sample('personal', 1)]):
            launcher.direct_usages({}, self.settings)
            self.assertEqual(launcher.direct_usages(saved, self.settings), {'company': 100, 'personal': 1})

    def test_the_configured_threshold_ends_the_direct_lookup(self):
        """기준을 95로 설정하면 92%인 회사 계정에서 바로 조회를 멈춘다. 기본 90이면 개인까지 읽는다."""
        settings = Settings(self.homes, 95, StrictPriorityPolicy(95, 60))
        with patch.object(launcher, 'read_snapshot', return_value=self.sample('company', 92)) as read:
            usages = launcher.direct_usages({}, settings)

        self.assertEqual((usages, read.call_count), ({'company': 92}, 1))

    def test_direct_launch_opens_company_when_both_are_over_the_threshold(self):
        """감독 없이 바로 여는 실행은 두 계정이 모두 기준 이상이면 회사 계정으로 연다."""
        samples = [self.sample('company', 95), self.sample('personal', 97)]
        with patch.dict(os.environ, {}, clear=True), patch.object(launcher, 'raise_file_limit'), \
                patch.object(launcher, 'load', return_value={}), \
                patch.object(service, 'running', return_value=False), \
                patch.object(launcher, 'read_snapshot', side_effect=samples), \
                patch.object(os, 'execve') as run, redirect_stderr(io.StringIO()):
            launcher.main(['exec', 'hello'])

        self.assertEqual(run.call_args.args[2]['CODEX_HOME'], str(self.homes['company']))

    def test_unreadable_existing_direct_cache_does_not_assume_quota_recovery(self):
        (self.home / 'direct-usage-company.json').write_text('{')
        with patch.object(launcher, 'read_snapshot') as read, self.assertRaises(UsageUnavailable):
            launcher.direct_usages({}, self.settings)
        read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
