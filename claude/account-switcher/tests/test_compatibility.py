import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from compatibility import MARKERS, check
from macos import KeychainError, NativeKeychain
from storage import SwitcherError


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.binary = Path(self.tmp.name) / 'claude'
        self.binary.write_bytes(b'\0'.join(MARKERS))
        self.home = Path(self.tmp.name) / 'config'
        self.home.mkdir()
        self.runner = Mock(side_effect=[
            Mock(stdout='2.1.324 (Claude Code)\n'),
            Mock(stdout=json.dumps({'loggedIn': True, 'authMethod': 'claude.ai',
                                    'email': 'personal@example.com'}))])

    def test_patch_upgrade_is_accepted_when_native_login_and_storage_contract_match(self):
        report = check(str(self.binary), self.home, ('personal@example.com',), runner=self.runner)
        self.assertEqual(report['version'], '2.1.324')
        self.assertEqual(report['credential_contract'], 'verified')

    def test_actual_storage_contract_change_stops_before_auth_access(self):
        self.binary.write_bytes(b'unrecognized implementation')
        with self.assertRaises(SwitcherError):
            check(str(self.binary), self.home, ('personal@example.com',), runner=self.runner)
        self.assertEqual(self.runner.call_count, 1)

    def test_new_binary_is_rechecked_even_when_version_string_is_unchanged(self):
        report = check(str(self.binary), self.home, ('personal@example.com',), runner=self.runner)
        self.binary.write_bytes(b'unrecognized implementation after reinstall')
        with self.assertRaises(SwitcherError):
            check(str(self.binary), self.home, ('personal@example.com',), report,
                  runner=Mock(return_value=Mock(stdout='2.1.324 (Claude Code)')))

    def test_unchanged_binary_reuses_the_last_check_without_running_the_cli(self):
        """실행 파일이 그대로면 Claude Code(`--version`·`auth status`)를 다시 띄우지 않고 지난 검사 결과를 쓴다."""
        # given
        report = check(str(self.binary), self.home, ('personal@example.com',), runner=self.runner)
        runner = Mock()
        # when
        again = check(str(self.binary), self.home, ('personal@example.com',), report, runner=runner)
        # then
        self.assertEqual((again, runner.call_count), (report, 0))

    def test_native_login_mismatch_is_rejected(self):
        with self.assertRaises(SwitcherError):
            check(str(self.binary), self.home, ('work@example.com',), runner=self.runner)


def hex_of(value):
    return json.dumps(value, separators=(',', ':')).encode().hex()


def written_then_read(value):
    return Mock(side_effect=[Mock(returncode=0),
                             Mock(returncode=0, stdout=json.dumps(value).encode())])


class NativeWriterTests(unittest.TestCase):
    def test_small_payload_is_written_through_security_stdin(self):
        """짧은 로그인 정보는 Claude Code처럼 `security -i` 표준 입력으로 써서 비밀값이 인자에 실리지 않는다."""
        # given
        value = {'claudeAiOauth': {'accessToken': 'fake-private-token'}}
        runner = written_then_read(value)
        # when
        NativeKeychain(Mock(), 'test', runner).write(value)
        # then
        call = runner.call_args_list[0]
        self.assertEqual(call.args[0], ['/usr/bin/security', '-i'])
        self.assertEqual(call.kwargs['input'].decode(),
                         'add-generic-password -U -a "test" -s "Claude Code-credentials" '
                         f'-X "{hex_of(value)}"\n')

    def test_large_payload_is_written_through_security_arguments(self):
        """`security -i` 한도(4032자)를 넘는 로그인 정보는 Claude Code처럼 같은 명령을 인자로 넘긴다."""
        # given
        value = {'claudeAiOauth': {'accessToken': 'fake-private-token'},
                 'mcpOAuth': {'connector': {'accessToken': 'x' * 16000}}}
        runner = written_then_read(value)
        # when
        NativeKeychain(Mock(), 'test', runner).write(value)
        # then
        self.assertEqual(runner.call_args_list[0].args[0],
                         ['/usr/bin/security', 'add-generic-password', '-U', '-a', 'test',
                          '-s', 'Claude Code-credentials', '-X', hex_of(value)])

    def test_failed_security_write_is_reported(self):
        """`security`가 실패 코드를 돌려주면 쓰기를 성공으로 보지 않는다."""
        # given
        runner = Mock(return_value=Mock(returncode=1))
        # when & then
        with self.assertRaises(KeychainError):
            NativeKeychain(Mock(), 'test', runner).write({'claudeAiOauth': {'accessToken': 'fake'}})

    def test_readback_mismatch_is_rejected(self):
        """쓴 뒤 `security`로 다시 읽은 값이 다르면 쓰기를 성공으로 보지 않는다."""
        # given
        runner = Mock(side_effect=[Mock(returncode=0), Mock(returncode=0, stdout=b'{}')])
        # when & then
        with self.assertRaises(KeychainError):
            NativeKeychain(Mock(), 'test', runner).write({'claudeAiOauth': {'accessToken': 'fake'}})

    def test_account_name_that_breaks_the_command_is_rejected(self):
        """따옴표가 든 macOS 계정 이름은 `security -i` 명령을 깨뜨리므로 처음부터 거절한다."""
        # when & then
        with self.assertRaises(KeychainError):
            NativeKeychain(Mock(), 'te"st', Mock())


if __name__ == '__main__':
    unittest.main()
