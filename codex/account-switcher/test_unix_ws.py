import struct
import threading
import unittest

from unix_ws import UnixWebSocket


class Socket:
    def __init__(self, incoming=b""):
        self.incoming = incoming
        self.sent = b""

    def recv(self, count):
        result, self.incoming = self.incoming[:count], self.incoming[count:]
        return result

    def sendall(self, data):
        self.sent += data


def connection(incoming=b""):
    client = object.__new__(UnixWebSocket)
    client.socket = Socket(incoming)
    client.buffer = b""
    client.lock = threading.Lock()
    return client


class WebSocketTest(unittest.TestCase):
    def test_fragmented_messages_and_ping_are_handled(self):
        client = connection(b'\x01\x02{"' + b'\x89\x01p' + b'\x00\x04a":1' + b'\x80\x01}')
        self.assertEqual(next(client.messages()), b'{"a":1}')
        self.assertEqual(client.socket.sent[0], 0x8A)

    def test_short_medium_and_long_client_frames_are_masked(self):
        for size in (5, 300, 70000):
            with self.subTest(size=size):
                client = connection()
                data = b"x" * size
                client.send(data)
                frame = client.socket.sent
                self.assertEqual(frame[0], 0x81)
                self.assertTrue(frame[1] & 128)
                offset = 2 if size < 126 else 4 if size < 65536 else 10
                mask, encoded = frame[offset:offset + 4], frame[offset + 4:]
                self.assertEqual(bytes(value ^ mask[i % 4] for i, value in enumerate(encoded)), data)

    def test_extended_server_frame_is_read(self):
        data = b"x" * 300
        client = connection(b'\x81\x7e' + struct.pack("!H", len(data)) + data)
        self.assertEqual(next(client.messages()), data)

    def test_oversize_is_rejected_before_reading_payload(self):
        client = connection(b'\x81\x7f' + struct.pack("!Q", 20 * 1024 * 1024))
        with self.assertRaises(OSError):
            next(client.messages())

    def test_invalid_continuation_is_rejected(self):
        with self.assertRaises(OSError):
            next(connection(b'\x80\x01x').messages())


if __name__ == "__main__":
    unittest.main()
