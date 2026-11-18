"""실제 모델 없이 수신 비용과 큰 알림 전달 뒤 중계기의 RSS를 비교한다."""

import argparse
import gc
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc


class Chunks:
    def __init__(self, size):
        self.remaining = size

    def recv(self, count):
        count = min(count, 16384, self.remaining)
        self.remaining -= count
        return b"x" * count


def receive(websocket, size):
    connection = object.__new__(websocket)
    connection.socket, connection.buffer = Chunks(size), b""
    tracemalloc.start()
    started = time.process_time()
    data = connection._read(size)
    elapsed = time.process_time() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert data == b"x" * size
    return {"size_mib": size >> 20, "cpu_seconds": elapsed, "peak_mib": peak / (1 << 20)}


def rss(pid):
    return int(subprocess.check_output(['ps', '-o', 'rss=', '-p', str(pid)], text=True)) / 1024


def traced_memory(process):
    process.send_signal(signal.SIGUSR1)
    if not select.select([process.stdout], [], [], 5)[0]:
        raise TimeoutError('proxy memory sample')
    current, peak = json.loads(process.stdout.readline())
    return {'current_mib': current / (1 << 20), 'peak_mib': peak / (1 << 20)}


def forward(source, websocket, client_socket, size, trace):
    with tempfile.TemporaryDirectory(prefix="idle-probe-", dir="/tmp") as directory:
        root = Path(directory)
        upstream, endpoint = root / "server.sock", root / "proxy" / "tui.sock"
        endpoint.parent.mkdir()
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(upstream))
        listener.listen(1)
        listener.settimeout(10)
        command = [str(source / 'idle.py'), str(upstream), str(endpoint), '900', str(os.getpid())]
        if trace:
            wrapper = '''import json, runpy, signal, sys, tracemalloc
from pathlib import Path
target = sys.argv.pop(1)
sys.argv[0] = target
sys.path.insert(0, str(Path(target).resolve().parent))
signal.signal(signal.SIGUSR1, lambda *_: print(json.dumps(tracemalloc.get_traced_memory()), flush=True))
tracemalloc.start()
runpy.run_path(target, run_name="__main__")
'''
            command = ['-c', wrapper, *command]
        process = subprocess.Popen([sys.executable, *command],
                                   stdout=subprocess.PIPE if trace else subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        client = server = None
        try:
            deadline = time.monotonic() + 10
            while not endpoint.exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise TimeoutError('proxy startup')
                threading.Event().wait(.01)
            client = websocket(endpoint)
            client.message_limit = client_socket.message_limit
            client.socket.settimeout(45)
            server = client_socket(listener.accept()[0])
            server.socket.settimeout(45)
            before = rss(process.pid)
            traced_before = traced_memory(process) if trace else None
            payload = json.dumps({'method': 'turn/diff/updated', 'params': {
                'threadId': 'fixture-thread', 'diff': 'x' * size,
            }}).encode()
            sent = threading.Event()

            def send():
                try:
                    server.send(payload)
                finally:
                    sent.set()

            sender = threading.Thread(target=send, daemon=True)
            started = time.monotonic()
            sender.start()
            received = next(client.messages())
            assert json.loads(received) == json.loads(payload)
            assert sent.wait(5)
            sender.join(timeout=5)
            elapsed = time.monotonic() - started
            # 다음 작은 프레임으로 reader를 진행시키면 참조 잔류를 숨기므로 추가 통신 없이 잰다.
            del received, payload
            gc.collect()
            samples = []
            for _ in range(3):
                threading.Event().wait(.1)
                samples.append(rss(process.pid))
            result = {'size_mib': size >> 20, 'elapsed_seconds': elapsed,
                      'rss_before_mib': before, 'rss_after_mib': samples}
            if trace:
                result.update(traced_before=traced_before, traced_after=traced_memory(process))
            return result
        finally:
            if client:
                client.close()
            if server:
                server.close()
            listener.close()
            process.terminate()
            process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path(__file__).parent)
    parser.add_argument('--proxy', action='store_true')
    parser.add_argument('--trace', action='store_true')
    parser.add_argument('--mib', type=int, default=32)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from idle import ClientSocket
    from unix_ws import UnixWebSocket
    if args.proxy:
        result = forward(args.source, UnixWebSocket, ClientSocket, args.mib << 20, args.trace)
    else:
        result = receive(UnixWebSocket, args.mib << 20)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
