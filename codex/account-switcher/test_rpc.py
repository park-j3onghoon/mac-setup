import json
import queue
import time
import unittest
from unittest.mock import patch

from policy import UsageUnavailable
from rpc import Rpc


class Socket:
    """Answers initialize and hands the reader whatever a test queues."""

    def __init__(self, path):
        self.sent = []
        self.incoming = queue.Queue()

    def send(self, data):
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
        pass


def connect():
    with patch("rpc.UnixWebSocket", Socket):
        client = Rpc(None, None, "/auto.sock")
    return client, client.websocket


class RpcTest(unittest.TestCase):
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
