"""Small RFC 6455 client for Codex's local Unix socket; no external listener."""

import base64
import hashlib
import os
import select
import socket
import struct
import threading
import time


XOR_TABLES = tuple(bytes(value ^ key for value in range(256)) for key in range(256))
WRITE_TIMEOUT = 30


def write_all(connection, parts, deadline):
    if not isinstance(connection, int) and connection.getblocking():
        connection.setblocking(False)
    for data in parts:
        remaining = memoryview(data)
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0 or not select.select([], [connection], [], timeout)[1]:
                raise TimeoutError('Codex transport write timed out')
            try:
                if isinstance(connection, int):
                    count = os.write(connection, remaining)
                else:
                    count = connection.send(remaining)
            except BlockingIOError:
                continue
            if not count:
                raise OSError('Codex transport closed while writing')
            remaining = remaining[count:]


def mask_payload(data, mask):
    result = bytearray(data)
    for index, key in enumerate(mask):
        result[index::4] = data[index::4].translate(XOR_TABLES[key])
    return result


class UnixWebSocket:
    message_limit = 16 * 1024 * 1024
    fragment_limit = 4096

    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.lock = threading.Lock()
        self.buffer = b""
        try:
            self.socket.settimeout(10)
            self.socket.connect(str(path))
            key = base64.b64encode(os.urandom(16)).decode()
            request = ("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                       "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
                       f"Sec-WebSocket-Key: {key}\r\n\r\n")
            self.socket.sendall(request.encode())
            while b"\r\n\r\n" not in self.buffer:
                chunk = self.socket.recv(4096)
                if not chunk or len(self.buffer) > 16384:
                    raise OSError("Invalid Codex socket handshake")
                self.buffer += chunk
            header, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
            lines = header.decode("ascii").split("\r\n")
            headers = {name.strip().lower(): value.strip()
                       for name, value in (line.split(":", 1) for line in lines[1:] if ":" in line)}
            expected = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()).decode()
            if " 101 " not in lines[0] or headers.get("sec-websocket-accept", "") != expected:
                raise OSError("Codex socket refused the WebSocket handshake")
            self.socket.settimeout(None)
        except Exception:
            self.socket.close()
            raise

    def send_frame(self, opcode, data, deadline=None):
        length = len(data)
        if length < 126:
            header = bytes([0x80 | opcode, 0x80 | length])
        elif length < 65536:
            header = bytes([0x80 | opcode, 0xFE]) + struct.pack("!H", length)
        else:
            header = bytes([0x80 | opcode, 0xFF]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = mask_payload(data, mask)
        self.write((header + mask, masked), deadline)

    def write(self, parts, deadline=None):
        deadline = time.monotonic() + WRITE_TIMEOUT if deadline is None else deadline
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise TimeoutError('Codex transport write lock timed out')
        try:
            write_all(self.socket, parts, deadline)
        finally:
            self.lock.release()

    def send(self, data, deadline=None):
        self.send_frame(1, data, deadline)

    def _read(self, count):
        buffered, self.buffer = self.buffer[:count], self.buffer[count:]
        chunks = [buffered]
        remaining = count - len(buffered)
        while remaining:
            try:
                data = self.socket.recv(max(4096, min(65536, remaining)))
            except BlockingIOError:
                select.select([self.socket], [], [])
                continue
            if not data:
                raise EOFError("Codex socket closed")
            chunks.append(data[:remaining])
            self.buffer = data[remaining:]
            remaining -= len(chunks[-1])
        return b"".join(chunks)

    def messages(self):
        chunks = []
        message_size = 0
        while True:
            first, second = self._read(2)
            opcode, final = first & 15, bool(first & 128)
            if first & 112:
                raise OSError("Unexpected WebSocket extension")
            length = second & 127
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if (length > self.message_limit
                    or (opcode in (0, 1) and message_size + length > self.message_limit)):
                raise OSError("Oversized Codex socket message")
            if opcode in (0, 1) and len(chunks) >= self.fragment_limit:
                raise OSError('Too many Codex socket fragments')
            mask = self._read(4) if second & 128 else None
            data = self._read(length)
            if mask:
                data = mask_payload(data, mask)
            if opcode == 8:
                return
            if opcode == 9:
                self.send_frame(10, data)
                continue
            if opcode == 10:
                continue
            if opcode != (0 if chunks else 1):
                raise OSError("Invalid Codex socket frame sequence")
            chunks.append(data)
            message_size += len(data)
            del data
            if final:
                payload = b"".join(chunks)
                chunks, message_size = [], 0
                yield payload
                del payload

    def close(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
