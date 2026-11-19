import json
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from idle import IdleThreads, Proxy
from policy import UsageUnavailable


class Transport:
    def __init__(self):
        self.incoming, self.outgoing = queue.Queue(), queue.Queue()

    def messages(self):
        while True:
            payload = self.incoming.get()
            if payload is None:
                return
            yield payload

    def send(self, payload):
        self.outgoing.put(payload)

    def close(self):
        self.incoming.put(None)


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

    def test_idle_batch_reads_loaded_graph_once(self):
        """50개 대화 검사에서 목록과 부모 관계를 공유하고 각 대화 상태를 재검증한다."""
        self.server.loaded = [str(i) for i in range(50)]
        idle = IdleThreads(self.server.request, delay=1)
        for thread_id in self.server.loaded:
            idle.track({'thread': {'id': thread_id, 'ephemeral': False}}, {}, 0)

        idle.park(10)

        self.assertEqual(idle.sleeping, set(self.server.loaded))
        methods = [method for method, _ in self.server.calls]
        self.assertEqual(methods.count('thread/loaded/list'), 1)
        self.assertLessEqual(methods.count('thread/read'), 100)

    def test_child_on_later_loaded_page_preserves_parent(self):
        """loaded 목록 다음 페이지의 ephemeral 자식도 parent 회수를 막는다."""
        request = self.server.request
        def paginated(method, params):
            if method == 'thread/loaded/list':
                return {'data': ['child']} if params.get('cursor') else {'data': ['thread'], 'nextCursor': 'next'}
            return request(method, params)
        self.idle.request = paginated

        self.idle.park(20)

        self.assertFalse(self.idle.sleeping)

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

    def test_activity_during_idle_checks_prevents_unsubscribe(self):
        """조회 중 입력을 받은 대화는 오래된 idle 검사 결과로 unsubscribe하지 않는다."""
        request = self.server.request
        def receive_input(method, params):
            result = request(method, params)
            if method == 'thread/turns/list':
                self.idle.touch('thread', 21)
            return result
        self.idle.request = receive_input

        self.idle.park(now=20)

        self.assertFalse(self.idle.sleeping)
        self.assertFalse(any(method == 'thread/unsubscribe' for method, _ in self.server.calls))

    def test_inspecting_a_parked_child_cannot_retain_a_new_automatic_subscription(self):
        """다른 연결의 단순 child resume가 붙인 구독도 다음 유휴 검사에서 다시 해제한다."""
        self.server.loaded = ["child"]
        self.idle.track({"thread": {"id": "child", "ephemeral": False, "parentThreadId": "thread"}}, {}, now=0)
        self.idle.park(now=10)

        self.idle.park(now=20)

        releases = [params["threadId"] for method, params in self.server.calls if method == "thread/unsubscribe"]
        self.assertEqual(releases, ["child", "child"])


class ProxyTest(unittest.TestCase):
    def test_failed_idle_check_does_not_delay_other_threads(self):
        """첫 대화 조회 실패 뒤에도 다른 유휴 대화는 다음 점검에서 바로 검사한다."""
        self.proxy.initialized = True
        self.proxy.idle.track({'thread': {'id': 'healthy', 'ephemeral': False}}, {}, 0)
        self.proxy.inspect_idle()
        first = json.loads(self.server.send.call_args.args[0])
        self.assertEqual(first['params']['parentThreadId'], 'thread')
        self.proxy.pending[self.proxy.check_id].put({'error': {'message': 'unavailable'}})
        self.proxy.inspect_idle()
        self.proxy.inspect_idle()
        next_request = json.loads(self.server.send.call_args.args[0])
        self.assertEqual(next_request['params']['parentThreadId'], 'healthy')
        self.assertEqual(self.proxy.idle.threads['healthy']['last_activity'], 0)

    def test_failed_discovery_keeps_the_next_unqueried_thread(self):
        """한 대화 조회가 실패해도 아직 조회하지 않은 다음 대화는 대기 목록에 남긴다."""
        self.proxy.initialized = True
        for thread_id in ('first', 'next'):
            self.send_server({'method': 'thread/status/changed', 'params': {
                'threadId': thread_id, 'status': {'type': 'idle'},
            }})
        self.proxy.inspect_idle()
        self.proxy.pending[self.proxy.check_id].put({'error': {'message': 'unavailable'}})

        self.proxy.inspect_idle()

        self.assertEqual(list(self.proxy.discoveries), ['next'])
        self.proxy.inspect_idle()
        request = json.loads(self.server.send.call_args.args[0])
        self.assertEqual(request['params'], {'threadId': 'next'})

    def test_deleted_thread_releases_resume_state_and_cancels_discovery(self):
        """삭제 알림은 복원 상태를 없애며 늦은 조회 응답으로 되살리지 않는다."""
        self.proxy.initialized = True
        self.send_server({'method': 'thread/status/changed', 'params': {
            'threadId': 'child', 'status': {'type': 'idle'},
        }})
        self.proxy.inspect_idle()
        request_id = self.proxy.check_id
        self.proxy.idle.track({'thread': {'id': 'child', 'ephemeral': False}}, {}, 0)
        self.proxy.idle.sleeping.add('child')

        self.send_server({'method': 'thread/deleted', 'params': {'threadId': 'child'}})
        self.proxy.receive('server', json.dumps({'id': request_id, 'result': {'thread': {
            'id': 'child', 'ephemeral': False, 'parentThreadId': 'thread',
        }}}).encode())

        self.assertNotIn('child', self.proxy.idle.threads)
        self.assertNotIn('child', self.proxy.idle.sleeping)
        self.assertNotIn('child', self.proxy.discoveries)
        self.assertNotIn(request_id, self.proxy.pending)

    def test_unknown_status_discovery_does_not_block_user_input(self):
        """처음 보는 대화의 조회 응답을 기다리는 동안에도 사용자 입력을 전달한다."""
        self.proxy.initialized = True
        self.proxy.request = Mock(side_effect=AssertionError('blocking discovery'))
        self.send_server({'method': 'thread/status/changed', 'params': {
            'threadId': 'child', 'status': {'type': 'idle'},
        }})
        self.proxy.inspect_idle()
        request = json.loads(self.server.send.call_args.args[0])

        self.send_client({'id': 42, 'method': 'thread/read', 'params': {'threadId': 'thread'}})

        self.assertEqual(json.loads(self.server.send.call_args.args[0])['id'], 42)
        self.proxy.pending[request['id']].put({'result': {'thread': {
            'id': 'child', 'ephemeral': False, 'parentThreadId': 'thread',
        }}})
        self.proxy.inspect_idle()
        self.assertEqual(self.proxy.idle.threads['child']['parent'], 'thread')

    def test_pending_request_limit_releases_capacity_after_responses(self):
        """양방향 요청이 상한에 닿으면 거절하고 응답 또는 승인 해결 뒤에는 용량을 돌려준다."""
        self.proxy.request_limit = 2
        self.send_client({'id': 1, 'method': 'thread/read', 'params': {}})
        self.send_server({'id': 2, 'method': 'fixture/approval', 'params': {}})

        with self.assertRaises(OSError):
            self.send_client({'id': 3, 'method': 'thread/read', 'params': {}})
        self.send_server({'method': 'serverRequest/resolved', 'params': {'requestId': 2}})
        self.send_client({'id': 3, 'method': 'thread/read', 'params': {}})
        self.send_server({'id': 1, 'result': {}})
        self.send_client({'id': 4, 'method': 'thread/read', 'params': {}})

        self.assertEqual(set(self.proxy.client_requests), {3, 4})

    def test_pending_request_byte_limit_is_independent_of_count(self):
        """소수의 큰 요청도 응답 전 보유량 상한을 넘으면 전달하지 않는다."""
        self.proxy.request_byte_limit = 100
        self.proxy.forward_client({'id': 1, 'method': 'fixture', 'params': {}}, b'x' * 60)

        with self.assertRaises(OSError):
            self.proxy.forward_client({'id': 2, 'method': 'fixture', 'params': {}}, b'x' * 60)

        self.assertEqual(self.server.send.call_count, 1)

    def setUp(self):
        self.client, self.server = Mock(), Mock()
        self.proxy = Proxy(self.client, self.server, delay=10)
        self.proxy.idle.track({"thread": {"id": "thread", "ephemeral": False}}, {}, now=0)

    def send_client(self, message):
        self.proxy.forward_client(message, json.dumps(message).encode())

    def send_server(self, message):
        self.proxy.forward_server(message, json.dumps(message).encode())

    def test_user_request_is_forwarded_while_idle_query_has_no_reply(self):
        """idle RPC가 응답하지 않아도 사용자 요청은 즉시 전달한다."""
        client, server = Transport(), Transport()
        proxy = Proxy(client, server, 0)
        proxy.initialized = True
        proxy.idle.track({'thread': {'id': 'thread', 'ephemeral': False}}, {}, 0)
        worker = threading.Thread(target=proxy.run, daemon=True)
        worker.start()
        try:
            query = json.loads(server.outgoing.get(timeout=3))
            self.assertEqual(query['method'], 'thread/list')
            payload = b'{"id":42,"method":"thread/read","params":{"threadId":"thread"}}'
            client.incoming.put(payload)

            forwarded = server.outgoing.get(timeout=1)

            self.assertEqual(forwarded, payload)
        finally:
            proxy.close()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())

    def test_forwarding_parses_each_payload_only_once(self):
        """원문 bytes를 보존하며 전달용 메시지를 한 번만 파싱한다."""
        client, server = Transport(), Transport()
        proxy = Proxy(client, server, 900)
        payload = b'{"method":"fixture","params":{"data":"unchanged"}}'
        with patch('idle.json.loads', wraps=json.loads) as decode:
            worker = threading.Thread(target=proxy.run, daemon=True)
            worker.start()
            try:
                client.incoming.put(payload)

                forwarded = server.outgoing.get(timeout=2)

                self.assertEqual(forwarded, payload)
                self.assertEqual(decode.call_count, 1)
            finally:
                proxy.close()
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())

    def test_routing_keeps_resume_configuration_and_blocks_dynamic_tools(self):
        """본문을 queue에서 제외해도 resume 설정과 복원 불가능한 동적 도구 표시는 유지한다."""
        request = {'id': 10, 'method': 'thread/start', 'params': {
            'cwd': '/fixture', 'config': {'permission': 'original'}, 'dynamicTools': [{'name': 'tool'}],
        }}
        response = {'id': 10, 'result': {'thread': {'id': 'new', 'ephemeral': False, 'parentThreadId': None}}}
        for side, message in (('client', request), ('server', response)):
            raw = json.dumps(message).encode()
            self.proxy.receive(side, raw)
            _, payload, route = self.proxy.events.get_nowait()
            if side == 'client':
                self.proxy.forward_client(route, payload)
            else:
                self.proxy.forward_server(route, payload)

        saved = self.proxy.idle.threads['new']
        self.assertEqual(saved['params']['config'], {'permission': 'original'})
        self.assertEqual(saved['params']['cwd'], '/fixture')
        self.assertTrue(saved['blocked'])

    def reach_unsubscribe(self):
        self.proxy.initialized = True
        server = Server()
        for _ in range(20):
            self.proxy.inspect_idle()
            request = json.loads(self.server.send.call_args.args[0])
            if request['method'] == 'thread/unsubscribe':
                return self.proxy.pending[request['id']]
            self.proxy.pending[request['id']].put({'result': server.request(request['method'], request['params'])})
        self.fail('unsubscribe was not requested')

    def test_rejected_unsubscribe_does_not_hide_real_thread_closed(self):
        """명시적으로 거절된 회수는 sleeping을 되돌려 진짜 종료 알림을 보존한다."""
        response = self.reach_unsubscribe()
        response.put({'error': {'message': 'rejected'}})

        self.proxy.inspect_idle()

        self.assertNotIn('thread', self.proxy.idle.sleeping)
        payload = b'{"method":"thread/closed","params":{"threadId":"thread"}}'
        self.proxy.receive('server', payload)
        self.assertEqual(self.proxy.events.get_nowait()[1], payload)

    def test_timed_out_unsubscribe_resumes_before_next_input(self):
        """회수 응답이 유실되면 실제 회수 여부를 모르므로 다음 입력 전에 resume한다."""
        self.reach_unsubscribe()
        request_id = self.proxy.check_id
        self.proxy.check_deadline = 0

        self.proxy.inspect_idle()

        self.assertIn('thread', self.proxy.idle.sleeping)
        self.proxy.receive('server', json.dumps({'id': request_id, 'result': {}}).encode())
        self.assertTrue(self.proxy.events.empty())
        self.proxy.idle.request = Mock(return_value={})
        self.send_client({'id': 99, 'method': 'turn/start', 'params': {'threadId': 'thread'}})
        self.proxy.idle.request.assert_called_once_with('thread/resume', {'threadId': 'thread', 'excludeTurns': True})

    def test_slow_consumer_disconnects_at_byte_budget_without_blocking_reader(self):
        """소비자가 멈춰도 byte 상한에서 종료하며 내부 RPC reader를 막지 않는다."""
        self.proxy.events.max_bytes = 100
        payload = json.dumps({'method': 'fixture', 'params': {'data': 'x' * 35}}).encode()
        self.server.messages.return_value = iter([payload, payload])

        self.proxy.read('server', self.server)

        self.client.close.assert_called()
        self.server.close.assert_called()
        self.assertLessEqual(self.proxy.events.queued_bytes, 100)

    def test_forwarded_bytes_release_queue_budget_and_internal_replies_bypass_it(self):
        """전달한 payload의 예산을 반환하고 내부 응답은 가득 찬 전달 queue를 우회한다."""
        self.proxy.events.max_bytes = 100
        payload = b'{"method":"fixture","params":{}}'
        self.proxy.receive('server', payload)
        self.proxy.events.get_nowait()
        self.assertEqual(self.proxy.events.queued_bytes, 0)
        response = queue.Queue(maxsize=1)
        self.proxy.pending['internal'] = response
        self.proxy.events.max_bytes = 1

        self.proxy.receive('server', b'{"id":"internal","result":{}}')

        self.assertEqual(response.get_nowait()['result'], {})

    def test_failed_wake_rejects_before_forwarding_user_input(self):
        """resume 실패는 제출 전 거절로 반환하여 TUI가 입력을 composer에 복원하게 한다."""
        self.proxy.idle.sleeping.add("thread")
        self.proxy.idle.request = Mock(side_effect=UsageUnavailable("fixture"))

        self.send_client({"id": 3, "method": "turn/start", "params": {"threadId": "thread"}})

        self.server.send.assert_not_called()
        self.assertEqual(json.loads(self.client.send.call_args.args[0])["error"]["code"], -32600)

    def test_settings_changed_by_another_connection_keep_current_runtime(self):
        """실제로 변경된 sticky 설정은 이전 start params로 덮어쓰지 않는다."""
        self.send_server({"method": "thread/settings/updated", "params": {"threadId": "thread"}})

        self.assertTrue(self.proxy.idle.threads["thread"]["blocked"])

    def test_resolved_server_request_does_not_keep_connection_busy(self):
        """다른 연결이 해결한 승인도 pending 목록에서 제거한다."""
        self.send_server({"id": 8, "method": "item/commandExecution/requestApproval", "params": {}})

        self.send_server({"method": "serverRequest/resolved", "params": {"requestId": 8}})

        self.assertFalse(self.proxy.server_requests)

    def test_owner_restart_reattaches_sleeping_child_before_unload_grace_expires(self):
        """owner가 다시 실행한 자식은 status 알림에서 실제로 resume하여 후속 background 작업을 보존한다."""
        self.proxy.idle.track({"thread": {"id": "child", "ephemeral": False, "parentThreadId": "thread"}}, {}, now=0)
        self.proxy.idle.sleeping.add("child")
        self.proxy.initialized = True
        self.proxy.idle.request = Mock(side_effect=AssertionError('blocking wake'))

        self.send_server({"method": "thread/status/changed", "params": {
            "threadId": "child", "status": {"type": "active"},
        }})

        self.proxy.inspect_idle()
        request = json.loads(self.server.send.call_args.args[0])
        self.assertEqual(request['method'], 'thread/resume')
        self.assertEqual(request['params'], {'threadId': 'child', 'excludeTurns': True})
        self.send_client({'id': 40, 'method': 'turn/start', 'params': {'threadId': 'child'}})
        self.send_client({'id': 41, 'method': 'thread/read', 'params': {'threadId': 'thread'}})
        self.assertEqual(json.loads(self.server.send.call_args.args[0])['id'], 41)
        self.send_server({'method': 'turn/started', 'params': {'threadId': 'child'}})
        self.send_client({'id': 42, 'method': 'turn/steer', 'params': {'threadId': 'child'}})

        self.proxy.pending[request['id']].put({'result': {}})
        self.proxy.inspect_idle()

        self.assertNotIn("child", self.proxy.idle.sleeping)
        order = [json.loads(call.args[0]).get('id') for call in self.server.send.call_args_list]
        self.assertEqual([key for key in order if key in (40, 42)], [40, 42])

    def test_known_child_wake_keeps_the_live_forwarder_responsive(self):
        """자식 resume 응답이 없어도 실제 전달 루프는 다른 대화의 입력을 전달한다."""
        client, server = Transport(), Transport()
        proxy = Proxy(client, server, 900)
        proxy.initialized = True
        proxy.idle.track({'thread': {'id': 'child', 'ephemeral': False,
                                    'parentThreadId': 'parent'}}, {}, 0)
        proxy.idle.sleeping.add('child')
        worker = threading.Thread(target=proxy.run, daemon=True)
        worker.start()
        try:
            server.incoming.put(json.dumps({'method': 'thread/status/changed', 'params': {
                'threadId': 'child', 'status': {'type': 'active'}}}).encode())
            resume = json.loads(server.outgoing.get(timeout=2))
            self.assertEqual(resume['method'], 'thread/resume')
            payload = b'{"id":42,"method":"turn/start","params":{"threadId":"other"}}'
            client.incoming.put(payload)
            self.assertEqual(server.outgoing.get(timeout=1), payload)
        finally:
            proxy.close()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())

    def test_failed_auto_wake_reports_unsent_input_and_retries_only_resume(self):
        """자동 재구독 실패는 보류한 입력에 오류를 돌려주며 입력 자체를 재전송하지 않는다."""
        self.proxy.initialized = True
        self.proxy.idle.track({'thread': {'id': 'child', 'ephemeral': False,
                                        'parentThreadId': 'thread'}}, {}, 0)
        self.proxy.idle.sleeping.add('child')
        self.send_server({'method': 'thread/status/changed', 'params': {
            'threadId': 'child', 'status': {'type': 'active'}}})
        self.proxy.inspect_idle()
        self.send_client({'id': 42, 'method': 'turn/start', 'params': {'threadId': 'child'}})
        self.proxy.check_deadline = 0

        self.proxy.inspect_idle()

        response = json.loads(self.client.send.call_args.args[0])
        self.assertEqual(response['id'], 42)
        self.assertIn('error', response)
        self.assertTrue(self.proxy.deferred.empty())
        self.proxy.wakeups['child'] = 0
        self.proxy.inspect_idle()
        request = json.loads(self.server.send.call_args.args[0])
        self.assertEqual(request['method'], 'thread/resume')
        self.proxy.pending[request['id']].put({'result': {}})
        self.proxy.inspect_idle()
        self.assertNotIn(42, [json.loads(call.args[0]).get('id')
                              for call in self.server.send.call_args_list])

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
