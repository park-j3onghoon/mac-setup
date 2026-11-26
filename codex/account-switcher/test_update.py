from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import launcher
from policy import UsageUnavailable
from profiles import DEFAULT_SETTINGS
from rpc import RpcRejected
import supervisor
from runtime import Runtime


class UpdateTest(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.installed = root / "Caskroom" / "codex" / "0.170.0" / "bin" / "codex"
        self.installed.parent.mkdir(parents=True)
        self.installed.touch()
        self.runtime = Runtime({"company": Mock()}, home=root, binary=self.installed)
        self.runtime.pid = 321
        self.runtime.pid_start = "original"
        self.runtime.active = "company"
        self.runtime.client = Mock(closed=False)
        stack.enter_context(patch.object(self.runtime, "observe_account"))
        stack.enter_context(patch("runtime.Rpc")).return_value.version = "0.170.0"
        self.peer = stack.enter_context(patch("runtime.peer_process", return_value=(321, "original")))
        self.threads = stack.enter_context(patch("runtime.loaded_threads", return_value=[]))
        self.signal = stack.enter_context(patch("runtime.os.kill"))
        self.stage = stack.enter_context(patch("runtime.preserve_server_package"))
        self.state = {"runtime_version": "0.169.0"}

    def test_current_release_needs_no_thread_queries_or_signals(self):
        self.state["runtime_version"] = "0.170.0"
        supervisor.check_upgrade(self.runtime, self.state)
        self.threads.assert_not_called()
        self.signal.assert_not_called()

    def test_busy_runtime_waits_then_drains_only_its_own_server(self):
        self.threads.return_value = [("t", {"status": {"type": "active"}})]
        supervisor.check_upgrade(self.runtime, self.state)
        self.assertEqual(self.state["upgrade_status"], "waiting_for_idle")
        self.signal.assert_not_called()

        self.threads.return_value = []
        supervisor.check_upgrade(self.runtime, self.state)
        self.assertEqual(self.state["upgrade_status"], "draining")
        self.stage.assert_called_once()
        self.signal.assert_called_once_with(321, signal.SIGHUP)

    def test_idle_thread_with_background_work_keeps_its_server(self):
        self.threads.return_value = [("t", {"status": {"type": "idle"}, "ephemeral": False})]
        self.runtime.client.request.return_value = {"data": ["terminal"]}
        supervisor.check_upgrade(self.runtime, self.state)
        self.assertEqual(self.state["upgrade_status"], "waiting_for_idle")
        self.signal.assert_not_called()

    def test_wrong_peer_or_unusable_package_leaves_server_running(self):
        self.peer.return_value = (777, "original")
        with self.assertRaises(UsageUnavailable):
            supervisor.check_upgrade(self.runtime, self.state)
        self.peer.return_value = (321, "original")
        self.runtime.prepared_upgrade = None
        self.stage.side_effect = OSError("disk full")
        with self.assertRaises(OSError):
            supervisor.check_upgrade(self.runtime, self.state)
        self.signal.assert_not_called()

    def test_ending_a_drain_interrupts_only_turns_still_running(self):
        self.threads.return_value = [(name, {"status": {"type": status}}) for name, status in (
            ("idle", "idle"), ("starting", "active"), ("done", "active"), ("watch", "active"), ("ended", "active"))]
        turns = {"starting": None, "done": {"id": "d", "status": "completed"},
                 "watch": {"id": "w", "status": "inProgress"}, "ended": {"id": "e", "status": "inProgress"}}

        def request(method, params):
            if params["threadId"] == "ended":
                raise RpcRejected("no active turn to interrupt")
            return {}
        self.runtime.client.request.side_effect = request

        with patch("runtime.newest_turn", side_effect=lambda _, thread_id: turns[thread_id]):
            interrupted = self.runtime.interrupt_running_turns()

        self.assertEqual(interrupted, [["watch", "w"]])
        self.assertEqual([call.args for call in self.runtime.client.request.call_args_list],
                         [("turn/interrupt", {"threadId": "watch", "turnId": "w"}),
                          ("turn/interrupt", {"threadId": "ended", "turnId": "e"})])

    def test_ending_a_drain_reconnects_a_closed_client_first(self):
        self.runtime.client.closed = True

        self.runtime.interrupt_running_turns()

        self.runtime.observe_account.assert_called_once_with()

    def test_ending_a_drain_on_another_server_interrupts_nothing(self):
        self.peer.return_value = (999, "replacement")

        with self.assertRaises(UsageUnavailable):
            self.runtime.interrupt_running_turns()

        self.runtime.client.request.assert_not_called()

    def test_unavailable_previous_login_defers_the_restart(self):
        self.runtime.profiles["company"].tokens.side_effect = UsageUnavailable("unavailable")
        with self.assertRaises(UsageUnavailable):
            supervisor.check_upgrade(self.runtime, self.state)
        self.signal.assert_not_called()

    def test_bare_update_runs_both_native_updaters_even_if_one_fails(self):
        with patch("launcher.subprocess.run") as run, patch("launcher.load", return_value={}), \
                patch("runtime.SOCKET", self.runtime.home / 'fixture-update.sock'), \
                patch.object(launcher, "RUNTIME", self.runtime.home):
            run.side_effect = [Mock(returncode=1), Mock(returncode=0)]
            self.assertNotEqual(launcher.main(["update"]), 0)
        self.assertEqual([str(call.args[0][0]) for call in run.call_args_list],
                         [str(launcher.BINARY), str(Path.home() / ".local/bin/claude")])
        self.assertTrue(all(call.args[0][1:] == ["update"] for call in run.call_args_list))

    def test_both_zsh_commands_update_together_and_pass_other_arguments_unchanged(self):
        root = self.runtime.home
        rc = root / "mac/ai-cli-update.zsh"
        rc.parent.mkdir()
        shutil.copy(Path(__file__).resolve().parents[2] / "mac/ai-cli-update.zsh", rc)
        hook = root / "hook.zsh"
        hook.symlink_to(rc)
        entry = root / "codex/account-switcher/launcher.py"
        entry.parent.mkdir(parents=True)
        binaries = root / "bin"
        binaries.mkdir()
        for binary, label in [(entry, "both"), (binaries / "codex", "codex"), (binaries / "claude", "claude")]:
            binary.write_text(f'#!/bin/sh\nprintf "%s|" {label} "$@"\n')
            binary.chmod(0o700)
        result = subprocess.run(["/bin/zsh", "-f", "-c",
                                 'source "$1"; codex update; claude update; codex resume "a b"; claude update --help',
                                 "test", str(hook)], env=dict(os.environ, PATH=str(binaries)),
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "both|update|both|update|codex|resume|a b|claude|update|--help|")

    def test_pending_work_and_update_failures_have_distinct_results(self):
        state = {"runtime_version": "0.169.0", "upgrade_target": "0.170.0", "upgrade_status": "waiting_for_idle"}
        with patch.object(launcher, "BINARY", self.installed), patch("service.running", return_value=True), \
                patch.object(launcher, "load", return_value=state):
            self.assertTrue(launcher.report_runtime_update())
            state["upgrade_error"] = "TimeoutError"
            self.assertFalse(launcher.report_runtime_update())

    def test_replacement_gets_the_account_of_the_drained_server(self):
        old, new = Mock(pid=101, pid_start="old", process=None), Mock(pid=202, pid_start="new")
        old.client.version, new.client.version = "0.169.0", "0.170.0"
        state = {"runtime_pid": 101, "runtime_pid_start": "old", "upgrade_status": "draining", "restore_account": "personal"}
        calls = []

        def monitor(runtime, profiles, stop, state):
            calls.append((runtime.pid, state.get("upgrade_status"), state["runtime_version"]))
            return runtime is old

        with patch("supervisor.Runtime", side_effect=[old, new]), patch("supervisor.save"), \
                patch("supervisor.monitor", side_effect=monitor):
            supervisor.run_runtimes({}, Mock(**{"is_set.return_value": False}), state, DEFAULT_SETTINGS)

        self.assertEqual(calls, [(101, "draining", "0.169.0"), (202, None, "0.170.0")])
        new.start.assert_called_once_with(restore_account="personal")
        old.close.assert_called_once_with()

    def test_replacement_restores_the_previous_login_without_a_new_account_selection(self):
        runtime = Runtime({"personal": Mock(account_id="same")})
        runtime.profiles["personal"].tokens.return_value = {}
        runtime.client = Mock(closed=False)
        runtime.client.request.side_effect = [
            {"account": None}, {}, {"account": {"type": "chatgpt"}, "workspaceRouting": {"chatgptAccountId": "same"}}
        ]
        runtime.restore_account("personal")
        self.assertEqual(runtime.active, "personal")
        runtime.profiles["personal"].usage.assert_not_called()
