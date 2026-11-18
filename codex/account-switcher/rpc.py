"""JSON-RPC transport using the installed Codex binary and its Unix proxy."""

import json
import os
import queue
import subprocess
import threading

from policy import UsageUnavailable
from unix_ws import UnixWebSocket


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


class Rpc:
    def __init__(self, binary, home, socket_path=None, handler=None):
        self.process = self.websocket = None
        if socket_path:
            self.websocket = UnixWebSocket(socket_path)
        else:
            self.process = subprocess.Popen(
                [str(binary), "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=dict(os.environ, CODEX_HOME=str(home)),
            )
        self.handler = handler
        self.pending = {}
        self.lock = threading.Lock()
        self.serial = 0
        self.closed = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.request("initialize", {
                "clientInfo": {"name": "codex-account-switcher", "version": "2.0.0"},
                "capabilities": {"experimentalApi": True,
                                 "optOutNotificationMethods": list(NOTIFICATIONS)},
            })
            self.send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def send(self, message):
        with self.lock:
            if self.closed:
                raise UsageUnavailable("Codex connection is closed")
            try:
                payload = json.dumps(message).encode()
                if self.websocket:
                    self.websocket.send(payload)
                else:
                    self.process.stdin.write(payload + b"\n")
                    self.process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                raise UsageUnavailable("Codex connection ended") from error

    def request(self, method, params=None, timeout=30):
        with self.lock:
            self.serial += 1
            request_id = self.serial
            response = queue.Queue(maxsize=1)
            self.pending[request_id] = response
        try:
            self.send({"id": request_id, "method": method, "params": params or {}})
            try:
                message = response.get(timeout=timeout)
            except queue.Empty as error:
                raise UsageUnavailable(f"Codex {method} timed out") from error
            if "error" in message:
                raise UsageUnavailable(f"Codex {method} failed")
            return message.get("result") or {}
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def _read(self):
        try:
            source = self.websocket.messages() if self.websocket else self.process.stdout
            for line in source:
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if "method" in message and "id" in message:
                    threading.Thread(target=self._respond, args=(message,), daemon=True).start()
                elif "id" in message:
                    with self.lock:
                        target = self.pending.get(message["id"])
                    if target is not None:
                        target.put_nowait(message)
        except (OSError, EOFError, ValueError, queue.Full):
            pass
        finally:
            if self.websocket:
                self.websocket.close()
            with self.lock:
                # Nobody is left to deliver replies; later requests must fail now, not time out.
                self.closed = True
                for target in self.pending.values():
                    try:
                        target.put_nowait({"error": {"code": -1}})
                    except queue.Full:
                        pass

    def _respond(self, message):
        try:
            if self.handler is None:
                raise UsageUnavailable("No handler for this server request")
            result = self.handler(message["method"], message.get("params") or {})
            reply = {"id": message["id"], "result": result}
        except Exception:
            reply = {"id": message["id"], "error": {
                "code": -32603, "message": "Account refresh unavailable",
            }}
        try:
            self.send(reply)
        except (OSError, UsageUnavailable):
            pass

    def close(self):
        self.closed = True
        if self.websocket:
            self.websocket.close()
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.reader.join(timeout=1)
        if self.process:
            self.process.stdin.close()
            self.process.stdout.close()
