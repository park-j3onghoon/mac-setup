import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from idle import Proxy, diff_route, routing
from policy import UsageUnavailable, utilization
from profiles import Profile
from rpc import RpcNotSent
from runtime import Runtime
from state import load, poll_delay, record
from test_rpc import connect


class RecoveryContract(unittest.TestCase):
    def test_stale_pct_is_not_used_for_retry_but_known_reset_is(self):
        old = {'company': {'used_percent': 7, 'windows': {'primary': {'resets_at': 105}}}}
        self.assertEqual(poll_delay({}, 'company', now=100, history=old), 6)
        self.assertEqual(poll_delay({}, 'company', now=200, history=old), 60)

    def test_usage_permission_and_missing_window_survive_partial_responses(self):
        before = {'ordinary_usage_allowed': False, 'windows': {'secondary': {'resets_at': 100}}}
        middle = record(before, {'observed_at': 105, 'windows': {}, 'used_percent': 2})
        self.assertEqual(middle['used_percent'], 100)
        after = record(middle, {'observed_at': 110, 'ordinary_usage_allowed': True,
                                'windows': {'secondary': {'resets_at': 200}}, 'used_percent': 3})
        self.assertEqual(after['windows']['secondary']['previous_resets_at'], 100)
        self.assertEqual(after['used_percent'], 3)
        with self.assertRaises(UsageUnavailable):
            utilization({'rateLimits': {'limitId': 'code-review', 'primary': {'usedPercent': 0}}})

    def test_refresh_success_with_expired_token_backs_off(self):
        get = lambda _: {'expires': 0, 'chatgptAccountId': 'one', 'accessToken': 'test'}
        with patch('profiles.credentials', side_effect=get):
            profile = Profile('company', Path('/fixture'))
            profile.client = Mock(closed=False)
            for _ in range(2):
                with self.assertRaises(UsageUnavailable):
                    profile.tokens()
            profile.client.request.assert_called_once()

    def test_non_object_state_is_recoverable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state.json'
            path.write_text('null')
            self.assertEqual(load(path), {})

    def test_full_duplex_rpc_cancels_cooperative_handler(self):
        rpc, transport = connect()
        entered, ended = threading.Event(), threading.Event()
        def handler(method, params, *, cancel):
            entered.set()
            if cancel.wait(2):
                ended.set()
            return {}
        rpc.handler = handler
        transport.incoming.put(b'{"id":99,"method":"fixture","params":{}}')
        self.assertTrue(entered.wait(1))
        rpc.close()
        self.assertTrue(ended.is_set())

    def test_partial_send_does_not_become_a_definite_rejection(self):
        rpc, _ = connect()
        self.addCleanup(rpc.close)
        for count in (0, 8):
            with self.subTest(count=count):
                err = ValueError('closed during write')
                err.bytes_written = count
                rpc.closed = False
                with patch.object(rpc.websocket, 'send', side_effect=err), self.assertRaises(UsageUnavailable) as result:
                    rpc.send({'id': 1})
                self.assertEqual(isinstance(result.exception, RpcNotSent), count == 0)

    def test_large_diff_routes_without_decoding_or_modifying_the_payload(self):
        payload = json.dumps({'method': 'turn/diff/updated',
                              'params': {'threadId': 'one', 'diff': 'x"y\\z' * 20000}}).encode()
        proxy = Proxy(Mock(), Mock(), 60)
        with patch('idle.json.loads', side_effect=AssertionError('decoded large diff')):
            proxy.receive('server', payload)
        side, forwarded, tag = proxy.events.get_nowait()
        self.assertEqual((side, tag['params']), ('server', {'threadId': 'one'}))
        self.assertIs(forwarded, payload)
        self.assertIsNone(diff_route(payload[:-1] + b',"id":1}'))

    def test_explicit_empty_environment_and_late_resume(self):
        proxy = Proxy(Mock(), Mock(), 60)
        def send(side, message):
            getattr(proxy, 'forward_' + side)(routing(message, side), json.dumps(message).encode())
        result = {'thread': {'id': 'one', 'ephemeral': False}}
        send('client', {'id': 1, 'method': 'thread/start', 'params': {'environments': []}})
        send('server', {'id': 1, 'result': result})
        self.assertTrue(proxy.idle.threads['one']['blocked'])
        proxy.idle.sleeping.add('one')
        send('client', {'id': 2, 'method': 'thread/resume', 'params': {'threadId': 'one'}})
        send('server', {'method': 'thread/deleted', 'params': {'threadId': 'one'}})
        send('server', {'id': 2, 'result': result})
        self.assertNotIn('one', proxy.idle.threads)

    def test_receipt_is_written_before_turn_start_and_survives_an_uncertain_send(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Runtime({}, home=temp)
            runtime.continuation_path = Path(temp) / 'receipts'
            client = Mock()
            def respond(method, params):
                if method == 'thread/read':
                    return {'thread': {'status': {'type': 'idle'}}}
                if method == 'thread/turns/list':
                    return {'data': [{'id': 'failed', 'status': 'failed',
                                      'error': {'codexErrorInfo': 'usageLimitExceeded'}}]}
                if method == 'thread/queue/list':
                    return {'data': []}
                self.assertEqual(load(runtime.continuation_path), {'one': 'failed'})
                raise UsageUnavailable('reply lost')
            client.request.side_effect = respond
            with self.assertRaises(UsageUnavailable):
                runtime.continue_thread('one', client)
            self.assertEqual(load(runtime.continuation_path), {'one': 'failed'})
