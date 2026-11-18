"""가짜 로컬 Responses·MCP로 구독 잔류와 유휴 회수의 작업·기록 보존을 검증한다."""

import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from rpc import Rpc
from policy import UsageUnavailable
from probe_lifecycle import sample
from idle import start_proxy


class Model(http.server.BaseHTTPRequestHandler):
    count = 0
    mail_seen = False
    release = threading.Event()

    def log_message(self, *args):
        pass

    def do_POST(self):
        request_body = self.rfile.read(int(self.headers['Content-Length']))
        if not self.path.endswith('/responses'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{}')
            return
        type(self).count += 1
        request = json.loads(request_body)
        users = [i for i in request.get('input', []) if i.get('role') == 'user']
        last_user = ''.join(c.get('text','') for c in users[-1].get('content',[])) if users else ''
        calls = {i.get('call_id') for i in request.get('input',[]) if i.get('type')=='function_call'}
        if last_user == 'Hold fixture active':
            type(self).release.wait(timeout=15)
        if 'QUEUED_RESOURCE_SENTINEL' in request_body.decode() and last_user not in ('Spawn child','Queue fixture mail','Resume fixture child'):
            type(self).mail_seen = True
        if ('Start fixture background' in request_body.decode()
                and not calls.intersection({'background-fixture', 'restart-fixture'})):
            item = {'type':'function_call','call_id':'background-fixture',
                    'name':'exec_command','arguments':json.dumps({'cmd':'sleep 30','yield_time_ms':1000})}
        elif last_user == 'Queue fixture mail' and 'queue-fixture' not in calls:
            item = {'type':'function_call','call_id':'queue-fixture','namespace':'collaboration',
                    'name':'send_message','arguments':json.dumps({'target':'fixture_child','message':'QUEUED_RESOURCE_SENTINEL'})}
        elif last_user == 'Resume fixture child' and 'wake-fixture' not in calls:
            item = {'type':'function_call','call_id':'wake-fixture','namespace':'collaboration',
                    'name':'followup_task','arguments':json.dumps({'target':'fixture_child','message':'Return queued mail'})}
        elif last_user == 'Restart fixture child' and 'restart-fixture' not in calls:
            item = {'type':'function_call','call_id':'restart-fixture','namespace':'collaboration',
                    'name':'followup_task','arguments':json.dumps({'target':'fixture_child','message':'Start fixture background'})}
        elif self.count == 1 and ('--proxy' not in sys.argv or '--child' in sys.argv):
            item = {'type': 'function_call', 'call_id': 'spawn', 'namespace': 'collaboration',
                    'name': 'spawn_agent', 'arguments': json.dumps({
                        'task_name': 'fixture_child', 'message': 'Reply done', 'fork_turns': 'none'})}
        else:
            item = {'type': 'message', 'role': 'assistant', 'id': 'msg',
                    'content': [{'type': 'output_text', 'text': 'Fixture done'}]}
        events = [{'type': 'response.created', 'response': {'id': f'r{self.count}'}},
                  {'type': 'response.output_item.done', 'item': item},
                  {'type': 'response.completed', 'response': {'id': f'r{self.count}',
                   'usage': {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}}}]
        body = ''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def wait_turn(client, thread_id, turn_id):
    deadline=time.monotonic()+20
    while True:
        if client.request('thread/read', {'threadId': thread_id})['thread']['status']['type'] == 'active':
            if time.monotonic()>deadline:raise TimeoutError('fixture active turn')
            time.sleep(.1)
            continue
        try:
            turns=client.request('thread/turns/list',{'threadId':thread_id,'limit':20,'sortDirection':'desc','itemsView':'notLoaded'})['data']
        except UsageUnavailable:
            turns=[]
        for turn in turns:
            if turn['id'] == turn_id and turn['status'] in ('completed', 'failed', 'interrupted'):
                # 0.169.0은 live 상태보다 먼저 읽은 미완료 기록을 interrupted로 정규화한다.
                if turn['status'] == 'interrupted' and turn['completedAt'] is None:
                    continue
                assert turn['status'] == 'completed', turn
                return
        if time.monotonic()>deadline:raise TimeoutError('fixture turn')
        time.sleep(.1)


def main():
    with tempfile.TemporaryDirectory(prefix='codex-subscription-', dir='/private/tmp') as directory:
        model = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Model)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        root = Path(directory)
        (root/'config.toml').write_text(f'''model = "gpt-5.1"
    model_provider = "fixture"
thread_unload_delay_secs = {5 if '--child-restart' in sys.argv else 1}
    approvals_reviewer = "user"
    [model_providers.fixture]
    name = "fixture"
    base_url = "http://127.0.0.1:{model.server_port}/v1"
    wire_api = "responses"
    [features]
    apps = false
    multi_agent = true
    multi_agent_v2 = true
    [mcp_servers.probe]
    command = "/opt/homebrew/bin/python3"
    args = [{json.dumps(str(Path(__file__).with_name("probe_lifecycle.py")))}, "--worker"]
    ''')
        sock = root/'s.sock'
        p = subprocess.Popen(['/opt/homebrew/bin/codex', 'app-server', '--listen', 'unix://'+str(sock)],
                             env=dict(os.environ, CODEX_HOME=directory), stdout=subprocess.DEVNULL,
                             stderr=(root/'stderr').open('w'))
        owner = observer = None
        records = []
        try:
            deadline = time.monotonic()+15
            while not sock.exists():
                if time.monotonic()>deadline: raise TimeoutError('server')
                time.sleep(.1)
            observer = Rpc(None, None, sock)
            if '--proxy' in sys.argv:
                endpoint = start_proxy(sock, 1)
                import rpc
                rpc.NOTIFICATIONS = ()
            else:
                endpoint = sock
            owner = Rpc(None, None, endpoint)
            parent = owner.request('thread/start', {'cwd': directory})['thread']['id']
            initial = owner.request('turn/start', {'threadId': parent, 'input': [{'type':'text', 'text':'Spawn child'}]})
            wait_turn(observer, parent, initial['turn']['id'])
            if '--reconnect' in sys.argv:
                assert '--proxy' in sys.argv
                before = owner.request('thread/read', {'threadId': parent, 'includeTurns': True})['thread']['turns']
                calls = Model.count
                p.terminate()
                p.wait(timeout=10)
                owner.reader.join(timeout=5)
                assert owner.closed, 'server exit did not disconnect the terminal'
                owner.close()
                observer.close()
                owner = observer = None
                assert endpoint.exists(), 'proxy endpoint disappeared with the server'
                try:
                    unavailable = Rpc(None, None, endpoint)
                except (UsageUnavailable, OSError):
                    pass
                else:
                    unavailable.close()
                    raise AssertionError('stopped server still accepted requests')
                with (root/'restart-stderr').open('w') as stderr:
                    p = subprocess.Popen(p.args, env=dict(os.environ, CODEX_HOME=directory),
                                         stdout=subprocess.DEVNULL, stderr=stderr)
                deadline = time.monotonic() + 15
                while True:
                    try:
                        owner = Rpc(None, None, endpoint)
                        break
                    except (UsageUnavailable, OSError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError('restarted server')
                        time.sleep(.1)
                resumed = owner.request('thread/resume', {'threadId': parent, 'cwd': directory})
                assert resumed['thread']['id'] == parent
                turn = owner.request('turn/start', {'threadId': parent, 'input': [
                    {'type': 'text', 'text': 'Resume same history'},
                ]})
                wait_turn(owner, parent, turn['turn']['id'])
                history = owner.request('thread/read', {'threadId': parent, 'includeTurns': True})['thread']['turns']
                assert [t['id'] for t in history] == [t['id'] for t in before] + [turn['turn']['id']]
                assert Model.count == calls + 1, 'reconnect replayed a model request'
                print(json.dumps({'same_endpoint': str(endpoint), 'same_thread': parent,
                                  'turns_before': len(before), 'turns_after': len(history),
                                  'new_model_requests': Model.count - calls}), flush=True)
                return
            deadline=time.monotonic()+20
            while True:
                threads = owner.request('thread/loaded/list')['data']
                statuses = [owner.request('thread/read',{'threadId':t})['thread']['status'] for t in threads]
                ready = len(threads)>1 or ('--proxy' in sys.argv and '--child' not in sys.argv)
                if ready and all(s['type']=='idle' for s in statuses): break
                if time.monotonic()>deadline:
                    print(json.dumps(owner.request('thread/read',{'threadId':parent,'includeTurns':True})),flush=True)
                    raise TimeoutError((threads,statuses, Model.count))
                time.sleep(.1)
            if '--proxy' in sys.argv:
                if '--active' in sys.argv:
                    owner.request('turn/start',{'threadId':parent,'input':[{'type':'text','text':'Hold fixture active'}]})
                    time.sleep(3)
                    active=observer.request('thread/read',{'threadId':parent})['thread']['status']['type']
                    assert active=='active',active
                    print('active turn preserved',active,flush=True)
                    Model.release.set()
                    while observer.request('thread/read',{'threadId':parent})['thread']['status']['type']=='active':time.sleep(.1)
                if '--background' in sys.argv:
                    turn=owner.request('turn/start',{'threadId':parent,'input':[{'type':'text','text':'Start fixture background'}]})
                    wait_turn(observer,parent,turn['turn']['id'])
                    deadline=time.monotonic()+10
                    while observer.request('thread/read',{'threadId':parent})['thread']['status']['type']=='active':
                        assert time.monotonic()<deadline
                        time.sleep(.1)
                    before_jobs=observer.request('thread/backgroundTerminals/list',{'threadId':parent})['data']
                    while not before_jobs and time.monotonic()<deadline:
                        time.sleep(.1)
                        before_jobs=observer.request('thread/backgroundTerminals/list',{'threadId':parent})['data']
                    if not before_jobs:
                        print(json.dumps(observer.request('thread/read',{'threadId':parent,'includeTurns':True})),flush=True)
                    assert before_jobs
                    time.sleep(4)
                    after_jobs=observer.request('thread/backgroundTerminals/list',{'threadId':parent})['data']
                    assert before_jobs[0]['processId']==after_jobs[0]['processId']
                    print('background process preserved',after_jobs[0]['processId'],flush=True)
                    return
                if '--child' in sys.argv and '--child-restart' not in sys.argv:
                    turn=owner.request('turn/start',{'threadId':parent,'input':[{'type':'text','text':'Queue fixture mail'}]})
                    wait_turn(observer,parent,turn['turn']['id'])
                for tid in threads:
                    observer.request('thread/unsubscribe', {'threadId': tid})
                if '--child-restart' in sys.argv:
                    child=next(t for t in threads if t != parent)
                    time.sleep(2)
                    turn=owner.request('turn/start',{'threadId':parent,'input':[{'type':'text','text':'Restart fixture child'}]})
                    wait_turn(observer,parent,turn['turn']['id'])
                    deadline=time.monotonic()+10
                    jobs=[]
                    while not jobs and time.monotonic()<deadline:
                        jobs=observer.request('thread/backgroundTerminals/list',{'threadId':child})['data']
                        time.sleep(.1)
                    assert jobs
                    time.sleep(7)
                    after=observer.request('thread/backgroundTerminals/list',{'threadId':child})['data']
                    assert after and after[0]['processId']==jobs[0]['processId'],after
                    print('child restart before unload preserved background',after[0]['processId'],flush=True)
                    return
                before=sample(p.pid)
                time.sleep(6)
                loaded=observer.request('thread/loaded/list')['data']
                parked=sample(p.pid)
                print(json.dumps({'phase':'parked','loaded':loaded,'before':before,'after':parked}),flush=True)
                assert loaded == [parent] if '--child' in sys.argv else not loaded, loaded
                if '--child' in sys.argv:
                    child=next(t for t in threads if t != parent)
                    observer.request('thread/resume',{'threadId':child,'excludeTurns':True})
                    observer.request('thread/unsubscribe',{'threadId':child})
                    time.sleep(4)
                    assert observer.request('thread/loaded/list')['data']==[parent]
                    print('passive child inspection reclaimed',flush=True)
                prompt = 'Resume fixture child' if '--child' in sys.argv else 'Resume same history'
                turn=owner.request('turn/start',{'threadId':parent,'input':[{'type':'text','text':prompt}]})
                wait_turn(observer,parent,turn['turn']['id'])
                history=observer.request('thread/read',{'threadId':parent,'includeTurns':True})['thread']['turns']
                print('resumed same thread',parent,'turns',len(history),flush=True)
                assert len(history)>= (3 if '--child' in sys.argv or '--active' in sys.argv else 2)
                if '--child' in sys.argv:
                    deadline=time.monotonic()+10
                    while not Model.mail_seen and time.monotonic()<deadline:time.sleep(.1)
                    print('queued child mail preserved',Model.mail_seen,flush=True)
                    assert Model.mail_seen
                return
            children = [t for t in threads if t != parent]
            for tid in children:
                owner.request('thread/unsubscribe', {'threadId':tid})
            owner.request('thread/unsubscribe', {'threadId':parent})
            owner.close(); owner=None
            time.sleep(3)
            result = sample(p.pid)
            result.update(label='owner_closed_observer_retains', loaded=observer.request('thread/loaded/list')['data'])
            assert set(result['loaded']) == set(children), result
            records.append(result); print(json.dumps(result),flush=True)
            for tid in children:
                print('observer unsubscribe', tid, observer.request('thread/unsubscribe', {'threadId': tid}),flush=True)
            time.sleep(3)
            result = sample(p.pid)
            result.update(label='observer_released',loaded=observer.request('thread/loaded/list')['data'])
            assert not result['loaded'], result
            records.append(result); print(json.dumps(result),flush=True)
        finally:
            diagnostic = observer or owner
            if sys.exc_info()[0] is not None and diagnostic:
                try:
                    failure = {}
                    for tid in diagnostic.request('thread/loaded/list')['data']:
                        failure[tid] = diagnostic.request('thread/read', {'threadId':tid,'includeTurns':True})
                    Path('/private/tmp/codex-fixture-failure.json').write_text(json.dumps(failure,indent=2))
                except (UsageUnavailable, OSError):
                    # 진단 실패가 격리 서버와 MCP의 정리를 막지 않게 한다.
                    pass
            Model.release.set()
            if owner: owner.close()
            if observer: observer.close()
            p.terminate(); p.wait(timeout=10)
            model.shutdown(); model.server_close()
            if '--proxy' not in sys.argv:
                Path('/private/tmp/codex-subscription-result.json').write_text(json.dumps(records,indent=2))


if __name__ == '__main__':
    main()
