"""터미널의 입력·출력을 유지한 채 자신의 유휴 thread 구독만 반환한다."""

from collections import Counter, defaultdict, deque
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import select
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


def routing(message, side):
    """Keep only policy metadata alongside raw bytes, never decoded diff/output bodies."""
    route = {key: message[key] for key in ('id', 'method') if key in message}
    params = message.get('params') or {}
    fields = {'threadId', 'status', 'requestId'}
    if side == 'client' and message.get('method') in ('thread/start', 'thread/resume', 'thread/fork'):
        fields |= RESUME_FIELDS
    route['params'] = {key: params[key] for key in fields if key in params}
    for key in ('dynamicTools', 'selectedCapabilityRoots', 'environments', 'history'):
        if params.get(key):
            route['params'][key] = True
    thread = params.get('thread')
    if thread:
        route['params']['thread'] = {key: thread[key] for key in
                                    ('id', 'parentThreadId', 'ephemeral') if key in thread}
    if 'result' in message:
        result = message['result']
        thread = result.get('thread') if isinstance(result, dict) else None
        route['result'] = {}
        if thread:
            route['result']['thread'] = {key: thread[key] for key in
                                        ('id', 'parentThreadId', 'ephemeral') if key in thread}
    return route


class IdleThreads:
    def __init__(self, request, delay, can_park=lambda: True):
        self.request, self.delay = request, delay
        self.can_park = can_park
        self.threads = {}
        self.sleeping = set()
        self.inspecting = None
        self.child_counts = Counter()

    def forget(self, thread_id):
        saved = self.threads.pop(thread_id, None)
        self.sleeping.discard(thread_id)
        if saved and saved["parent"]:
            parent = saved["parent"]
            self.child_counts[parent] -= 1
            if not self.child_counts[parent]:
                del self.child_counts[parent]

    def track(self, result, params, now):
        thread = result["thread"]
        blocked = (thread["ephemeral"] or any(params.get(key) for key in
                   ("dynamicTools", "selectedCapabilityRoots", "environments", "history")))
        self.forget(thread["id"])
        self.threads[thread["id"]] = {
            "ephemeral": thread["ephemeral"],
            "params": {key: value for key, value in params.items() if key in RESUME_FIELDS},
            "last_activity": now, "blocked": blocked,
            "parent": thread.get("parentThreadId"),
        }
        parent = thread.get("parentThreadId")
        if parent:
            self.child_counts[parent] += 1
            self.preserve(parent)
        if self.child_counts[thread["id"]]:
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
                try:
                    result = self.request(method, params)
                except Exception as error:
                    checks.throw(error)
        except StopIteration:
            pass
        finally:
            checks.close()

    def inspect(self, now):
        try:
            yield from self.inspect_candidates(now)
        finally:
            self.inspecting = None

    def inspect_candidates(self, now):
        ancestors = None
        for thread_id, saved in list(self.threads.items()):
            activity = saved['last_activity']
            was_sleeping = thread_id in self.sleeping
            if (saved["blocked"] or (was_sleeping and not saved["parent"])
                    or now - saved["last_activity"] < self.delay):
                continue
            self.inspecting = thread_id
            if not self.can_park():
                continue
            # root runtime은 내려간 자식의 mailbox·environment도 소유한다 (0.169.0).
            children = yield "thread/list", {"parentThreadId": thread_id, "limit": 1}
            if children["data"]:
                saved["blocked"] = True
                continue
            # 영속 목록에 없는 ephemeral 자식도 보존한다.
            if ancestors is None:
                ancestors, parents = set(), {}
                cursor = catalog_cursor = None
                catalog_done = False
                while True:
                    loaded = yield 'thread/loaded/list', {'cursor': cursor}
                    if len(loaded['data']) > 1 and not catalog_done:
                        # A current page of persisted metadata covers ordinary terminals in one RPC.
                        # Ephemeral and older threads still need their live ancestry checked.
                        for offset in range(0, len(loaded['data']), 100):
                            page = yield 'thread/list', {'limit': min(100, len(loaded['data']) - offset),
                                                         'sortKey': 'updated_at', 'cursor': catalog_cursor}
                            for item in page['data']:
                                parents[item['id']] = item.get('parentThreadId')
                            catalog_cursor = page.get('nextCursor')
                            if not catalog_cursor:
                                catalog_done = True
                                break
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
            if terminals["data"]:
                saved["last_activity"] = now
                continue
            goal = (yield "thread/goal/get", params)["goal"]
            queued = yield "thread/queue/list", params
            turns = yield "thread/turns/list", {
                **params, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded",
            }
            if (queued["data"] or not turns["data"]
                    or (goal and goal["status"] != "complete")):
                saved["last_activity"] = now
                continue
            if not self.can_park():
                continue
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
        steps = self.wake_steps(thread_id, now)
        result = None
        try:
            while True:
                method, params = steps.send(result)
                result = self.request(method, params)
        except StopIteration:
            pass
        finally:
            steps.close()

    def wake_steps(self, thread_id, now):
        if thread_id in self.sleeping:
            parent = self.threads[thread_id]["parent"]
            if parent in self.threads:
                yield from self.wake_steps(parent, now)
            yield "thread/resume", {
                **self.threads[thread_id]["params"], "threadId": thread_id, "excludeTurns": True,
            }
            self.sleeping.discard(thread_id)
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
        try:
            headers = {name.lower().strip(): value.strip() for name, value in
                       (line.split(':', 1) for line in header.decode('ascii').split('\r\n')[1:]
                        if ':' in line)}
            key = headers.get('sec-websocket-key', '')
            if len(header) > 16384 or len(base64.b64decode(key, validate=True)) != 16:
                raise ValueError('Invalid WebSocket key')
        except ValueError as error:
            raise OSError('Invalid local TUI handshake') from error
        accepted = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        connection.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                            "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accepted + "\r\n\r\n").encode())
        connection.settimeout(None)

    def send_frame(self, opcode, data, deadline=None):
        length = len(data)
        if length < 126:
            header = bytes([0x80 | opcode, length])
        elif length < 65536:
            header = bytes([0x80 | opcode, 126]) + struct.pack("!H", length)
        else:
            header = bytes([0x80 | opcode, 127]) + struct.pack("!Q", length)
        self.write((header, data), deadline)


class ForwardQueue(queue.Queue):
    """Bound retained payloads without ever blocking the RPC reader."""

    def __init__(self, max_bytes=256 << 20):
        super().__init__()
        self.max_bytes = max_bytes
        self.queued_bytes = 0
        self.thread_counts = Counter()

    @staticmethod
    def owners(event):
        if len(event) < 3:
            return ()
        params = event[2].get("params", {})
        thread = params.get("thread", {})
        owners = {params.get('threadId') or thread.get('id')}
        if thread.get('parentThreadId'):
            owners.add(thread['parentThreadId'])
        return owners

    def blocks(self, thread_id):
        with self.mutex:
            return bool(self.thread_counts[thread_id] or self.thread_counts[None])

    def _put(self, event):
        size = len(event[1]) if event[1] is not None else 0
        if size and (self.queued_bytes + size > self.max_bytes or len(self.queue) >= 4096):
            raise queue.Full
        self.queued_bytes += size
        self.thread_counts.update(self.owners(event))
        super()._put(event)

    def _get(self):
        event = super()._get()
        self.queued_bytes -= len(event[1]) if event[1] is not None else 0
        for owner in self.owners(event):
            self.thread_counts[owner] -= 1
            if not self.thread_counts[owner]:
                del self.thread_counts[owner]
        return event


class Proxy:
    request_limit = 4096
    request_byte_limit = 256 << 20

    def __init__(self, client, upstream, delay):
        self.client, self.upstream = client, upstream
        self.upstream.message_limit = ClientSocket.message_limit
        self.events = ForwardQueue()
        self.pending = {}
        self.client_requests = {}
        self.server_requests = {}
        self.request_sizes = {}
        self.request_bytes = 0
        self.discoveries = {}
        self.wakeups = {}
        self.wake_requests = {}
        self.deferred = defaultdict(deque)
        self.deferred_count = self.deferred_bytes = 0
        self.resuming = set()
        self.idle = IdleThreads(self.request, delay, self.can_park)
        self.initialized = False
        self.prefix = "idle-" + uuid.uuid4().hex + "-"
        self.serial = 0
        self.checks = None
        self.check_id = None
        self.check_deadline = 0

    def can_park(self):
        owner = self.idle.inspecting
        return (owner not in self.wakeups and owner not in self.wake_requests and owner not in self.resuming
                and not self.events.blocks(owner) and not self.discoveries
                and all(params.get("threadId") not in (None, owner)
                        for _, params in self.client_requests.values())
                and all(thread not in (None, owner) for thread in self.server_requests.values()))

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
        request_id = message.get('id')
        target = self.pending.get(request_id)
        if side == 'server' and 'method' not in message and (
                target is not None or isinstance(request_id, str) and request_id.startswith(self.prefix)):
            if target is not None:
                target.put_nowait(message)
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
        self.events.put((side, payload, routing(message, side)))

    def run(self):
        readers = [threading.Thread(target=self.read, args=(side, transport), daemon=True)
                   for side, transport in (("client", self.client), ("server", self.upstream))]
        for reader in readers:
            reader.start()
        next_check = time.monotonic() + 1
        try:
            while True:
                try:
                    event = self.events.get(timeout=max(0, next_check - time.monotonic()))
                except queue.Empty:
                    self.inspect_idle()
                    next_check = time.monotonic() + 1
                    continue
                side, payload = event[:2]
                if side == 'maintenance':
                    self.inspect_idle()
                    continue
                if payload is None:
                    break
                message = event[2]
                if side == "client":
                    self.forward_client(message, payload)
                else:
                    self.forward_server(message, payload)
                if self.wakeups or time.monotonic() >= next_check:
                    self.inspect_idle()
                    next_check = time.monotonic() + 1
                del message, payload, event
        finally:
            try:
                self.cancel_inspection()
            finally:
                self.close()
            for reader in readers:
                reader.join(timeout=2)

    def inspect_idle(self):
        now = time.monotonic()
        if self.wakeups or self.wake_requests:
            self.advance_wakes(now)
        if self.checks is None:
            if not self.initialized:
                return
            self.checks = self.inspect_threads(now)
        result = None
        if self.check_id is not None:
            try:
                response = self.pending[self.check_id].get_nowait()
            except queue.Empty:
                if now >= self.check_deadline:
                    self.idle.touch(self.idle.inspecting, now)
                    self.cancel_inspection()
                return
            self.pending.pop(self.check_id)
            self.check_id = None
            if 'error' in response:
                self.cancel_inspection(UsageUnavailable('Idle resource request failed'))
                return
            result = response['result']
        try:
            method, params = self.checks.send(result)
        except StopIteration:
            self.checks = None
            return
        self.check_params = params
        self.check_deadline = now + 30
        self.check_id = self.begin_request(method, params)

    def begin_request(self, method, params):
        self.serial += 1
        request_id = self.prefix + str(self.serial)
        self.pending[request_id] = queue.Queue(maxsize=1)
        self.upstream.send(json.dumps({'id': request_id, 'method': method, 'params': params}).encode())
        return request_id

    def wake_target(self, owner):
        """A sleeping ancestor resumes before its child. Independent roots can resume concurrently."""
        target = None
        thread = owner
        while thread in self.idle.threads:
            if thread in self.idle.sleeping or thread in self.wake_requests:
                target = thread
            thread = self.idle.threads[thread]['parent']
        return target

    def advance_wakes(self, now):
        for target, (request_id, deadline) in list(self.wake_requests.items()):
            try:
                response = self.pending[request_id].get_nowait()
            except queue.Empty:
                if now < deadline:
                    continue
                response = {'error': {}}
            owners = ([owner for owner in self.wakeups if self.wake_target(owner) == target]
                      if 'error' in response else ())
            self.wake_requests.pop(target)
            self.pending.pop(request_id)
            if 'error' not in response:
                self.idle.sleeping.discard(target)
                self.idle.touch(target, now)
                continue
            detail = response['error'].get('message', '')
            gone = detail in (f'thread not found: {target}', f'no rollout found for thread id {target}',
                              'thread no longer available')
            for owner in owners:
                if gone:
                    self.wakeups.pop(owner, None)
                else:
                    self.wakeups[owner] = now + 5
                self.flush_deferred(owner, failed=True)
            if gone:
                self.idle.forget(target)

        for owner, due in list(self.wakeups.items()):
            if now < due:
                continue
            target = self.wake_target(owner)
            if target is None:
                self.wakeups.pop(owner)
                self.flush_deferred(owner)
            elif target not in self.wake_requests and target not in self.resuming:
                params = {**self.idle.threads[target]['params'], 'threadId': target, 'excludeTurns': True}
                self.wake_requests[target] = self.begin_request('thread/resume', params), now + 30

    def inspect_threads(self, now):
        for thread_id in list(self.discoveries):
            try:
                thread = (yield 'thread/read', {'threadId': thread_id})['thread']
            finally:
                self.discoveries.pop(thread_id, None)
            if thread.get('parentThreadId') and thread_id not in self.idle.threads:
                self.idle.track({'thread': thread}, {}, time.monotonic())
        yield from self.idle.inspect(now)

    def cancel_inspection(self, error=None):
        if self.checks is not None:
            if error is not None:
                self.idle.touch(self.idle.inspecting, time.monotonic())
                try:
                    self.checks.throw(error)
                except (UsageUnavailable, StopIteration):
                    pass
            self.checks.close()
            self.checks = None
        if self.check_id is not None:
            self.pending.pop(self.check_id, None)
            self.check_id = None

    def flush_deferred(self, thread_id, failed=False):
        for payload, message in self.deferred.pop(thread_id, ()):
            self.deferred_count -= 1
            self.deferred_bytes -= len(payload)
            if failed:
                self.client.send(json.dumps({'id': message['id'], 'error': {
                    'code': -32600, 'message': 'Could not resume the idle thread. Retry submission.',
                }}).encode())
            else:
                self.forward_client(message, payload)

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
            if method not in READ_METHODS:
                self.idle.touch(thread_id, time.monotonic())
                needs_wake = (thread_id in self.idle.sleeping
                              and method not in ('thread/resume', 'thread/unsubscribe'))
                if needs_wake or thread_id in self.wakeups or thread_id in self.resuming:
                    if (self.deferred_count >= self.request_limit
                            or self.deferred_bytes + len(payload) > self.request_byte_limit):
                        raise OSError('Too many requests awaiting resume')
                    self.deferred[thread_id].append((payload, message))
                    self.deferred_count += 1
                    self.deferred_bytes += len(payload)
                    if needs_wake and thread_id not in self.resuming:
                        self.wakeups.setdefault(thread_id, 0)
                    return
                if method == 'thread/resume' and thread_id in self.idle.sleeping:
                    self.resuming.add(thread_id)
            # realtime 상태는 추측해서 재구성하지 않는다.
            if method.startswith("thread/realtime/"):
                self.idle.preserve(thread_id)
        if "id" in message:
            if method:
                self.retain_request('client', message['id'], len(payload))
                self.client_requests[message["id"]] = (method, params)
            else:
                self.release_request('server', message['id'])
                self.server_requests.pop(message["id"], None)
        self.upstream.send(payload)

    def forward_server(self, message, payload):
        method, params = message.get("method"), message.get("params") or {}
        thread_id = params.get("threadId")
        if method == 'thread/deleted' or (method == 'thread/closed'
                                            and self.idle.threads.get(thread_id, {}).get('ephemeral')):
            if (thread_id == self.idle.inspecting
                    or self.check_id and thread_id == self.check_params.get('threadId')):
                self.cancel_inspection()
            for owner in list(self.wakeups):
                if self.wake_target(owner) == thread_id:
                    self.wakeups.pop(owner)
                    self.flush_deferred(owner, failed=True)
            pending = self.wake_requests.pop(thread_id, None)
            if pending:
                self.pending.pop(pending[0], None)
            self.idle.forget(thread_id)
            self.resuming.discard(thread_id)
            self.discoveries.pop(thread_id, None)
            self.wakeups.pop(thread_id, None)
            self.flush_deferred(thread_id, failed=True)
        if (method == "thread/status/changed" and thread_id in self.idle.sleeping
                and params["status"]["type"] != "notLoaded"
                and self.idle.threads[thread_id]["parent"]):
            # unload 유예 중 owner가 다시 시작한 자식은 자동 재구독되지 않는다.
            self.wakeups.setdefault(thread_id, 0)
        if "id" in message:
            if method:
                self.retain_request('server', message['id'], len(payload))
                self.server_requests[message["id"]] = thread_id
            else:
                self.release_request('client', message['id'])
                request = self.client_requests.pop(message["id"], None)
                if request and "result" in message and request[0] in ("thread/start", "thread/resume", "thread/fork"):
                    self.idle.track(message["result"], request[1], time.monotonic())
                    if request[0] != "thread/start" and not message["result"]["thread"].get("parentThreadId"):
                        # 기존 runtime의 evicted ephemeral 자식 상태는 RPC로 열거할 수 없다.
                        self.idle.preserve(message["result"]["thread"]["id"])
                if request and request[0] == "thread/unsubscribe" and "result" in message:
                    self.idle.forget(request[1].get("threadId"))
                if request and request[0] == "thread/resume":
                    owner = request[1].get("threadId")
                    self.resuming.discard(owner)
                    self.flush_deferred(owner, failed="result" not in message)
        if thread_id and method and (method == "thread/status/changed" or method.startswith(("thread/goal/", "thread/queue/"))):
            self.idle.touch(thread_id, time.monotonic())
        if thread_id and method in ("turn/started", "turn/completed", "item/started", "item/completed"):
            # owner가 자식을 다시 실행하면 서버가 이 연결을 자동으로 재구독시킨다.
            self.idle.sleeping.discard(thread_id)
            self.idle.touch(thread_id, time.monotonic())
        # 이 알림은 실제 sticky 설정이 달라질 때만 온다. 오래된 설정으로 resume하지 않는다.
        if method == "thread/settings/updated":
            self.idle.preserve(thread_id)
        if method == "serverRequest/resolved":
            self.release_request('server', params['requestId'])
            self.server_requests.pop(params["requestId"], None)
        # 자식부터 회수한다. parent의 loaded 자식 검사가 끝날 때까지 parent는 유지된다.
        if method == "thread/started":
            parent = params["thread"].get("parentThreadId")
            if parent and params["thread"]["id"] not in self.idle.threads:
                self.idle.track(params, {}, time.monotonic())
        elif method == "thread/status/changed" and thread_id not in self.idle.threads:
            if len(self.discoveries) >= self.request_limit:
                raise OSError('Too many undiscovered threads')
            self.discoveries[thread_id] = None
        self.client.send(payload)

    def retain_request(self, side, request_id, size):
        key = (side, request_id)
        if (key in self.request_sizes or len(self.request_sizes) >= self.request_limit
                or self.request_bytes + size > self.request_byte_limit):
            raise OSError('Too many pending proxy requests')
        self.request_sizes[key] = size
        self.request_bytes += size

    def release_request(self, side, request_id):
        self.request_bytes -= self.request_sizes.pop((side, request_id), 0)


def start_proxy(upstream, delay):
    directory = Path(tempfile.mkdtemp(prefix="codex-idle-"))
    endpoint = directory / "tui.sock"
    try:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(upstream), str(endpoint), str(delay),
             str(os.getpid())],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        directory.rmdir()
        raise
    deadline = time.monotonic() + 10
    while not endpoint.exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            if directory.exists():
                endpoint.unlink(missing_ok=True)
                endpoint.with_suffix('.json').unlink(missing_ok=True)
                directory.rmdir()
            raise UsageUnavailable("Idle resource proxy did not start")
        time.sleep(.05)
    return endpoint


def serve(upstream, endpoint, delay, owner_pid):
    endpoint = Path(endpoint)
    listener = socket.socket(socket.AF_UNIX)
    owner = select.kqueue()
    status = {'pid': os.getpid(), 'owner_pid': owner_pid, 'started_at': time.time(),
              'source_revision': SOURCE_REVISION, 'connected': False, 'connections': 0}
    try:
        # Kernel registration follows this process incarnation, even after reparenting/PID reuse.
        owner.control([select.kevent(owner_pid, filter=select.KQ_FILTER_PROC,
                                     flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                     fflags=select.KQ_NOTE_EXIT)], 0, 0)
        save(status, endpoint.with_suffix('.json'))
        listener.bind(str(endpoint))
        os.chmod(endpoint, 0o600)
        listener.listen(1)
        listener.settimeout(1)
        while not owner.control([], 1, 0):
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            server = None
            try:
                client = ClientSocket(connection)
                server = UnixWebSocket(upstream)
                status.update(connected=True, connections=status['connections'] + 1,
                              connected_at=time.time())
                save(status, endpoint.with_suffix('.json'))
                # TUI가 새 initialize/resume로 복구한다. 이전 요청은 재전송하지 않는다.
                Proxy(client, server, delay).run()
            except (OSError, EOFError):
                # 서버가 아직 없거나 연결이 끊겨도 같은 주소로 다음 재접속을 받는다.
                pass
            finally:
                connection.close()
                if server:
                    server.close()
                status['connected'] = False
                save(status, endpoint.with_suffix('.json'))
    finally:
        owner.close()
        listener.close()
        endpoint.unlink(missing_ok=True)
        endpoint.with_suffix('.json').unlink(missing_ok=True)
        endpoint.parent.rmdir()


if __name__ == "__main__":
    serve(sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]))
