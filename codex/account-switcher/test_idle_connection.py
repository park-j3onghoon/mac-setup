"""실제 Unix WebSocket으로 중계기 단절·재접속·종료를 검증한다."""

import json
import errno
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
from unittest.mock import Mock, patch

from idle import ClientSocket, serve
from unix_ws import UnixWebSocket


class ProxyConnectionTest(unittest.TestCase):
    def test_malformed_handshake_rejects_only_that_connection(self):
        """필수 헤더가 빠진 연결 뒤에도 같은 중계기 주소로 정상 연결을 받는다."""
        with socket.socket(socket.AF_UNIX) as invalid:
            invalid.settimeout(3)
            invalid.connect(str(self.endpoint))
            invalid.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n')
            self.assertEqual(invalid.recv(1), b'')

        client, server = self.connect()

        self.exchange(client, server, {'id': 1, 'method': 'initialize', 'params': {}}, {})

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
        while self.endpoint.parent.exists() and time.monotonic() < deadline:
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
        status = json.loads(self.endpoint.with_suffix('.json').read_text())
        self.assertEqual(status['owner_pid'], self.owner.pid)
        self.assertGreater(status['pid'], 1)
        self.assertEqual(len(status['source_revision']), 64)
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

    def test_owner_exit_with_half_finished_upgrade_removes_endpoint(self):
        with socket.socket(socket.AF_UNIX) as partial:
            partial.connect(str(self.endpoint))
            partial.sendall(b'GET / HTTP/1.1\r\n')
            self.stop_owner()
            self.assert_endpoint_removed()

    def test_owner_exit_while_upstream_upgrade_is_pending(self):
        client = UnixWebSocket(self.endpoint)
        self.addCleanup(client.close)
        with self.listener.accept()[0] as waiting:
            self.assertTrue(waiting.recv(4096).startswith(b'GET '))
            self.stop_owner()
            self.assert_endpoint_removed()

    def test_failed_replacement_preserves_original_listener_and_status(self):
        original = self.endpoint.with_suffix('.json').read_bytes()
        attempt = subprocess.run([sys.executable, str(Path(__file__).with_name('idle.py')),
                                  str(self.upstream), str(self.endpoint), '900', str(self.owner.pid)],
                                 capture_output=True, timeout=5)
        self.assertNotEqual(attempt.returncode, 0)
        self.assertEqual(self.endpoint.with_suffix('.json').read_bytes(), original)
        client, server = self.connect()
        self.exchange(client, server, {'id': 7, 'method': 'initialize', 'params': {}}, {})

    def test_long_tmpdir_uses_short_private_socket(self):
        long_directory = Path(self.directory.name) / ('x' * 100)
        long_directory.mkdir()
        with subprocess.Popen(
            [sys.executable, '-u', '-c', 'from idle import start_proxy; import sys; '
             'print(start_proxy(sys.argv[1],900),flush=True); sys.stdin.read()', str(self.upstream)],
            cwd=Path(__file__).parent, env=dict(os.environ, TMPDIR=str(long_directory)),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) as owner:
            self.assertTrue(select.select([owner.stdout], [], [], 10)[0])
            endpoint = Path(owner.stdout.readline().strip())
            self.assertTrue(endpoint.is_socket())
            self.assertLess(len(os.fsencode(endpoint)), 104)
            self.assertEqual(endpoint.parent.stat().st_mode & 0o777, 0o700)
            owner.stdin.close()
            owner.wait(timeout=5)

    def test_temporary_descriptor_exhaustion_retries_accept(self):
        endpoint = Path(self.directory.name) / 'recover' / 'tui.sock'
        endpoint.parent.mkdir()
        listener, owner, connection = Mock(), Mock(), Mock()
        listener.bind.side_effect = lambda name: Path(name).touch()
        listener.accept.side_effect = [OSError(errno.ENFILE, 'temporary'), (connection, None)]
        owner.control.side_effect = [[], [], [], [object()]]
        with (patch('idle.socket.socket', return_value=listener), patch('idle.select.kqueue', return_value=owner),
              patch('idle.time.sleep'), patch('idle.ClientSocket'), patch('idle.UnixWebSocket'), patch('idle.Proxy') as proxy):
            serve(self.upstream, endpoint, 900, os.getpid())
        self.assertEqual(listener.accept.call_count, 2)
        proxy.return_value.run.assert_called_once()

    def test_replacement_follows_existing_terminal_instead_of_its_spawner(self):
        """별도 프로세스에서 띄운 교체용 proxy도 지정한 terminal의 생존 기간을 따른다."""
        directory = Path(self.directory.name) / 'replacement'
        directory.mkdir()
        endpoint = directory / 'tui.sock'
        replacement = subprocess.Popen([sys.executable, str(Path(__file__).with_name('idle.py')),
                                       str(self.upstream), str(endpoint), '900', str(self.owner.pid)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 3
            while not endpoint.exists() and replacement.poll() is None and time.monotonic() < deadline:
                threading.Event().wait(.01)
            self.assertTrue(endpoint.exists(), 'replacement rejected an existing owner')
            client = UnixWebSocket(endpoint)
            self.addCleanup(client.close)
            client.socket.settimeout(3)
            server = ClientSocket(self.listener.accept()[0])
            self.addCleanup(server.close)
            self.exchange(client, server, {'id': 1, 'method': 'initialize', 'params': {}}, {})
            status = json.loads(endpoint.with_suffix('.json').read_text())
            self.assertTrue(status['connected'])
            self.assertEqual(status['connections'], 1)
            self.stop_owner()

            replacement.wait(timeout=4)

            self.assertFalse(endpoint.exists())
            self.assert_disconnected(client)
        finally:
            if replacement.poll() is None:
                replacement.terminate()
                replacement.wait(timeout=3)
            replacement.stderr.close()

    def test_forwarding_preserves_original_json_bytes_in_both_directions(self):
        """계정·유휴 정책이 내용을 바꾸지 않는 요청과 응답은 원문 그대로 전달한다."""
        client, server = self.connect()
        request = b'{ "id": 7, "method": "fixture/echo", "params": {"text": "\\uac00"} }'
        response = b'{ "id": 7, "result": {"text": "\\uac00"} }'

        client.send(request)
        received_request = next(server.messages())
        server.send(response)
        received_response = next(client.messages())

        self.assertEqual(received_request, request)
        self.assertEqual(received_response, response)


if __name__ == "__main__":
    unittest.main()
