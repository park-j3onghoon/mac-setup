import json
import unittest
from unittest.mock import Mock

from idle import IdleThreads, Proxy
from policy import UsageUnavailable


class Server:
    def __init__(self):
        self.state = "idle"
        self.background = []
        self.goal = None
        self.queue = []
        self.calls = []
        self.loaded = ["thread"]
        self.children = []
        self.turns = [{"id": "turn", "status": "completed"}]

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": self.loaded}
        if method == "thread/list":
            return {"data": self.children}
        if method == "thread/read":
            return {"thread": {"status": {"type": self.state}, "ephemeral": False,
                               "parentThreadId": "thread" if params["threadId"] == "child" else None}}
        if method == "thread/backgroundTerminals/list":
            return {"data": self.background}
        if method == "thread/goal/get":
            return {"goal": self.goal}
        if method == "thread/queue/list":
            return {"data": self.queue}
        if method == "thread/turns/list":
            return {"data": self.turns}
        if method in ("thread/unsubscribe", "thread/resume"):
            return {}
        raise AssertionError(method)


class IdleTest(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.idle = IdleThreads(self.server.request, delay=10)
        self.idle.track({"thread": {"id": "thread", "ephemeral": False, "parentThreadId": None}},
                        {"config": {"shell_environment_policy.set.TAB": "original"}}, now=0)

    def test_idle_connection_unsubscribes_and_resumes_same_thread_before_use(self):
        """터미널 연결은 유지하고 유휴 구독만 해제한 뒤 같은 기록과 환경으로 resume한다."""
        self.idle.park(now=9)
        self.assertFalse(self.idle.sleeping)
        self.idle.park(now=10)
        self.assertEqual(self.idle.sleeping, {"thread"})

        self.idle.wake("thread", now=11)

        self.assertFalse(self.idle.sleeping)
        method, params = self.server.calls[-1]
        self.assertEqual(method, "thread/resume")
        self.assertEqual(params["threadId"], "thread")
        self.assertEqual(params["config"]["shell_environment_policy.set.TAB"], "original")

    def test_work_and_undurable_history_are_never_parked(self):
        """응답·승인 대기·백그라운드 작업·goal·queue·기록 없는 대화는 회수하지 않는다."""
        cases = (("state", "active"), ("background", [{}]), ("goal", {"status": "active"}),
                 ("queue", [{}]), ("turns", []), ("loaded", ["thread", "child"]), ("children", [{}]))
        for field, value in cases:
            with self.subTest(field=field):
                server = Server()
                setattr(server, field, value)
                idle = IdleThreads(server.request, delay=1)
                idle.track({"thread": {"id": "thread", "ephemeral": False, "parentThreadId": None}}, {}, now=0)

                idle.park(now=2)

                self.assertFalse(idle.sleeping)
                self.assertFalse(any(method == "thread/unsubscribe" for method, _ in server.calls))

    def test_unknown_state_and_modified_runtime_permissions_keep_subscription(self):
        """정확히 복원할 수 없는 설정 변경이 있으면 원래 runtime을 유지한다."""
        self.idle.preserve("thread")

        self.idle.park(now=20)

        self.assertFalse(self.idle.sleeping)

    def test_inspecting_a_parked_child_cannot_retain_a_new_automatic_subscription(self):
        """다른 연결의 단순 child resume가 붙인 구독도 다음 유휴 검사에서 다시 해제한다."""
        self.server.loaded = ["child"]
        self.idle.track({"thread": {"id": "child", "ephemeral": False, "parentThreadId": "thread"}}, {}, now=0)
        self.idle.park(now=10)

        self.idle.park(now=20)

        releases = [params["threadId"] for method, params in self.server.calls if method == "thread/unsubscribe"]
        self.assertEqual(releases, ["child", "child"])


class ProxyTest(unittest.TestCase):
    def setUp(self):
        self.client, self.server = Mock(), Mock()
        self.proxy = Proxy(self.client, self.server, delay=10)
        self.proxy.idle.track({"thread": {"id": "thread", "ephemeral": False}}, {}, now=0)

    def test_failed_wake_rejects_before_forwarding_user_input(self):
        """resume 실패는 제출 전 거절로 반환하여 TUI가 입력을 composer에 복원하게 한다."""
        self.proxy.idle.sleeping.add("thread")
        self.proxy.idle.request = Mock(side_effect=UsageUnavailable("fixture"))

        self.proxy.forward_client({"id": 3, "method": "turn/start", "params": {"threadId": "thread"}})

        self.server.send.assert_not_called()
        self.assertEqual(json.loads(self.client.send.call_args.args[0])["error"]["code"], -32600)

    def test_settings_changed_by_another_connection_keep_current_runtime(self):
        """실제로 변경된 sticky 설정은 이전 start params로 덮어쓰지 않는다."""
        self.proxy.forward_server({"method": "thread/settings/updated", "params": {"threadId": "thread"}})

        self.assertTrue(self.proxy.idle.threads["thread"]["blocked"])

    def test_resolved_server_request_does_not_keep_connection_busy(self):
        """다른 연결이 해결한 승인도 pending 목록에서 제거한다."""
        self.proxy.forward_server({"id": 8, "method": "item/commandExecution/requestApproval", "params": {}})

        self.proxy.forward_server({"method": "serverRequest/resolved", "params": {"requestId": 8}})

        self.assertFalse(self.proxy.server_requests)

    def test_owner_restart_reattaches_sleeping_child_before_unload_grace_expires(self):
        """owner가 다시 실행한 자식은 status 알림에서 실제로 resume하여 후속 background 작업을 보존한다."""
        self.proxy.idle.track({"thread": {"id": "child", "ephemeral": False, "parentThreadId": "thread"}}, {}, now=0)
        self.proxy.idle.sleeping.add("child")
        self.proxy.idle.request = Mock(return_value={})

        self.proxy.forward_server({"method": "thread/status/changed", "params": {
            "threadId": "child", "status": {"type": "active"},
        }})

        self.proxy.idle.request.assert_called_once_with("thread/resume", {"threadId": "child", "excludeTurns": True})
        self.assertNotIn("child", self.proxy.idle.sleeping)

    def test_intentional_unload_never_delivers_tui_exit_notification(self):
        """의도적인 unload의 thread/closed를 TUI에 보내지 않아 입력 초안을 보존한다."""
        self.proxy.idle.sleeping.add("thread")
        self.server.messages.return_value = iter([
            json.dumps({"method": "thread/closed", "params": {"threadId": "thread"}}).encode(),
        ])

        self.proxy.read("server", self.server)

        self.assertEqual(self.proxy.events.get_nowait(), ("server", None))
        self.assertTrue(self.proxy.events.empty())


if __name__ == "__main__":
    unittest.main()
