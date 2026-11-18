import json
import queue
import socket
import threading
import time
import unittest
from unittest.mock import patch

from policy import UsageUnavailable
from rpc import Rpc
from unix_ws import UnixWebSocket


class Socket:
    """Answers initialize and hands the reader whatever a test queues."""

    def __init__(self, path):
        self.sent = []
        self.incoming = queue.Queue()

    def send(self, data, deadline=None):
        message = json.loads(data)
        self.sent.append(message)
        if message.get("method") == "initialize":
            self.incoming.put(json.dumps({"id": message["id"], "result": {}}).encode())

    def messages(self):
        while True:
            item = self.incoming.get()
            if isinstance(item, Exception):
                raise item
            yield item

    def close(self):
        self.incoming.put(EOFError())


def connect():
    with patch("rpc.UnixWebSocket", Socket):
        client = Rpc(None, None, "/auto.sock")
    return client, client.websocket


class RpcTest(unittest.TestCase):
    def test_blocked_write_obeys_request_deadline_without_holding_response_lock(self):
        """상대가 읽지 않아도 요청이 제한시간 안에 실패하고 응답 잠금은 점유하지 않는다."""
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        client, original = connect()
        self.addCleanup(client.close)
        self.addCleanup(original.close)
        transport = UnixWebSocket.__new__(UnixWebSocket)
        transport.socket, transport.lock = left, threading.Lock()
        client.websocket = transport
        finished = threading.Event()
        errors = []

        def request():
            try:
                client.request('fixture', {'data': 'x' * (2 << 20)}, timeout=.05)
            except UsageUnavailable as error:
                errors.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=request, daemon=True)
        worker.start()
        completed = finished.wait(.5)
        acquired = client.lock.acquire(timeout=.05)
        if acquired:
            client.lock.release()
        right.close()
        worker.join(2)

        self.assertTrue(completed)
        self.assertTrue(acquired)
        self.assertEqual(len(errors), 1)

    def test_reader_failure_releases_the_socket_without_owner_cleanup(self):
        """reader가 실패하면 다음 계정 조회를 기다리지 않고 실제 descriptor를 회수한다."""
        left, right = socket.socketpair()
        transport = Socket(None)
        transport.close = left.close
        try:
            with patch("rpc.UnixWebSocket", return_value=transport):
                client = Rpc(None, None, "/fixture.sock")

            transport.incoming.put(OSError("fixture read failure"))
            client.reader.join(timeout=2)

            self.assertEqual(left.fileno(), -1)
        finally:
            left.close()
            right.close()

    def test_requests_fail_at_once_after_the_reader_stops(self):
        """수신이 멈춘 연결은 닫힌 것으로 보고, 다음 요청을 시간 초과까지 기다리지 않고 바로 실패시킨다."""
        client, socket = connect()

        socket.incoming.put(OSError("Oversized Codex socket message"))
        client.reader.join(timeout=5)
        started = time.monotonic()
        with self.assertRaises(UsageUnavailable):
            client.request("thread/loaded/list", timeout=30)

        self.assertTrue(client.closed)
        self.assertLess(time.monotonic() - started, 1)

    def test_connection_declines_thread_event_notifications(self):
        """감독 연결은 알림을 읽지 않으므로, 하위 에이전트의 턴 전체 diff 같은 큰 알림을 받지 않겠다고 밝힌다."""
        client, socket = connect()

        declined = socket.sent[0]["params"]["capabilities"]["optOutNotificationMethods"]

        self.assertIn("turn/diff/updated", declined)
        self.assertIn("item/completed", declined)
        client.close()


if __name__ == "__main__":
    unittest.main()
