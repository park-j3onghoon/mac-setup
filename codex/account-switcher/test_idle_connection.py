"""실제 Unix WebSocket으로 중계기 단절·재접속·종료를 검증한다."""

import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from idle import ClientSocket
from unix_ws import UnixWebSocket


class ProxyConnectionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="idle-test-", dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.upstream = Path(self.directory.name) / "server.sock"
        self.listen()
        self.owner = subprocess.Popen(
            [sys.executable, "-u", "-c",
             "import os, sys; from idle import start_proxy; "
             "endpoint = start_proxy(sys.argv[1], 900); "
             "os.execv(sys.executable, [sys.executable, '-u', '-c', "
             "'import sys; print(sys.argv[1], flush=True); sys.stdin.read()', str(endpoint)])",
             str(self.upstream)],
            cwd=Path(__file__).parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
            env=dict(os.environ, TMPDIR=self.directory.name),
        )
        self.addCleanup(self.stop_owner)
        self.assertTrue(select.select([self.owner.stdout], [], [], 10)[0], "proxy startup")
        self.endpoint = Path(self.owner.stdout.readline().strip())
        self.assertTrue(self.endpoint.is_socket())

    def listen(self):
        self.listener = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.listener.close)
        self.listener.bind(str(self.upstream))
        self.listener.listen(1)
        self.listener.settimeout(3)

    def stop_owner(self):
        if self.owner.poll() is None:
            self.owner.stdin.close()
            self.owner.wait(timeout=5)
        self.owner.stdout.close()
        self.owner.stderr.close()

    def connect(self):
        client = UnixWebSocket(self.endpoint)
        self.addCleanup(client.close)
        client.socket.settimeout(3)
        server = ClientSocket(self.listener.accept()[0])
        self.addCleanup(server.close)
        server.socket.settimeout(3)
        return client, server

    def exchange(self, client, server, request, result):
        client.send(json.dumps(request).encode())
        received = json.loads(next(server.messages()))
        self.assertEqual(received, request)
        response = {"id": request["id"], "result": result}
        server.send(json.dumps(response).encode())
        self.assertEqual(json.loads(next(client.messages())), response)

    def assert_disconnected(self, connection):
        with self.assertRaises(EOFError):
            next(connection.messages())

    def assert_endpoint_removed(self):
        deadline = time.monotonic() + 5
        while self.endpoint.exists() and time.monotonic() < deadline:
            threading.Event().wait(.02)
        self.assertFalse(self.endpoint.exists(), "proxy outlived its terminal")
        self.assertFalse(self.endpoint.parent.exists())

    def test_server_restart_resumes_without_replaying_uncertain_submission(self):
        """서버 단절·접속 실패 뒤 같은 주소로 복구하고 전달한 입력을 재전송하지 않는다."""
        client, server = self.connect()
        self.exchange(client, server, {"id": 1, "method": "initialize", "params": {}}, {})
        submitted = {"id": 2, "method": "turn/start", "params": {
            "threadId": "saved-thread", "input": [{"type": "text", "text": "already sent"}],
        }}
        client.send(json.dumps(submitted).encode())
        self.assertEqual(json.loads(next(server.messages())), submitted)
        server.close()
        self.listener.close()
        self.upstream.unlink()
        self.assert_disconnected(client)

        unavailable = UnixWebSocket(self.endpoint)
        self.addCleanup(unavailable.close)
        unavailable.socket.settimeout(3)
        self.assert_disconnected(unavailable)
        self.listen()
        client, server = self.connect()

        # A fresh initialize must be the first message, even when the old request had no reply.
        self.exchange(client, server, {"id": 1, "method": "initialize", "params": {}}, {})
        self.exchange(client, server, {"id": 2, "method": "thread/resume", "params": {
            "threadId": "saved-thread", "config": {"shell_environment_policy.set.TAB": "same"},
        }}, {"thread": {"id": "saved-thread", "ephemeral": False, "parentThreadId": None}})
        self.exchange(client, server, {"id": 3, "method": "turn/start", "params": {
            "threadId": "saved-thread", "input": [{"type": "text", "text": "new input"}],
        }}, {"turn": {"id": "new-turn"}})

    def test_client_reconnects_repeatedly_and_owner_exit_removes_endpoint(self):
        """터미널의 반복 재접속을 받되 터미널 종료 후에는 중계 주소를 회수한다."""
        for _ in range(3):
            client, server = self.connect()
            self.exchange(client, server, {"id": 1, "method": "initialize", "params": {}}, {})

            client.close()

            self.assert_disconnected(server)
        self.stop_owner()

        self.assert_endpoint_removed()

    def test_owner_exit_before_first_connection_removes_endpoint(self):
        """Codex 실행 자체가 실패해 첫 접속이 없어도 고아 중계기를 남기지 않는다."""
        self.stop_owner()

        self.assert_endpoint_removed()


if __name__ == "__main__":
    unittest.main()
