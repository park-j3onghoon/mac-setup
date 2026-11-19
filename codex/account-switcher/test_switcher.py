from contextlib import ExitStack, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import launcher
from policy import UsageUnavailable, choose, utilization
from runtime import SOCKET
from usage import handle_message, read_usage


class PolicyTest(unittest.TestCase):
    def test_personal_preference_keeps_automatic_fallback(self):
        """개인 계정을 먼저 쓰고 개인 한도에 도달하면 회사로 전환한다."""
        self.assertEqual(choose({"company": 76, "personal": 0}, preferred="personal"), "personal")
        self.assertEqual(choose({"company": 76, "personal": 90}, preferred="personal"), "company")
        self.assertEqual(choose({"company": 95, "personal": 95}, preferred="personal"), "personal")

    def test_company_preferred_until_threshold(self):
        self.assertEqual(choose({"company": 89.9}), "company")
        self.assertEqual(choose({"company": 90, "personal": 12}), "personal")

    def test_no_fallback_when_company_usage_unknown(self):
        with self.assertRaises(UsageUnavailable):
            choose({"personal": 0})

    def test_both_near_limit_prefer_company(self):
        self.assertEqual(choose({"company": 90, "personal": 95}), "company")
        self.assertEqual(choose({"company": 100, "personal": 100}), "company")

    def test_resets_are_decided_by_reported_usage(self):
        self.assertEqual(choose({"company": 0, "personal": 50}), "company")

    def test_highest_usage_window_wins(self):
        self.assertEqual(utilization({"rateLimits": {
            "primary": {"usedPercent": 10}, "secondary": {"usedPercent": 91},
        }}), 91)

    def test_invalid_or_missing_usage_cannot_select_an_account(self):
        for value in (None, "0", True, -1, 101, float("nan")):
            with self.subTest(value=value), self.assertRaises(UsageUnavailable):
                utilization({"rateLimits": {"primary": {"usedPercent": value}}})
        with self.assertRaises(UsageUnavailable):
            utilization({})

    def test_workspace_spend_control_blocks_usage(self):
        self.assertEqual(utilization({"rateLimits": {"spendControlReached": True}}), 100)
        self.assertEqual(utilization({"ordinaryUsageAllowed": False}), 100)

    def test_server_errors_do_not_echo_secrets(self):
        with self.assertRaises(UsageUnavailable) as error:
            handle_message(None, b'{"id":2,"error":{"message":"secret-token"}}')
        self.assertNotIn("secret-token", str(error.exception))


class LauncherTest(unittest.TestCase):
    def test_unverified_running_account_is_not_displayed_as_the_preferred_account(self):
        """현재 계정을 확인할 수 없을 때 우선 계정을 실제 로그인처럼 표시하지 않는다."""
        output = StringIO()
        state = {"active": None, "preferred": "company", "status": "degraded",
                 "account_error": "UsageUnavailable"}
        with patch("service.running", return_value=True), \
             patch.object(launcher, "load", return_value=state), redirect_stdout(output):
            launcher.show_status()

        self.assertIn("selected: unknown", output.getvalue())

    def setUp(self):
        proxy_patch = patch.object(launcher, "start_proxy", return_value=SOCKET)
        self.proxy = proxy_patch.start()
        self.addCleanup(proxy_patch.stop)
        binary_patch = patch.object(launcher, "BINARY", Path(sys.executable))
        binary_patch.start()
        self.addCleanup(binary_patch.stop)

    def test_automatic_terminal_gets_idle_proxy_and_can_opt_out(self):
        """새 자동 터미널은 15분 회수 proxy를 사용하고 0으로 기존 직접 연결을 선택한다."""
        with patch("service.ensure", return_value={"active": "company"}), \
             patch.dict(launcher.os.environ, {}, clear=True), \
             patch.object(launcher.os, "execve", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                launcher.launch_automatic([])

        self.assertEqual(self.proxy.call_args.args[1], 900)
        self.proxy.reset_mock()
        with patch("service.ensure", return_value={"active": "company"}), \
             patch.dict(launcher.os.environ, {"CODEX_IDLE_SECONDS": "0"}, clear=True), \
             patch.object(launcher.os, "execve", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                launcher.launch_automatic([])

        self.proxy.assert_not_called()

    def test_stopped_service_status_honors_saved_personal_preference(self):
        """서비스가 꺼져 있어도 다음 실행에서 선택할 개인 계정을 표시한다."""
        output = StringIO()
        snapshots = [{"used_percent": percent, "observed_at": 100, "windows": {}}
                     for percent in (76, 0)]
        with patch("service.running", return_value=False), \
             patch.object(launcher, "load", return_value={"preferred": "personal"}), \
             patch.object(launcher, "read_snapshot", side_effect=snapshots), \
             patch.object(launcher, "save"), redirect_stdout(output):
            launcher.show_status()

        self.assertIn("selected: personal", output.getvalue())

    def test_explicit_home_is_preserved(self):
        with patch.dict(launcher.os.environ, {"CODEX_HOME": "/chosen"}), \
             patch.object(launcher.os, "execv", side_effect=SystemExit) as run:
            with self.assertRaises(SystemExit):
                launcher.main(["resume", "my-thread"])
        self.assertEqual(run.call_args.args[1][1:], ["resume", "my-thread"])

    def test_company_management_does_not_query_or_select_personal(self):
        with patch.dict(launcher.os.environ, {}, clear=True), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(launcher, "read_usage") as query, \
             patch.object(launcher.os, "execve", side_effect=SystemExit) as run:
            with self.assertRaises(SystemExit):
                launcher.main(["login", "status"])
        query.assert_not_called()
        self.assertEqual(run.call_args.args[2]["CODEX_HOME"], str(launcher.PROFILES["company"]))

    def test_resume_uses_same_automatic_runtime_history(self):
        with patch.dict(launcher.os.environ, {}, clear=True), \
             patch.object(launcher, "launch_automatic", return_value=0) as run:
            self.assertEqual(launcher.main(["resume", "--last"]), 0)
        run.assert_called_once_with(["resume", "--last"])

    def test_full_company_falls_back_without_rewriting_credentials(self):
        with patch.dict(launcher.os.environ, {}, clear=True), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(launcher, "read_usage", side_effect=[90, 5]), \
             patch.object(launcher.os, "execve", side_effect=SystemExit) as run:
            with self.assertRaises(SystemExit):
                launcher.main(["--cd", "/project", "exec", "do work"])
        self.assertEqual(run.call_args.args[1][1:], ["--cd", "/project", "exec", "do work"])
        self.assertEqual(run.call_args.args[2]["CODEX_HOME"], str(launcher.PROFILES["personal"]))

    def test_interactive_session_uses_automatic_runtime(self):
        with patch.dict(launcher.os.environ, {}, clear=True), \
             patch.object(launcher, "launch_automatic", return_value=0) as run:
            self.assertEqual(launcher.main(["--model", "chosen-model"]), 0)
        run.assert_called_once_with(["--model", "chosen-model"])

    def test_automatic_session_runs_in_the_terminal_directory(self):
        with patch("service.ensure", return_value={"active": "company"}), \
             patch.dict(launcher.os.environ, {}, clear=True), \
             patch.object(launcher.os, "getcwd", return_value="/project"), \
             patch.object(launcher.os, "execve", side_effect=SystemExit) as run:
            with self.assertRaises(SystemExit):
                launcher.launch_automatic(["resume", "--last"])
        self.assertEqual(run.call_args.args[1][1:],
                         ["--remote", "unix://" + str(SOCKET), "-C", "/project", "resume", "--last"])

    def test_directory_given_by_the_user_is_kept(self):
        with patch("service.ensure", return_value={"active": "company"}), \
             patch.dict(launcher.os.environ, {}, clear=True), \
             patch.object(launcher.os, "execve", side_effect=SystemExit) as run:
            with self.assertRaises(SystemExit):
                launcher.launch_automatic(["--cd", "/chosen"])
        self.assertEqual(run.call_args.args[1][1:], ["--remote", "unix://" + str(SOCKET), "--cd", "/chosen"])

    def test_session_in_a_cmux_tab_passes_the_tab_to_its_shell_commands(self):
        with patch("service.ensure", return_value={"active": "company"}), \
             patch.dict(launcher.os.environ, {"CMUX_SURFACE_ID": "SURFACE-1",
                                              "CMUX_SOCKET_CAPABILITY": "v1.CAP"}, clear=True), \
             patch.object(launcher.os, "getpid", return_value=4321), \
             patch.object(launcher.os, "execve", side_effect=SystemExit) as run:
            with self.assertRaises(SystemExit):
                launcher.launch_automatic(["--cd", "/chosen"])
        self.assertEqual(run.call_args.args[1][1:], [
            "--remote", "unix://" + str(SOCKET),
            "-c", 'shell_environment_policy.set.CMUX_SURFACE_ID="SURFACE-1"',
            "-c", 'shell_environment_policy.set.CMUX_SOCKET_CAPABILITY="v1.CAP"',
            "-c", 'shell_environment_policy.set.CMUX_CODEX_PID="4321"',
            "--cd", "/chosen",
        ])

    def test_management_after_global_options_is_recognized(self):
        self.assertFalse(launcher.interactive(["-c", "model=chosen", "login", "status"]))
        self.assertFalse(launcher.interactive(["--cd=/project", "exec", "do work"]))


class TerminalVersionTest(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        cask = root / "Caskroom" / "codex"
        self.installed = cask / "0.170.0" / "bin" / "codex"
        self.previous = cask / "0.169.0" / "bin" / "codex"
        for cli in (self.installed, self.previous):
            cli.parent.mkdir(parents=True)
            cli.touch(mode=0o700)
        link = root / "codex"
        link.symlink_to(self.installed)
        stack.enter_context(patch.object(launcher, "BINARY", link))
        stack.enter_context(patch.object(launcher, "RUNTIME", root / "auto"))
        self.connection = stack.enter_context(patch.object(launcher, "UnixWebSocket")).return_value
        stack.enter_context(patch("service.ensure", return_value={"active": "company"}))
        stack.enter_context(patch.dict(launcher.os.environ, {"CODEX_IDLE_SECONDS": "0"}, clear=True))
        self.run = stack.enter_context(patch.object(launcher.os, "execve", side_effect=SystemExit))

    def launched(self, version, arguments):
        self.connection.messages.return_value = [
            json.dumps({"id": 1, "result": {"userAgent": f"codex/{version} (macOS)"}}).encode()
        ]
        with self.assertRaises(SystemExit):
            launcher.launch_automatic(arguments)
        executable, argv, _ = self.run.call_args.args
        self.assertEqual(argv[0], executable)
        return Path(executable)

    def test_terminal_tracks_the_live_server_across_a_homebrew_upgrade_and_restart(self):
        """새 대화와 resume은 구형 서버에 맞추고 서버가 교체되면 새 CLI를 쓴다."""
        self.assertEqual(self.launched("0.169.0", []), self.previous)
        saved = launcher.RUNTIME / "app-server-packages" / "0.169.0" / "bin" / "codex"
        saved.parent.mkdir(parents=True)
        self.previous.rename(saved)
        self.assertEqual(self.launched("0.169.0", ["resume", "--last"]), saved)
        self.assertEqual(self.launched("0.170.0", []), self.installed)

    def test_unavailable_version_or_package_keeps_the_installed_cli_usable(self):
        """소켓 조회 실패나 이전 패키지 부재에도 기존 CLI로 resume을 열 수 있다."""
        self.assertEqual(self.launched("0.168.0", ["resume"]), self.installed)
        for failure in (TimeoutError(), EOFError()):
            with self.subTest(failure=failure):
                self.connection.messages.side_effect = failure
                self.assertEqual(self.launched("0.169.0", ["resume"]), self.installed)
                self.connection.close.assert_called()


class ProtocolTest(unittest.TestCase):
    def test_real_subprocess_handshake_and_notification_handling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "auth.json").write_text("{}")
            fake = root / "codex"
            fake.write_text("#!" + sys.executable + "\n" + '''import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if message["method"] == "initialize":
        print('{"id":1,"result":{}}', flush=True)
    elif message["method"] == "account/rateLimits/read":
        print('{"method":"account/updated","params":{}}', flush=True)
        print('{"id":2,"result":{"rateLimits":{"primary":{"usedPercent":42}}}}', flush=True)
''')
            fake.chmod(0o700)
            self.assertEqual(read_usage(fake, root, timeout=2), 42)


if __name__ == "__main__":
    unittest.main()
