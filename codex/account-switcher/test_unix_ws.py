import struct
import threading
import unittest
from unittest.mock import patch

from unix_ws import UnixWebSocket


class Socket:
    def __init__(self, incoming=b""):
        self.incoming = incoming
        self.sent = b""

    def recv(self, count):
        result, self.incoming = self.incoming[:count], self.incoming[count:]
        return result

    def getblocking(self):
        return False

    def send(self, data):
        self.sent += data
        return len(data)


def connection(incoming=b""):
    client = object.__new__(UnixWebSocket)
    client.socket = Socket(incoming)
    client.buffer = b""
    client.lock = threading.Lock()
    return client


class WebSocketTest(unittest.TestCase):
    def test_empty_fragment_flood_is_rejected(self):
        """내용이 없는 fragment도 개수 상한을 넘으면 중단해 byte 상한 우회를 막는다."""
        client = connection(b'\x01\x00' + b'\x00\x00' * 4096 + b'\x80\x00')

        with self.assertRaises(OSError):
            next(client.messages())

    def setUp(self):
        ready = patch('unix_ws.select.select', side_effect=lambda read, write, *_: (read, write, []))
        ready.start()
        self.addCleanup(ready.stop)

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

    def test_masked_fragment_bytes_survive_unaligned_lengths(self):
        """여러 바이트 값·4바이트 경계 밖 길이의 masked frame을 원문 그대로 받는다."""
        for size in (0, 1, 3, 4, 5, 125, 300, 65537):
            with self.subTest(size=size):
                data = (bytes(range(256)) * (size // 256 + 1))[:size]
                sender = connection()
                sender.send(data)
                receiver = connection(sender.socket.sent)

                received = next(receiver.messages())

                self.assertEqual(received, data)

    def test_oversize_is_rejected_before_reading_payload(self):
        client = connection(b'\x81\x7f' + struct.pack("!Q", 20 * 1024 * 1024))
        with self.assertRaises(OSError):
            next(client.messages())

    def test_invalid_continuation_is_rejected(self):
        with self.assertRaises(OSError):
            next(connection(b'\x80\x01x').messages())

    def test_fragment_limit_is_checked_before_reading_continuation_payload(self):
        """앞 조각과 합쳐 한도를 넘는 continuation은 본문을 받기 전에 거절한다."""
        client = connection(b'\x01\x03abc' + b'\x80\x03')
        client.message_limit = 5

        with self.assertRaisesRegex(OSError, "Oversized"):
            next(client.messages())

    def test_coalesced_frames_and_partial_reads_preserve_messages(self):
        """한 번에 들어온 프레임과 여러 번 나뉜 읽기 모두 메시지 경계를 유지한다."""
        client = connection(b'\x81\x03one' + b'\x81\x03two')
        original_recv = client.socket.recv
        client.socket.recv = lambda count: original_recv(min(count, 1))

        messages = client.messages()
        first, second = next(messages), next(messages)

        self.assertEqual((first, second), (b'one', b'two'))

    def test_handshake_buffer_and_following_socket_bytes_preserve_frames(self):
        """handshake와 함께 온 프레임·다음 프레임 일부를 소켓의 남은 바이트와 연결한다."""
        client = connection(b'wo')
        client.buffer = b'\x81\x03one\x81\x03t'

        messages = client.messages()
        first, second = next(messages), next(messages)

        self.assertEqual((first, second), (b'one', b'two'))


if __name__ == "__main__":
    unittest.main()
