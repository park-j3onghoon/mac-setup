"""JSON-RPC transport using the installed Codex binary and its Unix proxy."""

import json
import inspect
import os
import queue
import re
import select
import subprocess
import threading
import time
import weakref

from policy import UsageUnavailable
from unix_ws import UnixWebSocket, WRITE_TIMEOUT, write_all


SERVER_REQUEST_LIMIT = 8
HANDLER_CAPACITY = threading.BoundedSemaphore(SERVER_REQUEST_LIMIT * 2)
# The app-server subscribes every initialized connection to the threads it creates itself
# (sub-agents; app-server/src/lib.rs in 0.169.0). On 2026-11-18 one sub-agent's turn/diff/updated,
# the whole diff of a turn that added 84 MB of files, passed the 16 MiB frame limit and ended the
# reader. This client reads no notifications, so it declines every method that
# `codex app-server generate-json-schema` lists for 0.169.0.
NOTIFICATIONS = (
    "account/gatewayOAuth/changed", "account/login/completed", "account/rateLimits/updated",
    "account/updated", "app/list/updated", "autoApprovalReview/strictReviewRequired",
    "command/exec/outputDelta", "configWarning", "deprecationNotice", "error",
    "externalAgentConfig/import/completed", "externalAgentConfig/import/progress", "fs/changed",
    "fuzzyFileSearch/sessionCompleted", "fuzzyFileSearch/sessionUpdated", "guardianWarning",
    "hook/completed", "hook/started", "item/agentMessage/delta",
    "item/autoApprovalReview/completed", "item/autoApprovalReview/started",
    "item/commandExecution/outputDelta", "item/commandExecution/terminalInteraction",
    "item/completed", "item/fileChange/outputDelta", "item/fileChange/patchUpdated",
    "item/mcpToolCall/progress", "item/plan/delta", "item/reasoning/summaryPartAdded",
    "item/reasoning/summaryTextDelta", "item/reasoning/textDelta", "item/started",
    "mcpServer/event/stream/notification", "mcpServer/oauthLogin/completed",
    "mcpServer/startupStatus/updated", "model/rerouted", "model/safetyBuffering/updated",
    "model/verification", "modelProvider/authRecoveryCompleted",
    "modelProvider/authRecoveryStarted", "process/exited", "process/outputDelta", "project/changed",
    "remoteControl/status/changed", "serverRequest/resolved", "skills/changed", "thread/archived",
    "thread/attachment/updated", "thread/closed", "thread/compacted", "thread/deleted",
    "thread/environment/connected", "thread/environment/disconnected", "thread/goal/cleared",
    "thread/goal/updated", "thread/name/updated", "thread/prediction/updated",
    "thread/project/updated", "thread/queue/changed", "thread/readState/changed",
    "thread/realtime/closed", "thread/realtime/error", "thread/realtime/item/completed",
    "thread/realtime/item/started", "thread/realtime/item/transcript/delta",
    "thread/realtime/itemAdded", "thread/realtime/outputAudio/delta", "thread/realtime/sdp",
    "thread/realtime/started", "thread/realtime/transcript/delta",
    "thread/realtime/transcript/done", "thread/reverted", "thread/section/changed",
    "thread/settings/updated", "thread/started", "thread/status/changed",
    "thread/tokenUsage/updated", "thread/unarchived", "turn/completed", "turn/diff/updated",
    "turn/moderationMetadata", "turn/plan/updated", "turn/started", "warning",
    "windows/worldWritableWarning", "windowsSandbox/setupCompleted",
)


class RpcRejected(UsageUnavailable):
    """The server explicitly rejected the request; a transport failure is uncertain."""

    no_history = False
    thread_missing = False


class RpcNotSent(UsageUnavailable):
    """The transport failed before writing any of this request."""


def version_from_initialize(result):
    agent = result.get("userAgent") if isinstance(result, dict) else None
    if isinstance(agent, str):
        match = re.match(r"[^/\s]+/([0-9][A-Za-z0-9.+-]*)(?:\s|$)", agent)
        if match:
            return match[1]
    return None


class Rpc:
    def __init__(self, binary, home, socket_path=None, handler=None, notification=None, *, cancel=None):
        self.process = self.websocket = None
        self.closing = threading.Event()
        self.workers = set()
        self.cleanup_lock = threading.Lock()
        self.timeouts = 0
        if socket_path:
            self.websocket = UnixWebSocket(socket_path)
        else:
            self.process = subprocess.Popen(
                [str(binary), "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=dict(os.environ, CODEX_HOME=str(home)),
            )
        self.handler = handler
        self.notification = notification
        self.pending = {}
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.handlers = threading.BoundedSemaphore(SERVER_REQUEST_LIMIT)
        self.serial = 0
        self.closed = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        try:
            if self.process:
                os.set_blocking(self.process.stdin.fileno(), False)
            self.reader.start()
            result = self.request("initialize", {
                "clientInfo": {"name": "codex-account-switcher", "version": "2.0.0"},
                "capabilities": {"experimentalApi": True,
                                 "optOutNotificationMethods": [method for method in NOTIFICATIONS
                                     if not notification or method not in (
                                         'thread/status/changed', 'thread/started', 'turn/started',
                                         'thread/queue/changed', 'thread/goal/updated', 'thread/goal/cleared',
                                         'turn/completed')]},
            }, cancel=cancel)
            self.version = version_from_initialize(result)
            self.send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def send(self, message, deadline=None, *, cancel=None):
        deadline = time.monotonic() + WRITE_TIMEOUT if deadline is None else deadline
        while True:
            remaining = max(0, deadline - time.monotonic())
            if remaining == 0 or cancel is not None and cancel.is_set():
                raise RpcNotSent('Codex write lock timed out')
            if self.write_lock.acquire(timeout=min(.05, remaining) if cancel is not None else remaining):
                break
        try:
            if self.closed:
                raise RpcNotSent("Codex connection is closed")
            try:
                payload = json.dumps(message).encode()
                if self.websocket:
                    self.websocket.send(payload, deadline=deadline)
                else:
                    write_all(self.process.stdin.fileno(), (payload + b'\n',), deadline, cancel)
            except (ValueError, OSError) as error:
                self.closed = True
                self.closing.set()
                if self.websocket:
                    self.websocket.close()
                elif self.process:
                    self.process.terminate()
                if getattr(error, 'bytes_written', 0 if isinstance(error, ValueError) else None) == 0:
                    raise RpcNotSent("Codex request was not sent") from error
                raise UsageUnavailable("Codex connection ended") from error
        finally:
            self.write_lock.release()

    def request(self, method, params=None, timeout=30, *, cancel=None):
        deadline = time.monotonic() + timeout
        with self.lock:
            self.serial += 1
            request_id = self.serial
            response = queue.Queue(maxsize=1)
            self.pending[request_id] = response
        try:
            message = {"id": request_id, "method": method, "params": params or {}}
            if cancel is None:
                self.send(message, deadline)
            else:
                self.send(message, deadline, cancel=cancel)
            try:
                while True:
                    remaining = max(0, deadline - time.monotonic())
                    if cancel is not None and cancel.is_set():
                        raise UsageUnavailable('Codex request cancelled')
                    try:
                        message = response.get(timeout=min(.05, remaining) if cancel is not None else remaining)
                        break
                    except queue.Empty:
                        if cancel is None or time.monotonic() >= deadline:
                            raise
            except queue.Empty as error:
                if method.endswith(('/read', '/list', '/get')):
                    with self.lock:
                        self.timeouts += 1
                        stalled = self.timeouts >= 2
                    if stalled:
                        self.close()
                raise UsageUnavailable(f"Codex {method} timed out") from error
            if message.get('_connection_closed'):
                raise UsageUnavailable('Codex connection ended')
            with self.lock:
                self.timeouts = 0
            if "error" in message:
                rejected = RpcRejected(f"Codex {method} failed")
                if method == 'thread/read':
                    thread_id = (params or {}).get('threadId')
                    detail = message['error'].get('message')
                    rejected.thread_missing = (detail in (f'no rollout found for thread id {thread_id}',
                                                          f'thread not found: {thread_id}')
                                               or not (params or {}).get('includeTurns')
                                               and detail == f'thread not loaded: {thread_id}')
                if method == 'thread/turns/list':
                    thread_id = (params or {}).get('threadId')
                    rejected.no_history = message['error'].get('message') == (
                        f'thread {thread_id} is not materialized yet; '
                        'thread/turns/list is unavailable before first user message')
                raise rejected
            return message.get("result") or {}
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def _read(self):
        try:
            source = self.websocket.messages() if self.websocket else self.stdio_lines()
            for line in source:
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    del line
                    continue
                if "method" in message and "id" in message:
                    if not self.handlers.acquire(blocking=False):
                        raise UsageUnavailable('Too many pending server requests')
                    if not HANDLER_CAPACITY.acquire(blocking=False):
                        self.handlers.release()
                        raise UsageUnavailable('Server request workers are busy')
                    worker = threading.Thread(target=Rpc.respond, args=(
                        weakref.ref(self), self.handler, self.closing, self.handlers, message), daemon=True)
                    try:
                        with self.lock:
                            self.workers.add(worker)
                        worker.start()
                    except RuntimeError:
                        with self.lock:
                            self.workers.discard(worker)
                        self.handlers.release()
                        HANDLER_CAPACITY.release()
                        raise
                elif "id" in message:
                    with self.lock:
                        target = self.pending.get(message["id"])
                    if target is not None:
                        target.put_nowait(message)
                elif self.notification and 'method' in message:
                    self.notification(message['method'], message.get('params') or {})
                del message, line
        except (OSError, EOFError, ValueError, queue.Full):
            pass
        finally:
            self.closing.set()
            if self.websocket:
                self.websocket.close()
            with self.lock:
                # Nobody is left to deliver replies; later requests must fail now, not time out.
                self.closed = True
                for target in self.pending.values():
                    try:
                        target.put_nowait({'_connection_closed': True})
                    except queue.Full:
                        pass
            if self.process:
                self.close_process()

    def stdio_lines(self):
        fd = self.process.stdout.fileno()
        buffered = bytearray()
        while not self.closing.is_set():
            if not select.select([fd], [], [], .05)[0]:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                return
            buffered.extend(chunk)
            start = 0
            while (end := buffered.find(b'\n', start)) != -1:
                yield buffered[start:end]
                start = end + 1
            del buffered[:start]

    @staticmethod
    def respond(owner, handler, cancelled, slots, message):
        try:
            if handler is None or cancelled.is_set():
                raise UsageUnavailable("No handler for this server request")
            args = (message["method"], message.get("params") or {})
            if 'cancel' in inspect.signature(handler).parameters:
                result = handler(*args, cancel=cancelled)
            else:
                result = handler(*args)
            reply = {"id": message["id"], "result": result}
        except Exception:
            reply = {"id": message["id"], "error": {
                "code": -32603, "message": "Account refresh unavailable",
            }}
        try:
            connection = owner()
            if connection and not cancelled.is_set():
                connection.send(reply)
        except (OSError, UsageUnavailable):
            pass
        finally:
            connection = owner()
            if connection:
                with connection.lock:
                    connection.workers.discard(threading.current_thread())
            slots.release()
            HANDLER_CAPACITY.release()

    def close(self):
        self.closed = True
        self.closing.set()
        if self.websocket:
            self.websocket.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        if self.reader.ident is not None and self.reader is not threading.current_thread():
            self.reader.join(timeout=.5)
        if self.process:
            self.close_process()
        with self.lock:
            workers = tuple(self.workers)
        deadline = time.monotonic() + 1
        for worker in workers:
            if worker is not threading.current_thread() and worker.ident is not None:
                worker.join(timeout=max(0, deadline - time.monotonic()))

    def close_process(self):
        with self.cleanup_lock:
            if self.process.stdin.closed and self.process.stdout.closed:
                return
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
