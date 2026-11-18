"""가짜 stdio MCP로 생성·종료·reload·지연 시작을 측정하는 로컬 격리 실험."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from rpc import Rpc


def worker():
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' not in request:
            continue
        method = request['method']
        if method == 'initialize':
            result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'fd-probe', 'version': '1'}}
        elif method == 'tools/list':
            result = {'tools': [{'name': 'pid', 'description': 'Report the isolated fixture PID',
                                 'inputSchema': {'type': 'object', 'properties': {}}}]}
        elif method == 'tools/call':
            result = {'content': [{'type': 'text', 'text': str(os.getpid())}]}
        else:
            result = {'resources': [], 'resourceTemplates': [], 'prompts': []}
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)


def descriptors(pid):
    output = subprocess.run(['lsof', '-nP', '-a', '-p', str(pid), '-F', 'ft'],
                            capture_output=True, text=True).stdout
    types = Counter()
    numeric = False
    for line in output.splitlines():
        if line.startswith('f'):
            numeric = line[1:].isdigit()
        elif line.startswith('t') and numeric:
            types[line[1:]] += 1
    return types


def sample(pid):
    types = descriptors(pid)
    processes = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,comm='], text=True)
    children = []
    for line in processes.splitlines():
        parts = line.split(None, 2)
        if int(parts[1]) == pid:
            child_types = descriptors(int(parts[0]))
            children.append({'pid': int(parts[0]), 'command': parts[2],
                             'fds':sum(child_types.values()),'types':dict(child_types)})
    return {'pid': pid, 'fds': sum(types.values()), 'types': dict(types), 'children': children}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lazy', action='store_true')
    parser.add_argument('--cycles', type=int, default=12)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='codex-fd-probe-', dir='/private/tmp') as directory:
        root = Path(directory)
        (root / 'config.toml').write_text(f'''model = "gpt-5.1"
model_provider = "fixture"
thread_unload_delay_secs = 1
[model_providers.fixture]
name = "fixture"
base_url = "http://127.0.0.1:9/v1"
wire_api = "responses"
[features]
apps = false
[mcp_servers.probe]
command = "/opt/homebrew/bin/python3"
args = [{json.dumps(str(Path(__file__).resolve()))}, "--worker"]
''')
        if args.lazy:
            config = root / 'config.toml'
            config.write_text(config.read_text().replace('apps = false', 'apps = false\nmcp_lazy_stdio_startup = true'))
        client = Rpc('/opt/homebrew/bin/codex', root)
        records = []
        try:
            def record(label):
                value = sample(client.process.pid)
                value.update(label=label, loaded=client.request('thread/loaded/list')['data'])
                records.append(value)
                print(json.dumps(value), flush=True)
                return value

            record('baseline')
            for cycle in range(args.cycles):
                thread = client.request('thread/start', {'cwd': directory})['thread']['id']
                if args.lazy:
                    time.sleep(.5)
                    record(f'before_tool-{cycle}')
                result = client.request('mcpServer/tool/call', {
                    'threadId': thread, 'server': 'probe', 'tool': 'pid', 'arguments': {}})
                mcp_pid = int(result['content'][0]['text'])
                record(f'loaded-{cycle}')
                if cycle == 0:
                    for refresh in range(8):
                        client.request('config/mcpServer/reload')
                        client.request('mcpServer/tool/call', {
                            'threadId': thread, 'server': 'probe', 'tool': 'pid', 'arguments': {}})
                        record(f'reload-{refresh}')
                client.request('thread/unsubscribe', {'threadId': thread})
                deadline = time.monotonic() + 15
                while client.request('thread/loaded/list')['data']:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('unload did not finish')
                    time.sleep(.1)
                after = record(f'unloaded-{cycle}')
                assert all(child['pid'] != mcp_pid for child in after['children']), after
        finally:
            client.close()
            output = '/private/tmp/codex-lazy-result.json' if args.lazy else '/private/tmp/codex-lifecycle-result.json'
            Path(output).write_text(json.dumps(records, indent=2))


if __name__ == '__main__':
    if '--worker' in sys.argv:
        worker()
    else:
        main()
