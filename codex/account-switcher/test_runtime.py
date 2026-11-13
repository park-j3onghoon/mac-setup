import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from policy import UsageUnavailable
from runtime import CONTINUE_PROMPT, Runtime, all_idle, prepare_home
from state import load, poll_delay, record, save, snapshot
from supervisor import monitor


def usage(percent, resets, observed):
    return snapshot({"rateLimits": {"primary": {
        "usedPercent": percent, "resetsAt": resets, "windowDurationMins": 10080,
    }}}, observed_at=observed)


class StateTest(unittest.TestCase):
    def test_reset_time_and_observation_are_preserved(self):
        value = usage(91, 200, 100)
        self.assertEqual(value["observed_at"], 100)
        self.assertEqual(value["windows"]["primary"]["resets_at"], 200)

    def test_elapsed_time_does_not_fabricate_a_reset(self):
        value = record(usage(91, 200, 100), usage(91, 200, 201))
        self.assertNotIn("last_reset_confirmed_at", value["windows"]["primary"])
        self.assertEqual(value["used_percent"], 91)

    def test_server_rollover_is_recorded_and_survives_next_poll(self):
        old = usage(91, 200, 100)
        new = record(old, usage(0, 1000, 201))
        again = record(new, usage(4, 1000, 250))
        self.assertEqual(again["windows"]["primary"]["last_reset_confirmed_at"], 201)

    def test_reset_triggers_earlier_check_without_past_time_busy_loop(self):
        self.assertEqual(poll_delay({"company": usage(91, 110, 100)}, now=100), 11)
        self.assertEqual(poll_delay({"company": usage(91, 90, 100)}, now=100), 60)

    def test_poll_interval_follows_the_active_account_headroom(self):
        later = 10_000_000
        for percent, seconds in ((20, 540), (61, 300), (80, 120), (88, 60)):
            with self.subTest(percent=percent):
                accounts = {"company": usage(percent, later, 100), "personal": usage(95, later, 100)}
                self.assertEqual(poll_delay(accounts, active="company", now=100), seconds)

    def test_only_metadata_is_written_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            value = {"accounts": {"company": usage(20, 200, 100)}}
            save(value, path)
            self.assertEqual(load(path), value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("token", path.read_text())


class HomeTest(unittest.TestCase):
    def test_shared_server_opens_with_the_company_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = root / "company.toml"
            company.write_text("model = 'company'\n")
            shared = root / "shared"
            shared.mkdir()
            (shared / "config.toml").write_text("model = 'personal'\n")
            home = root / "auto"
            home.mkdir()
            (home / "config.toml").symlink_to(shared / "config.toml")
            prepare_home(home, shared=shared, config=company)
            self.assertEqual((home / "config.toml").read_text(), "model = 'company'\n")

    def test_company_workspace_lock_is_lifted_only_on_the_shared_server(self):
        runtime = Runtime({}, home=Path("/auto"))
        with patch("runtime.prepare_home"), patch("runtime.subprocess.Popen") as popen, \
             patch.object(Path, "exists", return_value=False):
            popen.return_value.poll.return_value = 1
            with self.assertRaises(UsageUnavailable):
                runtime.start()
        self.assertEqual(popen.call_args.args[0][1:4], ["app-server", "-c", 'forced_chatgpt_workspace_id=""'])


class IdleTest(unittest.TestCase):
    def test_all_pages_are_checked(self):
        client = Mock()
        client.request.side_effect = [
            {"data": ["a"], "nextCursor": "next"},
            {"thread": {"status": {"type": "idle"}}},
            {"data": ["b"]},
            {"thread": {"status": {"type": "active", "activeFlags": ["waitingOnApproval"]}}},
        ]
        self.assertFalse(all_idle(client))

    def test_unknown_thread_state_blocks_switch(self):
        client = Mock()
        client.request.side_effect = [{"data": ["a"]}, {"thread": {}}]
        self.assertFalse(all_idle(client))

    def test_thread_stopped_by_an_error_does_not_block_switch(self):
        client = Mock()
        client.request.side_effect = [{"data": ["a"]}, {"thread": {"status": {"type": "systemError"}}}]
        self.assertTrue(all_idle(client))


LIMITED = {"data": [{"id": "turn-1", "status": "failed",
                     "error": {"codexErrorInfo": "usageLimitExceeded"}}]}


class ContinueTest(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime({})
        self.runtime.client = Mock()

    def answer(self, threads):
        def request(method, params=None, timeout=30):
            if method == "thread/loaded/list":
                return {"data": list(threads)}
            status, turns = threads.get(params.get("threadId"), (None, None))
            if method == "thread/read":
                return {"thread": {"status": {"type": status}}}
            if method == "thread/turns/list" and isinstance(turns, Exception):
                raise turns
            return turns if method == "thread/turns/list" else {}

        self.runtime.client.request.side_effect = request

    def started(self):
        return [call.args[1] for call in self.runtime.client.request.call_args_list
                if call.args[0] == "turn/start"]

    def test_turn_stopped_by_the_usage_limit_is_continued_once(self):
        self.answer({"t1": ("idle", LIMITED)})
        self.runtime.continue_limited()
        self.runtime.continue_limited()
        self.assertEqual(self.started(), [
            {"threadId": "t1", "input": [{"type": "text", "text": CONTINUE_PROMPT}]},
        ])

    def test_running_threads_and_other_endings_are_left_alone(self):
        self.answer({
            "running": ("active", LIMITED),
            "done": ("idle", {"data": [{"id": "turn-2", "status": "completed"}]}),
            "crashed": ("systemError", {"data": [{"id": "turn-3", "status": "failed",
                                                  "error": {"codexErrorInfo": "other"}}]}),
            "unprompted": ("idle", UsageUnavailable("Codex thread/turns/list failed")),
        })
        self.runtime.continue_limited()
        self.assertEqual(self.started(), [])


class SwitchingTest(unittest.TestCase):
    def setUp(self):
        self.profiles = {name: Mock(account_id=name) for name in ("company", "personal")}
        for name, profile in self.profiles.items():
            profile.tokens.return_value = {"accessToken": "dummy", "chatgptAccountId": name}
        self.runtime = Runtime(self.profiles)
        self.runtime.active = "company"
        self.runtime.client = Mock()

    def test_active_work_is_not_interrupted_or_reauthenticated(self):
        self.runtime.client.request.side_effect = [
            {"data": ["work"]}, {"thread": {"status": {"type": "active"}}},
        ]
        self.assertFalse(self.runtime.select("personal"))
        self.assertEqual(self.runtime.active, "company")
        self.profiles["personal"].tokens.assert_not_called()

        methods = [call.args[0] for call in self.runtime.client.request.call_args_list]
        self.assertNotIn("account/login/start", methods)
        self.assertNotIn("turn/interrupt", methods)

    def test_idle_switch_is_verified(self):
        self.runtime.client.request.side_effect = [
            {"data": []}, {"type": "chatgptAuthTokens"}, {"accountId": "personal"},
        ]
        self.assertTrue(self.runtime.select("personal"))
        self.assertEqual(self.runtime.active, "personal")

    def test_wrong_identity_rolls_back(self):
        self.runtime.client.request.side_effect = [
            {"data": []}, {}, {"accountId": "unexpected"}, {}, {"accountId": "company"},
        ]
        with self.assertRaises(UsageUnavailable):
            self.runtime.select("personal")
        self.assertEqual(self.runtime.active, "company")
        self.profiles["company"].tokens.assert_called_once()

    def test_failed_rollback_does_not_claim_an_unverified_active_account(self):
        self.runtime.client.request.side_effect = [
            {"data": []}, {}, {"accountId": "unexpected"}, UsageUnavailable("offline"),
        ]
        with self.assertRaises(UsageUnavailable):
            self.runtime.select("personal")
        self.assertIsNone(self.runtime.active)

    def test_token_refresh_cannot_select_an_unknown_workspace(self):
        with self.assertRaises(UsageUnavailable):
            self.runtime.refresh("account/chatgptAuthTokens/refresh", {"previousAccountId": "other"})
        for profile in self.profiles.values():
            profile.tokens.assert_not_called()

    def test_refresh_uses_original_profile_for_requested_identity(self):
        self.runtime.refresh("account/chatgptAuthTokens/refresh", {"previousAccountId": "company"})
        self.profiles["company"].tokens.assert_called_once_with(force=True)
        self.profiles["personal"].tokens.assert_not_called()


class MonitorTest(unittest.TestCase):
    def run_monitor(self, batches):
        clock = [1000]
        stop = Mock()
        stop.is_set.side_effect = lambda: clock[0] >= 1000 + len(batches) * 61
        stop.wait.side_effect = lambda _: clock.__setitem__(0, clock[0] + 61)
        runtime = Mock(active=None)
        runtime.process.poll.return_value = None
        selected = []

        def select(name):
            selected.append(name)
            runtime.active = name
            return True

        runtime.select.side_effect = select
        state = {}
        with patch("supervisor.time.time", side_effect=lambda: clock[0]), \
             patch("supervisor.collect", side_effect=batches), patch("supervisor.save"):
            monitor(runtime, {}, stop, state)
        self.runtime = runtime
        return selected, state

    def test_running_monitor_applies_fallback_and_both_high_policy(self):
        batches = [({"company": usage(company, 9999, 1000),
                     "personal": usage(personal, 9999, 1000)}, {})
                   for company, personal in ((5, 20), (95, 20), (95, 95), (0, 95))]
        selected, state = self.run_monitor(batches)
        self.assertEqual(selected, ["company", "personal", "company", "company"])
        self.assertEqual(state["active"], "company")

    def test_limit_stopped_work_continues_only_on_an_account_below_the_threshold(self):
        batches = [({"company": usage(company, 9999, 1000),
                     "personal": usage(personal, 9999, 1000)}, {})
                   for company, personal in ((95, 20), (95, 95))]
        selected, _ = self.run_monitor(batches)
        self.assertEqual(selected, ["personal", "company"])
        self.runtime.continue_limited.assert_called_once_with()

    def test_lookup_failure_keeps_current_account_and_old_reset_record(self):
        first = {"company": usage(5, 9999, 1000), "personal": usage(20, 9999, 1000)}
        selected, state = self.run_monitor([(first, {}), ({}, {"company": "Timeout"})])
        self.assertEqual(selected, ["company"])
        self.assertEqual(state["active"], "company")
        self.assertEqual(state["status"], "degraded")
        self.assertEqual(state["accounts"]["company"]["windows"]["primary"]["resets_at"], 9999)


if __name__ == "__main__":
    unittest.main()
