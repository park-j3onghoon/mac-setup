"""터미널의 입력·출력을 유지한 채 자신의 유휴 thread 구독만 반환한다."""

import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from policy import UsageUnavailable
from state import save
from unix_ws import UnixWebSocket


RESUME_FIELDS = {"model", "modelProvider", "serviceTier", "cwd", "runtimeWorkspaceRoots",
                 "approvalPolicy", "approvalsReviewer", "sandbox", "permissions", "config",
                 "baseInstructions", "developerInstructions", "personality"}
READ_METHODS = {"thread/read", "thread/turns/list", "thread/items/list", "thread/goal/get",
                "thread/queue/list", "thread/backgroundTerminals/list"}
SOURCE_REVISION = hashlib.sha256(b''.join(
    Path(__file__).with_name(name).read_bytes() for name in ('idle.py', 'unix_ws.py')
)).hexdigest()


class IdleThreads:
    def __init__(self, request, delay, can_park=lambda: True):
        self.request, self.delay = request, delay
        self.can_park = can_park
        self.threads = {}
        self.sleeping = set()

    def track(self, result, params, now):
        thread = result["thread"]
        blocked = (thread["ephemeral"] or any(params.get(key) for key in
                   ("dynamicTools", "selectedCapabilityRoots", "environments", "history")))
        self.threads[thread["id"]] = {
            "params": {key: value for key, value in params.items() if key in RESUME_FIELDS},
            "last_activity": now, "blocked": blocked,
            "parent": thread.get("parentThreadId"),
        }
        parent = thread.get("parentThreadId")
        if parent:
            self.preserve(parent)
        if any(saved["parent"] == thread["id"] for saved in self.threads.values()):
            self.preserve(thread["id"])

    def preserve(self, thread_id):
        if thread_id in self.threads:
            self.threads[thread_id]["blocked"] = True

    def touch(self, thread_id, now):
        if thread_id in self.threads:
            self.threads[thread_id]["last_activity"] = now

    def park(self, now):
        checks = self.inspect(now)
        result = None
        try:
            while True:
                method, params = checks.send(result)
                result = self.request(method, params)
        except StopIteration:
            pass
        finally:
            checks.close()

    def inspect(self, now):
        ancestors = None
        for thread_id, saved in list(self.threads.items()):
            activity = saved['last_activity']
            was_sleeping = thread_id in self.sleeping
            if (saved["blocked"] or (was_sleeping and not saved["parent"])
                    or now - saved["last_activity"] < self.delay):
                continue
            # root runtime은 내려간 자식의 mailbox·environment도 소유한다 (0.169.0).
            children = yield "thread/list", {"parentThreadId": thread_id, "limit": 1}
            if children["data"]:
                saved["blocked"] = True
                continue
            # 영속 목록에 없는 ephemeral 자식도 보존한다.
            if ancestors is None:
                ancestors, parents = set(), {}
                cursor = None
                while True:
                    loaded = yield 'thread/loaded/list', {'cursor': cursor}
                    for other_id in loaded['data']:
                        seen = {other_id}
                        while other_id:
                            if other_id not in parents:
                                other = (yield 'thread/read', {'threadId': other_id})['thread']
                                parents[other_id] = other.get('parentThreadId')
                            other_id = parents[other_id]
                            if not other_id or other_id in seen:
                                break
                            ancestors.add(other_id)
                            seen.add(other_id)
                    cursor = loaded.get('nextCursor')
                    if not cursor:
                        break
            if thread_id in ancestors:
                saved["blocked"] = True
                continue
            params = {"threadId": thread_id}
            thread = (yield "thread/read", params)["thread"]
            if thread["status"]["type"] != "idle" or thread["ephemeral"]:
                saved["last_activity"] = now
                continue
            terminals = yield "thread/backgroundTerminals/list", params
            goal = (yield "thread/goal/get", params)["goal"]
            queued = yield "thread/queue/list", params
            turns = yield "thread/turns/list", {
                **params, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded",
            }
            if (terminals["data"] or queued["data"] or not turns["data"]
                    or (goal and goal["status"] != "complete")):
                saved["last_activity"] = now
                continue
            if not self.can_park():
                return
            if (self.threads.get(thread_id) is not saved or saved['blocked']
                    or saved['last_activity'] != activity):
                continue
            # thread/closed 종료 알림보다 먼저 표시한다. TUI는 이 알림을 받으면 종료한다.
            self.sleeping.add(thread_id)
            try:
                yield "thread/unsubscribe", params
                if saved['last_activity'] == activity:
                    saved["last_activity"] = now
            except Exception:
                if not was_sleeping:
                    self.sleeping.discard(thread_id)
                raise

    def wake(self, thread_id, now):
        if thread_id in self.sleeping:
            parent = self.threads[thread_id]["parent"]
            if parent in self.threads:
                self.wake(parent, now)
            self.request("thread/resume", {
                **self.threads[thread_id]["params"], "threadId": thread_id, "excludeTurns": True,
            })
            self.sleeping.remove(thread_id)
        self.touch(thread_id, now)


class ClientSocket(UnixWebSocket):
    # 공식 TUI의 remote WebSocket 한도와 같다 (0.169.0 remote.rs).
    message_limit = 128 << 20

    def __init__(self, connection):
        self.socket, self.buffer, self.lock = connection, b"", threading.Lock()
        connection.settimeout(10)
        while b"\r\n\r\n" not in self.buffer:
            block = connection.recv(4096)
            if not block or len(self.buffer) > 16384:
                raise OSError("Invalid local TUI handshake")
            self.buffer += block
        header, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        headers = {name.lower().strip(): value.strip() for name, value in
                   (line.split(":", 1) for line in header.decode("ascii").split("\r\n")[1:] if ":" in line)}
        accepted = base64.b64encode(hashlib.sha1(
            (headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        connection.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                            "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accepted + "\r\n\r\n").encode())
        connection.settimeout(None)

    def send_frame(self, opcode, data):
        length = len(data)
        if length < 126:
            header = bytes([0x80 | opcode, length])
        elif length < 65536:
            header = bytes([0x80 | opcode, 126]) + struct.pack("!H", length)
        else:
            header = bytes([0x80 | opcode, 127]) + struct.pack("!Q", length)
        with self.lock:
            self.socket.sendall(header + data)


class ForwardQueue(queue.Queue):
    """Bound retained payloads without ever blocking the RPC reader."""

    def __init__(self, max_bytes=256 << 20):
        super().__init__()
        self.max_bytes = max_bytes
        self.queued_bytes = 0

    def _put(self, event):
        size = len(event[1]) if event[1] is not None else 0
        if size and (self.queued_bytes + size > self.max_bytes or len(self.queue) >= 4096):
            raise queue.Full
        self.queued_bytes += size
        super()._put(event)

    def _get(self):
        event = super()._get()
        self.queued_bytes -= len(event[1]) if event[1] is not None else 0
        return event


class Proxy:
    def __init__(self, client, upstream, delay):
        self.client, self.upstream = client, upstream
        self.upstream.message_limit = ClientSocket.message_limit
        self.events = ForwardQueue()
        self.pending = {}
        self.client_requests = {}
        self.server_requests = set()
        self.idle = IdleThreads(self.request, delay, lambda: (
            self.events.empty() and not self.client_requests and not self.server_requests
        ))
        self.initialized = False
        self.prefix = "idle-" + uuid.uuid4().hex + "-"
        self.serial = 0
        self.checks = None
        self.check_id = None
        self.check_deadline = 0

    def request(self, method, params):
        self.serial += 1
        request_id = self.prefix + str(self.serial)
        response = queue.Queue(maxsize=1)
        self.pending[request_id] = response
        try:
            self.upstream.send(json.dumps({"id": request_id, "method": method, "params": params}).encode())
            deadline = time.monotonic() + 30
            while True:
                try:
                    message = response.get(timeout=max(.01, deadline - time.monotonic()))
                except queue.Empty as error:
                    raise UsageUnavailable("Idle resource request timed out") from error
                if "error" not in message:
                    break
                closing = "is closing; retry" in message["error"].get("message", "")
                if method != "thread/resume" or not closing or time.monotonic() >= deadline:
                    raise UsageUnavailable("Idle resource request failed: " + method)
                time.sleep(.1)
                self.upstream.send(json.dumps({"id": request_id, "method": method, "params": params}).encode())
            return message["result"]
        finally:
            self.pending.pop(request_id, None)

    def read(self, side, transport):
        try:
            for payload in transport.messages():
                self.receive(side, payload)
                del payload
        except queue.Full:
            # A blocking put could prevent the same reader from delivering our RPC response.
            self.close()
        except (OSError, EOFError, ValueError):
            pass
        finally:
            self.events.put((side, None))

    def receive(self, side, payload):
        message = json.loads(payload)
        target = self.pending.get(message.get("id"))
        if side == "server" and "method" not in message and target is not None:
            target.put_nowait(message)
            if message.get('id') == self.check_id:
                self.events.put(('maintenance', None))
            return
        params = message.get("params") or {}
        thread_id = params.get("threadId") or (params.get("thread") or {}).get("id")
        child_woke = (message.get("method") == "thread/status/changed"
                      and params["status"]["type"] != "notLoaded"
                      and self.idle.threads.get(thread_id, {}).get("parent"))
        if (side == "server" and thread_id in self.idle.sleeping
                and not child_woke
                and message.get("method") in ("thread/closed", "thread/started", "thread/status/changed")):
            return
        self.events.put((side, payload))

    def run(self):
        readers = [threading.Thread(target=self.read, args=(side, transport), daemon=True)
                   for side, transport in (("client", self.client), ("server", self.upstream))]
        for reader in readers:
            reader.start()
        try:
            while True:
                try:
                    side, payload = self.events.get(timeout=1)
                except queue.Empty:
                    self.inspect_idle()
                    continue
                if side == 'maintenance':
                    self.inspect_idle()
                    continue
                if payload is None:
                    break
                message = json.loads(payload)
                if side == "client":
                    self.forward_client(message, payload)
                else:
                    self.forward_server(message, payload)
                del message, payload
        finally:
            self.cancel_inspection()
            self.close()
            for reader in readers:
                reader.join(timeout=2)

    def inspect_idle(self):
        now = time.monotonic()
        if self.checks is None:
            if not self.initialized or self.client_requests or self.server_requests:
                return
            self.checks = self.idle.inspect(now)
        result = None
        if self.check_id is not None:
            try:
                response = self.pending[self.check_id].get_nowait()
            except queue.Empty:
                if now >= self.check_deadline:
                    self.cancel_inspection()
                return
            self.pending.pop(self.check_id)
            self.check_id = None
            if 'error' in response:
                self.cancel_inspection()
                return
            result = response['result']
        try:
            method, params = self.checks.send(result)
        except StopIteration:
            self.checks = None
            return
        self.serial += 1
        self.check_id = self.prefix + str(self.serial)
        self.pending[self.check_id] = queue.Queue(maxsize=1)
        self.check_deadline = now + 30
        self.upstream.send(json.dumps({'id': self.check_id, 'method': method, 'params': params}).encode())

    def cancel_inspection(self):
        if self.checks is not None:
            self.checks.close()
            self.checks = None
            for thread_id in self.idle.threads:
                self.idle.touch(thread_id, time.monotonic())
        if self.check_id is not None:
            self.pending.pop(self.check_id, None)
            self.check_id = None

    def close(self):
        self.client.close()
        self.upstream.close()
        for response in list(self.pending.values()):
            try:
                response.put_nowait({'error': {'message': 'Proxy connection ended'}})
            except queue.Full:
                pass

    def forward_client(self, message, payload):
        method, params = message.get("method"), message.get("params") or {}
        thread_id = params.get("threadId")
        if method == "initialized":
            self.initialized = True
        if method and thread_id:
            try:
                if method not in READ_METHODS and method != "thread/unsubscribe":
                    self.idle.wake(thread_id, time.monotonic())
                self.idle.touch(thread_id, time.monotonic())
            except UsageUnavailable:
                self.client.send(json.dumps({"id": message["id"], "error": {
                    "code": -32600, "message": "Could not resume the idle thread before submission. Retry or resume; saved history is unchanged.",
                }}).encode())
                return
            # realtime 상태는 추측해서 재구성하지 않는다.
            if method.startswith("thread/realtime/"):
                self.idle.preserve(thread_id)
            if method == "thread/unsubscribe":
                self.idle.threads.pop(thread_id, None)
                self.idle.sleeping.discard(thread_id)
        if "id" in message:
            if method:
                self.client_requests[message["id"]] = (method, params)
            else:
                self.server_requests.discard(message["id"])
        self.upstream.send(payload)

    def forward_server(self, message, payload):
        method, params = message.get("method"), message.get("params") or {}
        thread_id = params.get("threadId")
        if (method == "thread/status/changed" and thread_id in self.idle.sleeping
                and params["status"]["type"] != "notLoaded"
                and self.idle.threads[thread_id]["parent"]):
            # unload 유예 중 owner가 다시 시작한 자식은 자동 재구독되지 않는다.
            try:
                self.idle.wake(thread_id, time.monotonic())
            except UsageUnavailable:
                self.idle.touch(thread_id, time.monotonic() - self.idle.delay)
        if "id" in message:
            if method:
                self.server_requests.add(message["id"])
            else:
                request = self.client_requests.pop(message["id"], None)
                if request and "result" in message and request[0] in ("thread/start", "thread/resume", "thread/fork"):
                    self.idle.track(message["result"], request[1], time.monotonic())
                    if request[0] != "thread/start" and not message["result"]["thread"].get("parentThreadId"):
                        # 기존 runtime의 evicted ephemeral 자식 상태는 RPC로 열거할 수 없다.
                        self.idle.preserve(message["result"]["thread"]["id"])
        if thread_id and method in ("turn/started", "turn/completed", "item/started", "item/completed"):
            # owner가 자식을 다시 실행하면 서버가 이 연결을 자동으로 재구독시킨다.
            self.idle.sleeping.discard(thread_id)
            self.idle.touch(thread_id, time.monotonic())
        # 이 알림은 실제 sticky 설정이 달라질 때만 온다. 오래된 설정으로 resume하지 않는다.
        if method == "thread/settings/updated":
            self.idle.preserve(thread_id)
        if method == "serverRequest/resolved":
            self.server_requests.discard(params["requestId"])
        # 자식부터 회수한다. parent의 loaded 자식 검사가 끝날 때까지 parent는 유지된다.
        if method == "thread/started":
            parent = params["thread"].get("parentThreadId")
            if parent and params["thread"]["id"] not in self.idle.threads:
                self.idle.track(params, {}, time.monotonic())
        elif method == "thread/status/changed" and thread_id not in self.idle.threads:
            try:
                thread = self.request("thread/read", {"threadId": thread_id})["thread"]
                if thread.get("parentThreadId"):
                    self.idle.track({"thread": thread}, {}, time.monotonic())
            except UsageUnavailable:
                # 알림을 읽기 전에 내려간 대화는 새 구독을 만들지 않는다.
                pass
        self.client.send(payload)


def start_proxy(upstream, delay):
    directory = Path(tempfile.mkdtemp(prefix="codex-idle-"))
    endpoint = directory / "tui.sock"
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(upstream), str(endpoint), str(delay),
         str(os.getpid())],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    while not endpoint.exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            raise UsageUnavailable("Idle resource proxy did not start")
        time.sleep(.05)
    return endpoint


def serve(upstream, endpoint, delay, owner_pid):
    endpoint = Path(endpoint)
    listener = socket.socket(socket.AF_UNIX)
    try:
        save({'pid': os.getpid(), 'owner_pid': owner_pid, 'started_at': time.time(),
              'source_revision': SOURCE_REVISION}, endpoint.with_suffix('.json'))
        listener.bind(str(endpoint))
        os.chmod(endpoint, 0o600)
        listener.listen(1)
        listener.settimeout(1)
        while os.getppid() == owner_pid:
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            server = None
            try:
                client = ClientSocket(connection)
                server = UnixWebSocket(upstream)
                # TUI가 새 initialize/resume로 복구한다. 이전 요청은 재전송하지 않는다.
                Proxy(client, server, delay).run()
            except (OSError, EOFError):
                # 서버가 아직 없거나 연결이 끊겨도 같은 주소로 다음 재접속을 받는다.
                pass
            finally:
                connection.close()
                if server:
                    server.close()
    finally:
        listener.close()
        endpoint.unlink(missing_ok=True)
        endpoint.with_suffix('.json').unlink(missing_ok=True)
        endpoint.parent.rmdir()


if __name__ == "__main__":
    serve(sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]))
