"""터미널의 입력·출력을 유지한 채 자신의 유휴 thread 구독만 반환한다."""

from collections import Counter, defaultdict, deque
import base64
import errno
import hashlib
import heapq
import json
import os
from pathlib import Path
import queue
import re
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
from unix_ws import UnixWebSocket, read_handshake


RESUME_FIELDS = {"model", "modelProvider", "serviceTier", "cwd", "runtimeWorkspaceRoots",
                 "approvalPolicy", "approvalsReviewer", "sandbox", "permissions", "config",
                 "baseInstructions", "developerInstructions", "personality"}
READ_METHODS = {"thread/read", "thread/turns/list", "thread/items/list", "thread/goal/get",
                "thread/queue/list", "thread/attachment/list", "thread/backgroundTerminals/list"}
# Cold resume restores the model and reasoning settings from the thread's persisted history.
MODEL_OVERRIDES = {"model", "model_provider", "model_reasoning_effort"}
GLOBAL_TRANSITIONS = {"account/login/start", "account/logout"}
SOURCE_REVISION = hashlib.sha256(b''.join(
    Path(__file__).with_name(name).read_bytes() for name in ('idle.py', 'unix_ws.py')
)).hexdigest()
DIFF_HEADER = re.compile(br'^\s*\{\s*"method"\s*:\s*"turn/diff/updated"\s*,\s*"params"\s*:\s*\{'
                         br'\s*"threadId"\s*:\s*"([\w.-]{1,128})"\s*,'
                         br'(?:\s*"turnId"\s*:\s*"[\w.-]{1,128}"\s*,)?\s*"diff"\s*:\s*"')
DIFF_END = re.compile(br'\s*\}\s*\}\s*\Z')
DIFF_VALUE = re.compile(br'"diff"\s*:\s*"')


def diff_route(payload):
    header = DIFF_HEADER.match(payload)
    field = header or DIFF_VALUE.search(payload, 0, 4096)
    if not field:
        return None
    cursor = field.end()
    while (quote := payload.find(b'"', cursor)) >= 0:
        escape = quote
        while escape > cursor and payload[escape - 1] == 92:
            escape -= 1
        if (quote - escape) % 2 == 0:
            if header and DIFF_END.fullmatch(payload, quote + 1):
                return {'method': 'turn/diff/updated', 'params': {'threadId': header[1].decode()}}
            if field.end() + len(payload) - quote <= 8192:
                try:
                    envelope = json.loads(payload[:field.end()] + payload[quote:])
                except ValueError:
                    return None
                if (isinstance(envelope, dict) and 'id' not in envelope
                        and envelope.get('method') == 'turn/diff/updated'
                        and isinstance(envelope.get('params'), dict)
                        and envelope['params'].get('diff') == ''):
                    return routing(envelope, 'server')
            break
        cursor = quote + 1
    return None


def routing(message, side):
    """Keep only policy metadata alongside raw bytes, never decoded diff/output bodies."""
    route = {key: message[key] for key in ('id', 'method') if key in message}
    params = message.get('params') or {}
    fields = {'threadId', 'status', 'requestId'}
    if side == 'client' and message.get('method') in ('thread/start', 'thread/resume', 'thread/fork'):
        fields |= RESUME_FIELDS
    route['params'] = {key: params[key] for key in fields if key in params}
    if side == 'server' and message.get('method') in ('execCommandApproval', 'applyPatchApproval'):
        if params.get('conversationId'):
            route['params']['threadId'] = params['conversationId']
    for key in ('dynamicTools', 'selectedCapabilityRoots', 'environments', 'history'):
        if params.get(key) or key == 'environments' and params.get(key) is not None:
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
        self.realtime = set()
        self.inspecting = None
        self.child_counts = Counter()
        self.due = []
        self.scheduled = {}
        self.serial = 0

    def forget(self, thread_id):
        saved = self.threads.pop(thread_id, None)
        self.sleeping.discard(thread_id)
        self.realtime.discard(thread_id)
        self.scheduled.pop(thread_id, None)
        if saved and saved["parent"]:
            parent = saved["parent"]
            self.child_counts[parent] -= 1
            if not self.child_counts[parent]:
                del self.child_counts[parent]

    def track(self, result, params, now):
        thread = result["thread"]
        blocked = (thread["ephemeral"] or params.get('environments') is not None or any(params.get(key) for key in
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
        self.schedule(thread['id'], now + self.delay)

    def resume_params(self, owner):
        params = {key: value for key, value in self.threads[owner]["params"].items()
                  if key not in ('model', 'modelProvider')}
        if isinstance(params.get('config'), dict):
            params['config'] = {key: value for key, value in params['config'].items()
                                if key not in MODEL_OVERRIDES}
        return {**params, 'threadId': owner, 'excludeTurns': True}

    def schedule(self, owner, due, *, earlier=False):
        entry = self.scheduled.get(owner)
        if entry is None or earlier and due < entry[0]:
            self.serial += 1
            self.scheduled[owner] = (due, self.serial)
            heapq.heappush(self.due, (due, self.serial, owner))
        if len(self.due) > 2 * len(self.scheduled) + 32:
            self.due = [(*entry, key) for key, entry in self.scheduled.items()]
            heapq.heapify(self.due)

    def candidates(self, now):
        while self.due and self.due[0][0] <= now:
            due, serial, owner = heapq.heappop(self.due)
            if self.scheduled.get(owner) != (due, serial):
                continue
            del self.scheduled[owner]
            saved = self.threads.get(owner)
            if not saved or saved['blocked'] or owner in self.realtime or owner in self.sleeping and not saved['parent']:
                continue
            next_due = saved['last_activity'] + self.delay
            self.schedule(owner, next_due if next_due > now else now + max(.001, self.delay))
            if next_due <= now:
                yield owner, saved

    def preserve(self, thread_id):
        if thread_id in self.threads:
            self.threads[thread_id]["blocked"] = True

    def touch(self, thread_id, now):
        if thread_id in self.threads:
            self.threads[thread_id]["last_activity"] = now
            self.schedule(thread_id, now + self.delay)

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
        cache = {}
        work = deque((owner, self.inspect_candidates(now, ((owner, saved),), cache), None)
                     for owner, saved in self.candidates(now))
        try:
            while work:
                owner, checks, reply = work.popleft()
                self.inspecting = owner
                until = time.monotonic() + 2
                try:
                    while True:
                        step = checks.send(reply)
                        try:
                            reply = yield step
                        except Exception as error:
                            checks.throw(error)
                            raise
                        if work and time.monotonic() >= until:
                            work.append((owner, checks, reply))
                            break
                except StopIteration:
                    continue
                finally:
                    if not work or work[-1][1] is not checks:
                        checks.close()
        finally:
            for owner, checks, _ in work:
                checks.close()
                self.schedule(owner, now, earlier=True)
            self.inspecting = None

    def inspect_candidates(self, now, candidates, cache):
        started = time.monotonic()
        for thread_id, saved in candidates:
            activity = saved['last_activity']
            was_sleeping = thread_id in self.sleeping
            if (saved["blocked"] or (was_sleeping and not saved["parent"])
                    or now - saved["last_activity"] < self.delay):
                continue
            self.inspecting = thread_id
            if not self.can_park():
                self.schedule(thread_id, now + 1, earlier=True)
                continue
            # root runtime은 내려간 자식의 mailbox·environment도 소유한다 (0.169.0).
            children = yield "thread/list", {"parentThreadId": thread_id, "limit": 1}
            if children["data"]:
                saved["blocked"] = True
                continue
            # 영속 목록에 없는 ephemeral 자식도 보존한다.
            ancestors = cache.get('ancestors')
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
                            if not other_id or other_id in seen or other_id in ancestors:
                                break
                            ancestors.add(other_id)
                            seen.add(other_id)
                    cursor = loaded.get('nextCursor')
                    if not cursor:
                        break
                cache['ancestors'] = ancestors
            if thread_id in ancestors:
                saved["blocked"] = True
                continue
            params = {"threadId": thread_id}
            thread = (yield "thread/read", params)["thread"]
            if thread["status"]["type"] != "idle" or thread["ephemeral"]:
                self.touch(thread_id, now + (time.monotonic() - started))
                continue
            terminals = yield "thread/backgroundTerminals/list", params
            if terminals["data"]:
                self.touch(thread_id, now + (time.monotonic() - started))
                continue
            goal = (yield "thread/goal/get", params)["goal"]
            if goal and goal["status"] != "complete":
                self.touch(thread_id, now + (time.monotonic() - started))
                continue
            queued = yield "thread/queue/list", params
            if queued["data"]:
                self.touch(thread_id, now + (time.monotonic() - started))
                continue
            turns = yield "thread/turns/list", {
                **params, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded",
            }
            if not turns["data"]:
                self.touch(thread_id, now + (time.monotonic() - started))
                continue
            if not self.can_park():
                self.schedule(thread_id, now + 1, earlier=True)
                continue
            if (self.threads.get(thread_id) is not saved or saved['blocked'] or thread_id in self.realtime
                    or saved['last_activity'] != activity):
                continue
            # thread/closed 종료 알림보다 먼저 표시한다. TUI는 이 알림을 받으면 종료한다.
            self.sleeping.add(thread_id)
            try:
                yield "thread/unsubscribe", params
                if saved['last_activity'] == activity:
                    self.touch(thread_id, now + (time.monotonic() - started))
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
            yield "thread/resume", self.resume_params(thread_id)
            self.sleeping.discard(thread_id)
        self.touch(thread_id, now)


class ClientSocket(UnixWebSocket):
    # 공식 TUI의 remote WebSocket 한도와 같다 (0.169.0 remote.rs).
    message_limit = 128 << 20

    def __init__(self, connection, owner_watch=None):
        self.socket, self.lock = connection, threading.Lock()
        header, self.buffer = read_handshake(connection, owner_watch=owner_watch)
        try:
            headers = {name.lower().strip(): value.strip() for name, value in
                       (line.split(':', 1) for line in header.decode('ascii').split('\r\n')[1:]
                        if ':' in line)}
            key = headers.get('sec-websocket-key', '')
            if len(base64.b64decode(key, validate=True)) != 16:
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


class WakeSchedule(dict):
    def __init__(self, changed):
        super().__init__()
        self.changed = changed

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.changed()


class MaintenanceReply(queue.Queue):
    def __init__(self, owner):
        super().__init__(maxsize=1)
        self.owner = owner

    def _put(self, response):
        super()._put(response)
        self.owner.wake_dirty = True


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
        self.wake_dirty = True
        self.wakeups = WakeSchedule(self.wake_changed)
        self.next_wake_check = 0
        self.wake_requests = WakeSchedule(self.wake_changed)
        self.deferred = defaultdict(deque)
        self.deferred_count = self.deferred_bytes = 0
        self.resuming = set()
        self.explicit_resumes = {}
        self.external_roots = {}
        self.request_owners = {}
        self.owner_counts = Counter()
        self.global_transitions = {}
        self.early_closes = {}
        self.uncertain_unsubscribes = {}
        self.unsubscribe_lock = threading.RLock()
        self.wake_retry_limits = {}
        self.retried_timeouts = set()
        self.check_params = {}
        self.writers = {}
        self.stopped = threading.Event()
        self.idle = IdleThreads(self.request, delay, self.can_park)
        self.initialized = False
        self.prefix = "idle-" + uuid.uuid4().hex + "-"
        self.serial = 0
        self.checks = None
        self.check_id = None
        self.check_deadline = 0

    def can_park(self):
        owner = self.idle.inspecting
        now = time.monotonic()
        self.global_transitions = {key: until for key, until in self.global_transitions.items()
                                   if until > now}
        return (owner not in self.wakeups and owner not in self.wake_requests and owner not in self.resuming
                and not self.events.blocks(owner) and not self.discoveries
                and not self.owner_counts[owner] and not self.global_transitions)

    def request(self, method, params):
        self.serial += 1
        request_id = self.prefix + str(self.serial)
        response = queue.Queue(maxsize=1)
        self.pending[request_id] = response
        try:
            self.send('server', json.dumps({"id": request_id, "method": method, "params": params}).encode())
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
                self.send('server', json.dumps({"id": request_id, "method": method, "params": params}).encode())
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
        if side == 'server' and len(payload) >= 65536:
            route = diff_route(payload)
            if route:
                self.events.put((side, payload, route))
                return
        message = json.loads(payload)
        request_id = message.get('id')
        target = self.pending.get(request_id)
        if side == 'server' and 'method' not in message and (
                target is not None or isinstance(request_id, str) and request_id.startswith(self.prefix)):
            with self.unsubscribe_lock:
                owner = self.uncertain_unsubscribes.pop(request_id, None)
                if owner is not None:
                    early = self.early_closes.pop(owner, None)
                    if 'error' in message:
                        self.idle.sleeping.discard(owner)
                        if early:
                            self.events.put(early)
                elif target is not None:
                    target.put_nowait(message)
                    self.next_wake_check = 0
                    self.events.put(('maintenance', None))
            return
        params = message.get("params") or {}
        thread_id = params.get("threadId") or (params.get("thread") or {}).get("id")
        if side == 'server' and message.get('method') == 'thread/closed':
            with self.unsubscribe_lock:
                if thread_id in self.idle.sleeping:
                    if (getattr(self, 'check_method', None) == 'thread/unsubscribe'
                            and self.check_params.get('threadId') == thread_id
                            or thread_id in self.uncertain_unsubscribes.values()):
                        self.early_closes[thread_id] = (side, payload, routing(message, side))
                    return
        if (side == "server" and thread_id in self.idle.sleeping
                and (message.get("method") == "thread/started" or
                     message.get("method") == "thread/status/changed" and
                     params["status"]["type"] == "notLoaded")):
            return
        route = routing(message, side)
        if side == 'server' and 'error' in message:
            request = self.client_requests.get(request_id)
            if request and request[0] == 'thread/backgroundTerminals/list':
                owner = request[1].get('threadId')
                if owner in self.idle.sleeping and message['error'].get('message') == f'thread not found: {owner}':
                    # The daemon only lists terminals on live runtimes. A parked, unloaded
                    # runtime cannot own background processes.
                    message = {'id': request_id, 'result': {'data': [], 'nextCursor': None}}
                    route, payload = routing(message, side), json.dumps(message).encode()
        if 'method' not in message and 'id' in message:
            other = 'client' if side == 'server' else 'server'
            owner = self.request_owners.get((other, message['id']))
            if owner:
                route['params']['threadId'] = owner
        self.events.put((side, payload, route))

    def run(self, owner_exited=None):
        writers = []
        for side, transport in (('client', self.client), ('server', self.upstream)):
            outgoing = ForwardQueue(self.request_byte_limit // 2)
            self.writers[side] = outgoing
            writer = threading.Thread(target=self.write_messages, args=(outgoing, transport), daemon=True)
            writer.start()
            writers.append(writer)
        readers = [threading.Thread(target=self.read, args=(side, transport), daemon=True)
                   for side, transport in (("client", self.client), ("server", self.upstream))]
        for reader in readers:
            reader.start()
        next_check = time.monotonic() + 1
        next_owner_check = 0
        try:
            while True:
                if owner_exited is not None and time.monotonic() >= next_owner_check:
                    if owner_exited():
                        break
                    next_owner_check = time.monotonic() + 1
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
                    if not self.stopped.is_set():
                        deadline = time.monotonic() + 2
                        for outgoing in self.writers.values():
                            with outgoing.all_tasks_done:
                                outgoing.all_tasks_done.wait_for(lambda: not outgoing.unfinished_tasks,
                                    timeout=max(0, deadline - time.monotonic()))
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
            for outgoing in self.writers.values():
                outgoing.put((None, None))
            for writer in writers:
                writer.join(timeout=2)

    def send(self, side, payload):
        if side in self.writers:
            try:
                self.writers[side].put_nowait((side, payload))
            except queue.Full as error:
                raise OSError('Proxy output buffer is full') from error
        else:
            (self.upstream if side == 'server' else self.client).send(payload)

    def write_messages(self, outgoing, transport):
        try:
            while True:
                _, payload = outgoing.get()
                try:
                    if payload is None:
                        return
                    transport.send(payload)
                finally:
                    outgoing.task_done()
                del payload
        except (OSError, EOFError, ValueError):
            self.close()

    def inspect_idle(self):
        now = time.monotonic()
        # An explicit resume belongs to the TUI. Its real response resolves it; after a
        # prolonged transport stall, let the TUI reconnect rather than inventing a rejection.
        if any(now >= deadline for deadline in self.explicit_resumes.values()):
            raise OSError('No response to the terminal resume request')
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
                    if self.check_method == 'thread/unsubscribe':
                        owner = self.check_params['threadId']
                        with self.unsubscribe_lock:
                            if not self.pending[self.check_id].empty():
                                return
                            if len(self.uncertain_unsubscribes) >= self.request_limit:
                                raise OSError('Too many unresolved unsubscribe responses')
                            self.uncertain_unsubscribes[self.check_id] = owner
                    self.cancel_inspection()
                return
            self.pending.pop(self.check_id)
            self.check_id = None
            if (self.check_method == 'thread/goal/get' and
                    response.get('error', {}).get('message') == 'goals feature is disabled'):
                response = {'result': {'goal': None}}
            if 'error' in response:
                if self.check_params.get('threadId') in self.early_closes:
                    self.events.put(self.early_closes.pop(self.check_params['threadId']))
                self.cancel_inspection(UsageUnavailable('Idle resource request failed'))
                return
            result = response['result']
            self.early_closes.pop(self.check_params.get('threadId'), None)
            self.check_method = None
        try:
            method, params = self.checks.send(result)
        except StopIteration:
            self.checks = None
            return
        self.check_params = params
        self.check_method = method
        self.check_deadline = now + 30
        self.check_id = self.begin_request(method, params)

    def begin_request(self, method, params):
        self.serial += 1
        request_id = self.prefix + str(self.serial)
        self.pending[request_id] = MaintenanceReply(self) if method == 'thread/resume' else queue.Queue(maxsize=1)
        self.send('server', json.dumps({'id': request_id, 'method': method, 'params': params}).encode())
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

    def wake_changed(self):
        self.wake_dirty = True

    def advance_wakes(self, now):
        if now < self.next_wake_check and not self.wake_dirty:
            return
        self.wake_dirty = False
        for target, (request_id, deadline) in list(self.wake_requests.items()):
            timed_out = False
            try:
                response = self.pending[request_id].get_nowait()
            except queue.Empty:
                if now < deadline:
                    continue
                timed_out = True
                response = {'error': {}}
            owners = ([owner for owner in self.wakeups if self.wake_target(owner) == target]
                      if 'error' in response else ())
            self.wake_requests.pop(target)
            self.pending.pop(request_id)
            if 'error' not in response:
                self.idle.sleeping.discard(target)
                self.wake_retry_limits.pop(target, None)
                self.retried_timeouts.discard(target)
                self.clear_uncertain_unsubscribe(target)
                self.idle.touch(target, now)
                continue
            detail = response['error'].get('message', '')
            gone = detail in (f'thread not found: {target}', f'no rollout found for thread id {target}',
                              'thread no longer available')
            retry_closing = ('is closing; retry' in detail and now < self.wake_retry_limits.get(target, now))
            retry_timeout = timed_out and target not in self.retried_timeouts
            if retry_timeout:
                self.retried_timeouts.add(target)
            elif not retry_closing:
                self.retried_timeouts.discard(target)
            for owner in owners:
                if retry_closing:
                    self.wakeups[owner] = now + .1
                    continue
                if retry_timeout:
                    self.wakeups[owner] = now + 5
                else:
                    self.wakeups.pop(owner, None)
                self.flush_deferred(owner, failed=True)
            if not retry_closing:
                self.wake_retry_limits.pop(target, None)
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
                params = self.idle.resume_params(target)
                end = self.wake_retry_limits.setdefault(target, now + 30)
                self.wake_requests[target] = self.begin_request('thread/resume', params), end
        future = [due for due in self.wakeups.values() if due > now]
        future.extend(end for _, end in self.wake_requests.values())
        self.next_wake_check = min(future, default=0)

    def inspect_threads(self, now):
        for thread_id in list(self.discoveries):
            try:
                thread = (yield 'thread/read', {'threadId': thread_id})['thread']
            finally:
                self.discoveries.pop(thread_id, None)
            if thread.get('parentThreadId') and thread_id not in self.idle.threads:
                self.idle.track({'thread': thread}, {}, time.monotonic())
            elif not thread.get('parentThreadId'):
                if len(self.external_roots) >= self.request_limit:
                    self.external_roots.pop(next(iter(self.external_roots)))
                self.external_roots[thread_id] = time.monotonic() + 300
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
        with self.unsubscribe_lock:
            unresolved = set(self.uncertain_unsubscribes.values())
            self.early_closes = {key: value for key, value in self.early_closes.items() if key in unresolved}
        self.check_method = None
        if self.check_id is not None:
            self.pending.pop(self.check_id, None)
            self.check_id = None

    def flush_deferred(self, thread_id, failed=False):
        for payload, message in self.deferred.pop(thread_id, ()):
            self.deferred_count -= 1
            self.deferred_bytes -= len(payload)
            if failed:
                self.send('client', json.dumps({'id': message['id'], 'error': {
                    'code': -32600, 'message': 'Could not resume the idle thread. Retry submission.',
                }}).encode())
            else:
                self.forward_client(message, payload)

    def close(self):
        self.stopped.set()
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
        if method and thread_id and method != 'thread/unarchive':
            if method not in READ_METHODS or thread_id in self.deferred or thread_id in self.resuming:
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
                        self.next_wake_check = 0
                    return
                if method == 'thread/resume' and thread_id in self.idle.sleeping:
                    self.resuming.add(thread_id)
                    self.explicit_resumes[thread_id] = time.monotonic() + 120
        if "id" in message:
            if method:
                self.retain_request('client', message['id'], len(payload), thread_id)
                self.client_requests[message["id"]] = (method, params)
                if not thread_id and method in GLOBAL_TRANSITIONS:
                    self.global_transitions[('client', message['id'])] = time.monotonic() + 30
            else:
                self.release_request('server', message['id'])
                self.server_requests.pop(message["id"], None)
        self.send('server', payload)

    def forward_server(self, message, payload):
        method, params = message.get("method"), message.get("params") or {}
        thread_id = params.get("threadId")
        if method in ('thread/archived', 'thread/deleted') or (method == 'thread/closed' and thread_id not in self.idle.sleeping):
            self.external_roots.pop(thread_id, None)
            self.explicit_resumes.pop(thread_id, None)
            for request_id, (operation, saved) in list(self.client_requests.items()):
                if operation == 'thread/resume' and saved.get('threadId') == thread_id:
                    self.client_requests.pop(request_id)
                    self.release_request('client', request_id)
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
            self.clear_uncertain_unsubscribe(thread_id)
            self.wake_retry_limits.pop(thread_id, None)
            self.retried_timeouts.discard(thread_id)
            self.resuming.discard(thread_id)
            self.discoveries.pop(thread_id, None)
            self.wakeups.pop(thread_id, None)
            self.flush_deferred(thread_id, failed=True)
        if (method == "thread/status/changed" and thread_id in self.idle.sleeping
                and params["status"]["type"] != "notLoaded"
                and (self.idle.threads[thread_id]["parent"] or params["status"]["type"] == "active")):
            # unload 유예 중 owner가 다시 시작한 자식은 자동 재구독되지 않는다.
            self.wakeups.setdefault(thread_id, 0)
            self.next_wake_check = 0
        if "id" in message:
            if method:
                self.retain_request('server', message['id'], len(payload), thread_id)
                self.server_requests[message["id"]] = thread_id
            else:
                self.release_request('client', message['id'])
                request = self.client_requests.pop(message["id"], None)
                if request and request[0] in ('thread/realtime/start', 'thread/realtime/stop') and 'result' in message:
                    self.realtime_changed(request[1].get('threadId'), request[0].endswith('/start'))
                if request and "result" in message and request[0] in ("thread/start", "thread/resume", "thread/fork"):
                    self.clear_uncertain_unsubscribe(message['result']['thread']['id'])
                    self.idle.track(message["result"], request[1], time.monotonic())
                    if request[0] != "thread/start" and not message["result"]["thread"].get("parentThreadId"):
                        # 기존 runtime의 evicted ephemeral 자식 상태는 RPC로 열거할 수 없다.
                        self.idle.preserve(message["result"]["thread"]["id"])
                if request and request[0] == "thread/unsubscribe" and "result" in message:
                    self.idle.forget(request[1].get("threadId"))
                if request and request[0] == "thread/resume":
                    owner = request[1].get("threadId")
                    self.resuming.discard(owner)
                    self.explicit_resumes.pop(owner, None)
                    self.flush_deferred(owner, failed="result" not in message)
        if method in ('thread/realtime/started', 'thread/realtime/closed'):
            self.realtime_changed(thread_id, method.endswith('/started'))
        if thread_id and method and (method == "thread/status/changed" or method.startswith(("thread/goal/", "thread/queue/"))):
            self.idle.touch(thread_id, time.monotonic())
        if thread_id and method in ("turn/started", "turn/completed", "item/started", "item/completed"):
            # owner가 자식을 다시 실행하면 서버가 이 연결을 자동으로 재구독시킨다.
            self.idle.sleeping.discard(thread_id)
            self.idle.touch(thread_id, time.monotonic())
        # 이 알림은 실제 sticky 설정이 달라질 때만 온다. 오래된 설정으로 resume하지 않는다.
        if method == "thread/settings/updated":
            self.idle.preserve(thread_id)
            if thread_id in self.idle.sleeping:
                self.idle.threads[thread_id]['params'] = {}
        if method == "serverRequest/resolved":
            self.release_request('server', params['requestId'])
            self.server_requests.pop(params["requestId"], None)
        # 자식부터 회수한다. parent의 loaded 자식 검사가 끝날 때까지 parent는 유지된다.
        if method == "thread/started":
            parent = params["thread"].get("parentThreadId")
            if parent and params["thread"]["id"] not in self.idle.threads:
                self.idle.track(params, {}, time.monotonic())
        elif (method == "thread/status/changed" and thread_id not in self.idle.threads
                and self.external_roots.get(thread_id, 0) <= time.monotonic()):
            if len(self.discoveries) >= self.request_limit:
                raise OSError('Too many undiscovered threads')
            self.discoveries[thread_id] = None
        self.send('client', payload)

    def clear_uncertain_unsubscribe(self, owner):
        with self.unsubscribe_lock:
            matches = [key for key, value in self.uncertain_unsubscribes.items() if value == owner]
            for key in matches:
                self.uncertain_unsubscribes.pop(key)
            if matches:
                self.early_closes.pop(owner, None)
            return bool(matches)

    def realtime_changed(self, owner, active):
        if owner in self.idle.threads:
            if active:
                self.idle.realtime.add(owner)
            else:
                self.idle.realtime.discard(owner)
            self.idle.touch(owner, time.monotonic())

    def retain_request(self, side, request_id, size, owner=None):
        key = (side, request_id)
        if (key in self.request_sizes or len(self.request_sizes) >= self.request_limit
                or self.request_bytes + size > self.request_byte_limit):
            raise OSError('Too many pending proxy requests')
        self.request_sizes[key] = size
        self.request_owners[key] = owner
        self.owner_counts[owner] += 1
        self.request_bytes += size

    def release_request(self, side, request_id):
        key = (side, request_id)
        self.global_transitions.pop(key, None)
        if key in self.request_owners:
            owner = self.request_owners.pop(key)
            self.owner_counts[owner] -= 1
            if not self.owner_counts[owner]:
                del self.owner_counts[owner]
        self.request_bytes -= self.request_sizes.pop((side, request_id), 0)


def start_proxy(upstream, delay):
    directory = Path(tempfile.mkdtemp(prefix="codex-idle-"))
    if len(os.fsencode(directory / 'tui.sock')) >= 104:
        directory.rmdir()
        directory = Path(tempfile.mkdtemp(prefix="codex-idle-", dir="/tmp"))
    endpoint = directory / "tui.sock"
    read_fd, write_fd = os.pipe()
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(upstream), str(endpoint), str(delay),
             str(os.getpid()), str(write_fd)], pass_fds=(write_fd,),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        os.close(write_fd)
        write_fd = None
        if select.select([read_fd], [], [], 10)[0] and os.read(read_fd, 1) == b'1' and process.poll() is None:
            return endpoint
        raise UsageUnavailable("Idle resource proxy did not start")
    except BaseException:
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        finally:
            if directory.exists():
                endpoint.unlink(missing_ok=True)
                endpoint.with_suffix('.json').unlink(missing_ok=True)
                directory.rmdir()
        raise
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def serve(upstream, endpoint, delay, owner_pid, ready_fd=None):
    endpoint = Path(endpoint)
    listener = socket.socket(socket.AF_UNIX)
    owner = select.kqueue()
    owner_finished = False
    identity = None
    def owner_exited():
        nonlocal owner_finished
        if not owner_finished:
            owner_finished = bool(owner.control([], 1, 0))
        return owner_finished
    status = {'pid': os.getpid(), 'owner_pid': owner_pid, 'started_at': time.time(),
              'source_revision': SOURCE_REVISION, 'connected': False, 'connections': 0}
    def record_status():
        try:
            save(status, endpoint.with_suffix('.json'))
        except OSError as error:
            print(f'Proxy status unavailable: {type(error).__name__}', file=sys.stderr)
    try:
        # Kernel registration follows this process incarnation, even after reparenting/PID reuse.
        owner.control([select.kevent(owner_pid, filter=select.KQ_FILTER_PROC,
                                     flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                     fflags=select.KQ_NOTE_EXIT)], 0, 0)
        listener.bind(str(endpoint))
        info = endpoint.stat()
        identity = (info.st_dev, info.st_ino)
        os.chmod(endpoint, 0o600)
        listener.listen(1)
        record_status()
        if ready_fd is not None:
            os.write(ready_fd, b'1')
            os.close(ready_fd)
            ready_fd = None
        listener.settimeout(1)
        while not owner_exited():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError as error:
                if error.errno not in (errno.ECONNABORTED, errno.ECONNRESET, errno.EINTR, errno.EAGAIN,
                                       errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM):
                    raise
                time.sleep(.2)
                continue
            server = None
            try:
                client = ClientSocket(connection, owner)
                server = UnixWebSocket(upstream, owner_watch=owner)
                status.update(connected=True, connections=status['connections'] + 1,
                              connected_at=time.time())
                record_status()
                # TUI가 새 initialize/resume로 복구한다. 이전 요청은 재전송하지 않는다.
                Proxy(client, server, delay).run(owner_exited)
            except (OSError, EOFError):
                # 서버가 아직 없거나 연결이 끊겨도 같은 주소로 다음 재접속을 받는다.
                pass
            finally:
                connection.close()
                if server:
                    server.close()
                status['connected'] = False
                record_status()
    finally:
        if ready_fd is not None:
            os.close(ready_fd)
        owner.close()
        listener.close()
        if identity is not None:
            try:
                current = endpoint.stat()
            except FileNotFoundError:
                pass
            else:
                if (current.st_dev, current.st_ino) == identity:
                    endpoint.unlink()
                    endpoint.with_suffix('.json').unlink(missing_ok=True)
                    endpoint.parent.rmdir()


if __name__ == "__main__":
    serve(sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]),
          int(sys.argv[5]) if len(sys.argv) > 5 else None)
