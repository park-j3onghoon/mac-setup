import os
import json
from pathlib import Path
import resource
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from policy import UsageUnavailable
from rpc import RpcRejected
from runtime import CONTINUE_PROMPT, Runtime, all_idle, prepare_home
from state import load, poll_delay, record, save, snapshot
from supervisor import monitor


def usage(percent, resets, observed):
    return snapshot({"rateLimits": {"primary": {
        "usedPercent": percent, "resetsAt": resets, "windowDurationMins": 10080,
    }}}, observed_at=observed)


class StateTest(unittest.TestCase):
    def test_reset_time_and_observation_are_preserved(self):
        value = usage(91, 200, 100)
        self.assertEqual(value["observed_at"], 100)
        self.assertEqual(value["windows"]["primary"]["resets_at"], 200)

    def test_elapsed_time_does_not_fabricate_a_reset(self):
        value = record(usage(91, 200, 100), usage(91, 200, 201))
        self.assertNotIn("last_reset_confirmed_at", value["windows"]["primary"])
        self.assertEqual(value["used_percent"], 91)

    def test_server_rollover_is_recorded_and_survives_next_poll(self):
        old = usage(91, 200, 100)
        new = record(old, usage(0, 1000, 201))
        again = record(new, usage(4, 1000, 250))
        self.assertEqual(again["windows"]["primary"]["last_reset_confirmed_at"], 201)

    def test_reset_triggers_earlier_check_without_past_time_busy_loop(self):
        self.assertEqual(poll_delay({"company": usage(91, 110, 100)}, now=100), 11)
        self.assertEqual(poll_delay({"company": usage(91, 90, 100)}, now=100), 60)

    def test_poll_interval_follows_the_active_account_headroom(self):
        later = 10_000_000
        for percent, seconds in ((20, 540), (61, 300), (80, 120), (88, 60)):
            with self.subTest(percent=percent):
                accounts = {"company": usage(percent, later, 100), "personal": usage(95, later, 100)}
                self.assertEqual(poll_delay(accounts, active="company", now=100), seconds)

    def test_only_metadata_is_written_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            value = {"accounts": {"company": usage(20, 200, 100)}}
            save(value, path)
            self.assertEqual(load(path), value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("token", path.read_text())


class HomeTest(unittest.TestCase):
    def test_live_socket_recovers_identity_without_saved_runtime_pid(self):
        """상태 파일을 잃어도 현재 사용자 소켓의 실제 프로세스를 확인해 서버를 이어받는다."""
        profiles = {'company': Mock(account_id='company')}
        with tempfile.TemporaryDirectory(dir='/tmp') as directory, socket.socket(socket.AF_UNIX) as listener:
            server = Runtime(profiles, home=directory)
            listener.bind(str(server.socket))
            listener.listen(1)
            with patch('runtime.prepare_home'), patch('runtime.Rpc') as rpc, \
                    patch('runtime.process_start', return_value='peer-start', create=True), \
                    patch('runtime.subprocess.Popen') as spawn:
                rpc.return_value.request.return_value = {'account': {'type': 'chatgpt'},
                    'workspaceRouting': {'chatgptAccountId': 'company'}}

                server.start()

                self.assertEqual(server.pid, os.getpid())
                self.assertEqual(server.pid_start, 'peer-start')
                self.assertEqual(server.active, 'company')
                spawn.assert_not_called()
                server.close()

    def test_reused_native_pid_is_not_a_live_runtime(self):
        """공유 서버 PID가 다른 프로세스에 재사용되면 살아 있다고 보지 않는다."""
        server = Runtime({})
        server.pid, server.pid_start = 4321, 'original'
        with patch('runtime.os.kill'), patch('runtime.process_start', return_value='reused', create=True):
            self.assertFalse(server.running())

    def test_start_retries_transient_connect_refusal_after_socket_creation(self):
        """bind 뒤 listen 전의 연결 거부는 새 서버를 종료하지 않고 시작 예산 안에서 재시도한다."""
        server = Runtime({}, home='/unused', binary=Path(sys.executable))
        client = Mock(closed=False)
        with patch('runtime.prepare_home'), patch('runtime.preserve_server_package', return_value='/fixture'), \
                patch.object(Path, 'exists', side_effect=[False, True, True]), \
                patch('runtime.subprocess.Popen') as spawn, \
                patch('runtime.Rpc', side_effect=[ConnectionRefusedError(), client]) as rpc, \
                patch('runtime.time.sleep'), \
                patch('runtime.process_start', return_value='new-start', create=True):
            spawn.return_value.poll.return_value = None

            server.start()

            self.assertIs(server.client, client)
            self.assertEqual(rpc.call_count, 2)
            spawn.return_value.terminate.assert_not_called()

    def test_standalone_launcher_inherits_capacity_for_more_than_256_open_files(self):
        """CODEX_HOME을 지정한 --no-daemon도 exec 전에 파일 한도를 보완한다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "codex"
            binary.write_text(
                f"#!{sys.executable}\n"
                "import json, resource\nfrom pathlib import Path\n"
                "handles = [open('/dev/null') for _ in range(300)]\n"
                "Path(__file__).with_name('capacity.json').write_text(json.dumps(\n"
                "    resource.getrlimit(resource.RLIMIT_NOFILE)))\n"
            )
            binary.chmod(0o700)
            script = """
import os, resource, sys
from pathlib import Path
import launcher
resource.setrlimit(resource.RLIMIT_NOFILE, (256, resource.RLIM_INFINITY))
launcher.BINARY = Path(sys.argv[1]) / 'codex'
os.environ['CODEX_HOME'] = sys.argv[1]
launcher.main(['--no-daemon'])
"""

            subprocess.run([sys.executable, "-c", script, directory], cwd=Path(__file__).parent,
                           check=True, timeout=10)

            self.assertEqual(json.loads((root / "capacity.json").read_text())[0], 4096)

    def test_new_runtime_inherits_capacity_for_more_than_256_open_files(self):
        """낮은 기본 한도를 높여 자식이 파일 300개를 열고, hard limit과 더 높은 한도는 보존한다."""
        for soft, hard, expected in ((256, resource.RLIM_INFINITY, 4096),
                                     (256, 512, 512), (8192, 8192, 8192)):
            with self.subTest(soft=soft, hard=hard), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = root / "codex"
                binary.write_text(
                    f"#!{sys.executable}\n"
                    "import json, resource\nfrom pathlib import Path\n"
                    "handles = [open('/dev/null') for _ in range(300)]\n"
                    "Path(__file__).with_name('capacity.json').write_text(json.dumps(\n"
                    "    resource.getrlimit(resource.RLIMIT_NOFILE)))\n"
                )
                binary.chmod(0o700)
                script = """
import resource, sys
from pathlib import Path
import runtime
resource.setrlimit(resource.RLIMIT_NOFILE, (int(sys.argv[2]), int(sys.argv[3])))
runtime.prepare_home = lambda home: None
root = Path(sys.argv[1])
server = runtime.Runtime({}, home=root, binary=root / 'codex')
try:
    server.start()
except runtime.UsageUnavailable:
    pass
finally:
    server.stop()
"""

                subprocess.run([sys.executable, "-c", script, directory, str(soft), str(hard)],
                               cwd=Path(__file__).parent, check=True, timeout=10)

                self.assertEqual(json.loads((root / "capacity.json").read_text()),
                                 [expected, hard])

    def test_existing_runtime_is_reattached_without_restarting_conversations(self):
        """감독 프로세스만 바뀌면 실행 중인 서버와 대화를 그대로 사용한다."""
        profiles = {name: Mock(account_id=name) for name in ("company", "personal")}
        runtime = Runtime(profiles, home=Path("/auto"))
        with patch("runtime.prepare_home"), patch.object(Path, "exists", return_value=True), \
             patch("runtime.socket.socket"), patch("runtime.os.kill"), \
             patch('runtime.peer_process', return_value=(4321, 'original')), \
             patch('runtime.process_start', return_value='original'), \
             patch("runtime.Rpc") as rpc, patch("runtime.subprocess.Popen") as popen:
            rpc.return_value.request.return_value = {
                "account": {"type": "chatgpt"}, "workspaceRouting": {"chatgptAccountId": "company"}}

            runtime.start()
            running = runtime.running()
            runtime.close()

        self.assertTrue(running)
        self.assertEqual(runtime.pid, 4321)
        self.assertEqual(runtime.active, "company")
        popen.assert_not_called()
        rpc.return_value.close.assert_called_once()

    def test_shared_server_opens_with_the_company_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            company = root / "company.toml"
            company.write_text("model = 'company'\n")
            shared = root / "shared"
            shared.mkdir()
            (shared / "config.toml").write_text("model = 'personal'\n")
            home = root / "auto"
            home.mkdir()
            (home / "config.toml").symlink_to(shared / "config.toml")
            prepare_home(home, shared=shared, config=company)
            self.assertEqual((home / "config.toml").read_text(), "model = 'company'\n")

    def test_company_workspace_lock_is_lifted_only_on_the_shared_server(self):
        runtime = Runtime({}, home=Path("/auto"), binary=Path(sys.executable))
        with patch("runtime.prepare_home"), patch("runtime.subprocess.Popen") as popen, \
             patch.object(Path, "exists", return_value=False):
            popen.return_value.poll.return_value = 1
            with self.assertRaises(UsageUnavailable):
                runtime.start()
        self.assertEqual(popen.call_args.args[0][1:4], ["app-server", "-c", 'forced_chatgpt_workspace_id=""'])


class PackagedRuntimeTest(unittest.TestCase):
    def test_existing_cache_missing_host_is_rebuilt_before_server_start(self):
        """원본 설치가 정상일 때 손상된 보관본을 재사용하지 않고 도구 실행까지 복구한다."""
        self.install('0.170.0')
        first = self.start_server()
        self.assertEqual(self.call_tool(first), '0.170.0')
        first.stop()
        cached = self.home / 'app-server-packages/0.170.0/bin/codex-code-mode-host'
        cached.unlink()

        repaired = self.start_server()

        self.assertEqual(self.call_tool(repaired), '0.170.0')

    def test_corrupt_install_does_not_replace_the_working_cache(self):
        from runtime import preserve_server_package
        release = self.install('0.170.0')
        cached = preserve_server_package(self.binary, self.home)
        host = cached.parent / 'codex-code-mode-host'
        good = host.read_bytes()
        (release / 'bin' / host.name).write_bytes(b'')
        preserve_server_package(self.binary, self.home)
        self.assertEqual(host.read_bytes(), good)

    def test_supervisor_disconnect_keeps_owned_server_available(self):
        """감독의 상태 저장 오류나 종료가 공유 서버의 대화와 도구를 종료하지 않는다."""
        self.install("0.170.0")
        running = self.start_server()

        running.close()

        self.assertIsNone(running.process.poll())
        self.assertEqual(self.call_tool(running), "0.170.0")

    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "auto"
        self.home.mkdir()
        self.binary = self.root / "codex"
        rpc = patch("runtime.Rpc")
        rpc.start()
        self.addCleanup(rpc.stop)

    def install(self, version):
        release = self.root / "Caskroom" / "codex" / version
        (release / "bin").mkdir(parents=True)
        (release / "codex-package.json").write_text(json.dumps({"version": version}))
        (release / "codex-resources").mkdir()
        (release / "codex-resources" / "version").write_text(version)
        cli = release / "bin" / "codex"
        cli.write_text(f"#!{sys.executable}\n" + """
import socket, subprocess, sys
from pathlib import Path
host = Path(__file__).resolve().with_name("codex-code-mode-host")
with socket.socket(socket.AF_UNIX) as server:
    server.bind(sys.argv[-1].removeprefix("unix://"))
    server.listen()
    with server.accept()[0] as client:
        client.sendall(subprocess.check_output([host]))
""")
        cli.chmod(0o700)
        host = cli.with_name("codex-code-mode-host")
        host.write_text(f"#!{sys.executable}\nfrom pathlib import Path\n"
                        "print((Path(__file__).parents[1] / 'codex-resources/version').read_text())\n")
        host.chmod(0o700)
        shutil.copy2(host, host.with_name("codex-exec-server"))
        self.binary.unlink(missing_ok=True)
        self.binary.symlink_to(cli)
        return release

    def start_server(self):
        runtime = Runtime({}, home=self.home, binary=self.binary)
        self.addCleanup(runtime.stop)
        runtime.start()
        return runtime

    def call_tool(self, runtime):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(5)
            client.connect(str(runtime.socket))
            with client.makefile() as response:
                return response.readline().strip()

    def test_resumed_client_can_call_the_original_tool_after_cask_cleanup(self):
        """공유 서버는 원본 Cask가 지워진 뒤에도 같은 릴리스의 host와 리소스를 사용한다."""
        previous = self.install("0.169.0")
        running = self.start_server()

        self.install("0.170.0")
        shutil.rmtree(previous)
        self.assertEqual(self.call_tool(running), "0.169.0")
        running.stop()

        restarted = self.start_server()
        self.assertEqual(self.call_tool(restarted), "0.170.0")
        self.assertEqual([p.name for p in (self.home / "app-server-packages").iterdir()], ["0.170.0"])

    def test_missing_host_can_be_repaired_before_retrying_start(self):
        """일부만 남은 Cask를 실행하거나 보관하면 같은 버전을 복구해도 도구가 계속 실패한다."""
        release = self.install("0.170.0")
        host = release / "bin" / "codex-code-mode-host"
        host.rename(release / "saved-host")
        with self.assertRaises(UsageUnavailable):
            self.start_server()

        (release / "saved-host").rename(host)
        self.assertEqual(self.call_tool(self.start_server()), "0.170.0")

    def test_rollback_after_cleanup_interruption_uses_the_complete_package(self):
        """이전 버전 정리가 일부만 끝난 상태에서 다운그레이드해도 리소스를 다시 보존한다."""
        previous = self.install("0.169.0")
        running = self.start_server()
        self.assertEqual(self.call_tool(running), "0.169.0")
        running.stop()
        self.install("0.170.0")
        rmtree = shutil.rmtree

        def interrupt_cleanup(path, *args, **kwargs):
            for resource_file in Path(path).rglob("codex-resources/version"):
                if resource_file.read_text() == "0.169.0":
                    resource_file.unlink()
                    raise InterruptedError("interrupted cleanup")
            return rmtree(path, *args, **kwargs)

        with patch("shutil.rmtree", side_effect=interrupt_cleanup), self.assertRaises(InterruptedError):
            self.start_server()
        self.binary.unlink()
        self.binary.symlink_to(previous / "bin" / "codex")

        self.assertEqual(self.call_tool(self.start_server()), "0.169.0")


class IdleTest(unittest.TestCase):
    def test_cleanup_returns_between_threads_and_bounds_each_rpc(self):
        """대화가 많아도 한 주기에는 하나만 정리하고 각 RPC에 남은 시간만 준다."""
        runtime = Runtime({})
        runtime.client = Mock(closed=False)
        def answer(method, params=None, timeout=30):
            self.assertLessEqual(timeout, 2)
            if method == 'thread/loaded/list':
                return {'data': [str(number) for number in range(100)]}
            if method == 'thread/read':
                return {'thread': {'status': {'type': 'idle'}}}
            return {'data': []}
        runtime.client.request.side_effect = answer

        self.assertFalse(runtime.release_subscriptions())
        self.assertLessEqual(runtime.client.request.call_count, 4)
        for _ in range(99):
            complete = runtime.release_subscriptions()
        self.assertTrue(complete)
        self.assertEqual(sum(call.args[0] == 'thread/unsubscribe'
                             for call in runtime.client.request.call_args_list), 100)

    def test_observer_releases_only_its_quiet_subscriptions_without_background_jobs(self):
        """감독 연결은 유휴 구독만 놓고 active·백그라운드 명령이 있는 대화는 보존한다."""
        runtime = Runtime({})
        runtime.client = Mock(closed=False)
        def answer(method, params=None, **kwargs):
            if method == "thread/loaded/list":
                return {"data": ["idle", "active", "background"]}
            if method == "thread/read":
                return {"thread": {"status": {"type": "active" if params["threadId"] == "active" else "idle"}}}
            if method == "thread/backgroundTerminals/list":
                return {"data": ["running"] if params["threadId"] == "background" else []}
            if method == "thread/unsubscribe":
                return {"status": "unsubscribed"}
            raise AssertionError(method)
        runtime.client.request.side_effect = answer

        for _ in range(3):
            complete = runtime.release_subscriptions()
        self.assertTrue(complete)

        releases = [call.args[1]["threadId"] for call in runtime.client.request.call_args_list
                    if call.args[0] == "thread/unsubscribe"]
        self.assertEqual(releases, ["idle"])

    def test_all_pages_are_checked(self):
        client = Mock()
        client.request.side_effect = [
            {"data": ["a"], "nextCursor": "next"},
            {"thread": {"status": {"type": "idle"}}},
            {"data": ["b"]},
            {"thread": {"status": {"type": "active", "activeFlags": ["waitingOnApproval"]}}},
        ]
        self.assertFalse(all_idle(client))

    def test_unknown_thread_state_blocks_switch(self):
        client = Mock()
        client.request.side_effect = [{"data": ["a"]}, {"thread": {}}]
        self.assertFalse(all_idle(client))

    def test_idle_scan_has_one_total_budget_across_threads(self):
        """대화별 제한뿐 아니라 전체 점검 예산을 넘으면 유휴로 승인하지 않는다."""
        clock = [0]
        client = Mock()

        def slow(method, params, timeout):
            self.assertLessEqual(timeout, 5 - clock[0])
            clock[0] += 2
            if method == 'thread/loaded/list':
                return {'data': ['a', 'b', 'c']}
            return {'thread': {'status': {'type': 'idle'}}}

        client.request.side_effect = slow
        with patch('runtime.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(UsageUnavailable, 'budget'):
                all_idle(client, deadline=5)
        self.assertEqual(client.request.call_count, 3)

    def test_thread_stopped_by_an_error_does_not_block_switch(self):
        client = Mock()
        client.request.side_effect = [{"data": ["a"]}, {"thread": {"status": {"type": "systemError"}}}]
        self.assertTrue(all_idle(client))


LIMITED = {"data": [{"id": "turn-1", "status": "failed",
                     "error": {"codexErrorInfo": "usageLimitExceeded"}}]}


class ContinueTest(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime({})
        self.runtime.client = Mock()
        self.addCleanup(self.runtime.close)

    def test_slow_continuation_scan_keeps_supervisor_responsive(self):
        """이어하기 점검도 감독을 막지 않고 다음 호출에서 진행을 이어간다."""
        entered, release = threading.Event(), threading.Event()
        self.answer({'t1': ('idle', LIMITED)})
        answer = self.runtime.client.request.side_effect

        def request(method, params=None, **kwargs):
            if method == 'thread/read':
                entered.set()
                release.wait(2)
            return answer(method, params, **kwargs)

        self.runtime.client.request.side_effect = request
        started = time.monotonic()
        try:
            self.assertFalse(self.runtime.continue_limited())
            self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(entered.wait(.5))
            release.set()
            self.runtime.continuation_future.result(timeout=1)
            self.assertTrue(self.runtime.continue_limited())
            self.assertEqual(len(self.started()), 1)
        finally:
            release.set()

    def answer(self, threads, parents=None):
        def request(method, params=None, timeout=30):
            if method == "thread/loaded/list":
                return {"data": list(threads)}
            status, turns = threads.get(params.get("threadId"), (None, None))
            if method == "thread/read":
                return {"thread": {"status": {"type": status},
                                   "parentThreadId": (parents or {}).get(params["threadId"])}}
            if method == "thread/turns/list" and isinstance(turns, Exception):
                raise turns
            return turns if method == "thread/turns/list" else {}

        self.runtime.client.request.side_effect = request

    def started(self):
        return [call.args[1] for call in self.runtime.client.request.call_args_list
                if call.args[0] == "turn/start"]

    def test_turn_stopped_by_the_usage_limit_is_continued_once(self):
        self.answer({"t1": ("idle", LIMITED)})
        self.runtime.continue_limited()
        self.runtime.continue_limited()
        self.assertEqual(self.started(), [
            {"threadId": "t1", "input": [{"type": "text", "text": CONTINUE_PROMPT}]},
        ])

    def test_new_user_turn_prevents_an_extra_continuation(self):
        self.answer({'t1': ('idle', LIMITED)})
        answer = self.runtime.client.request.side_effect
        def request(method, params=None, **kwargs):
            if method == 'thread/turns/list':
                self.runtime.activity('turn/started', {'threadId': 't1'})
            return answer(method, params, **kwargs)
        self.runtime.client.request.side_effect = request
        self.runtime.continue_limited()
        self.assertEqual(self.started(), [])

    def test_running_threads_and_other_endings_are_left_alone(self):
        unprompted = RpcRejected("Codex thread/turns/list failed")
        unprompted.no_history = True
        self.answer({
            "running": ("active", LIMITED),
            "done": ("idle", {"data": [{"id": "turn-2", "status": "completed"}]}),
            "crashed": ("systemError", {"data": [{"id": "turn-3", "status": "failed",
                                                  "error": {"codexErrorInfo": "other"}}]}),
            "unprompted": ("idle", unprompted),
        })
        self.runtime.continue_limited()
        self.assertEqual(self.started(), [])

    def test_sub_agents_stopped_by_the_limit_are_left_to_their_parent(self):
        """한도로 멈춘 하위 에이전트에는 직접 이어서 하라고 하지 않는다. 부모가 이어서 하면서 하위 에이전트를 다시 움직인다."""
        child_limited = {"data": [{"id": "turn-9", "status": "failed",
                                   "error": {"codexErrorInfo": "usageLimitExceeded"}}]}
        self.answer({"parent": ("systemError", LIMITED), "child": ("systemError", child_limited)},
                    parents={"child": "parent"})

        self.runtime.continue_limited()

        self.assertEqual([params["threadId"] for params in self.started()], ["parent"])

    def test_failed_thread_does_not_starve_later_continuations(self):
        """앞 대화의 재개가 거절돼도 뒤 대화는 계속하며 거절된 요청만 재시도한다."""
        from rpc import RpcRejected
        self.answer({'bad': ('idle', LIMITED), 'good': ('idle', {
            'data': [dict(LIMITED['data'][0], id='turn-good')]})})
        answer = self.runtime.client.request.side_effect
        failures = [RpcRejected('rejected')]

        def request(method, params=None, **kwargs):
            if method == 'turn/start' and params['threadId'] == 'bad' and failures:
                raise failures.pop()
            return answer(method, params, **kwargs)

        self.runtime.client.request.side_effect = request
        with self.assertRaises(UsageUnavailable):
            self.runtime.continue_limited()
        self.runtime.continue_limited()
        self.assertEqual([value['threadId'] for value in self.started()], ['bad', 'good', 'bad'])

    def test_continuation_batches_preserve_progress_at_the_time_budget(self):
        """예산 경계의 대화까지 다음 묶음에서 이어 처리해 어느 대화도 계속 누락되지 않는다."""
        clock = [0]
        self.answer({f't{i}': ('idle', {'data': [dict(LIMITED['data'][0], id=f'turn-{i}')]})
                     for i in range(20)})
        answer = self.runtime.client.request.side_effect

        def slow(method, params=None, **kwargs):
            clock[0] += 2
            return answer(method, params, **kwargs)

        self.runtime.client.request.side_effect = slow
        with patch('runtime.time.monotonic', side_effect=lambda: clock[0]):
            for _ in range(30):
                if self.runtime.continue_limited():
                    break
            else:
                self.fail('scan did not finish')
        self.assertEqual(len(self.started()), 20)
        self.assertEqual(len({value['threadId'] for value in self.started()}), 20)

    def test_one_thread_timeout_does_not_repeat_at_the_head_of_every_batch(self):
        """한 대화가 예산 끝까지 시간 초과해도 다음 묶음은 뒤 대화로 진행한다."""
        clock = [0]
        self.answer({'bad': ('idle', LIMITED), 'good': ('idle', {
            'data': [dict(LIMITED['data'][0], id='good-turn')]})})
        answer = self.runtime.client.request.side_effect

        def request(method, params=None, timeout=30):
            if method == 'thread/read' and params['threadId'] == 'bad':
                clock[0] += timeout
                raise UsageUnavailable('thread read timed out')
            return answer(method, params, timeout)

        self.runtime.client.request.side_effect = request
        with patch('runtime.time.monotonic', side_effect=lambda: clock[0]):
            self.assertFalse(self.runtime.continue_batch(self.runtime.client))
            with self.assertRaises(UsageUnavailable):
                self.runtime.continue_batch(self.runtime.client)
        self.assertEqual([value['threadId'] for value in self.started()], ['good'])

    def test_definite_pre_send_failure_can_retry_after_reconnection(self):
        """전송하기 전 끊긴 연결은 복구 후 자동 이어하기를 다시 시도한다."""
        from rpc import RpcNotSent
        self.answer({'t1': ('idle', LIMITED)})
        answer = self.runtime.client.request.side_effect
        failures = [RpcNotSent('connection was already closed')]

        def request(method, params=None, **kwargs):
            if method == 'turn/start' and failures:
                raise failures.pop()
            return answer(method, params, **kwargs)

        self.runtime.client.request.side_effect = request
        with self.assertRaises(UsageUnavailable):
            self.runtime.continue_limited()
        self.runtime.continue_limited()
        self.assertEqual(len(self.started()), 2)

    def test_uncertain_turn_start_is_not_blindly_replayed(self):
        """응답을 잃은 재개는 이미 실행됐을 수 있으므로 같은 한도 오류로 중복 전송하지 않는다."""
        self.answer({'t1': ('idle', LIMITED)})
        answer = self.runtime.client.request.side_effect

        def request(method, params=None, **kwargs):
            if method == 'turn/start':
                raise UsageUnavailable('connection ended after send')
            return answer(method, params, **kwargs)

        self.runtime.client.request.side_effect = request
        with self.assertRaises(UsageUnavailable):
            self.runtime.continue_limited()
        with self.assertRaises(UsageUnavailable):
            self.runtime.continue_limited()
        self.assertEqual(len(self.started()), 1)
        self.assertEqual(self.runtime.uncertain_continuations, {'t1': 'turn-1'})
        self.answer({'t1': ('idle', {'data': [{'id': 'new-turn', 'status': 'completed'}]})})
        self.runtime.continue_limited()
        self.assertEqual(self.runtime.uncertain_continuations, {})


class SwitchingTest(unittest.TestCase):
    def setUp(self):
        self.profiles = {name: Mock(account_id=name) for name in ("company", "personal")}
        for name, profile in self.profiles.items():
            profile.tokens.return_value = {"accessToken": "dummy", "chatgptAccountId": name}
            profile.usage.return_value = usage(10, 9999, 1000)
        self.runtime = Runtime(self.profiles)
        self.runtime.active = "company"
        self.runtime.client = Mock(closed=False)
        self.addCleanup(self.runtime.close)

    def test_slow_idle_scan_returns_control_and_rejects_activity_during_scan(self):
        """느린 전체 점검은 감독을 막지 않으며 그 사이 새 활동이 관측되면 다시 검사한다."""
        entered, release = threading.Event(), threading.Event()

        def scan(_client, **_kwargs):
            entered.set()
            release.wait(2)
            return True

        with patch('runtime.all_idle', side_effect=scan):
            started = time.monotonic()
            try:
                self.assertFalse(self.runtime.select('personal'))
                self.assertLess(time.monotonic() - started, .5)
                self.assertTrue(entered.wait(.5))
                self.runtime.activity('thread/status/changed', {'status': {'type': 'active'}})
                release.set()
                self.runtime.idle_job['future'].result(timeout=1)
                self.assertFalse(self.runtime.select('personal'))
                self.assertNotIn('account/login/start', [
                    call.args[0] for call in self.runtime.client.request.call_args_list])
            finally:
                release.set()

    def test_token_preparation_finishes_before_the_idle_snapshot(self):
        """토큰 갱신 중 시작된 작업은 유휴 검사에서 발견하고 로그인을 바꾸지 않는다."""
        active = [False]

        def tokens():
            active[0] = True
            return {'accessToken': 'fixture', 'chatgptAccountId': 'personal'}

        self.profiles['personal'].tokens.side_effect = tokens
        with patch('runtime.all_idle', side_effect=lambda *_args, **_kwargs: not active[0]):
            self.assertFalse(self.runtime.select('personal'))
        self.assertNotIn('account/login/start', [
            call.args[0] for call in self.runtime.client.request.call_args_list])

    def test_exhausted_or_unavailable_target_never_changes_login(self):
        """이전 조회에 여유가 있었어도 전환 직전 한도를 확인할 수 없으면 로그인하지 않는다."""
        for result in (usage(100, 9999, 1000), UsageUnavailable('offline')):
            with self.subTest(result=result):
                self.runtime.client.request.return_value = {'data': []}
                self.profiles['personal'].usage.side_effect = [result]
                with self.assertRaises(UsageUnavailable):
                    self.runtime.select('personal')
                self.assertEqual(self.runtime.active, 'company')
                self.assertNotIn('account/login/start', [
                    call.args[0] for call in self.runtime.client.request.call_args_list])

    def test_active_work_is_not_interrupted_or_reauthenticated(self):
        self.runtime.client.request.side_effect = [
            {"data": ["work"]}, {"thread": {"status": {"type": "active"}}},
        ]
        self.assertFalse(self.runtime.select("personal"))
        self.assertEqual(self.runtime.active, "company")
        methods = [call.args[0] for call in self.runtime.client.request.call_args_list]
        self.assertNotIn("account/login/start", methods)
        self.assertNotIn("turn/interrupt", methods)

    def test_idle_switch_is_verified(self):
        self.runtime.client.request.side_effect = [
            {"data": []}, {"type": "chatgptAuthTokens"}, {"accountId": "personal"},
        ]
        self.assertTrue(self.runtime.select("personal"))
        self.assertEqual(self.runtime.active, "personal")

    def test_activity_during_the_final_quota_check_postpones_login(self):
        self.runtime.client.request.return_value = {'data': []}
        def quota():
            self.runtime.activity('turn/started', {'threadId': 'new'})
            return usage(10, 9999, 1000)
        self.profiles['personal'].usage.side_effect = quota
        self.assertFalse(self.runtime.select('personal'))
        self.assertNotIn('account/login/start', [c.args[0] for c in self.runtime.client.request.call_args_list])

    def test_manual_switch_reauthenticates_without_waiting_for_active_work(self):
        """수동 전환은 실행 중인 대화가 있어도 새 계정으로 로그인하고 검증한다."""
        def request(method, params=None):
            if method == "thread/loaded/list":
                return {"data": ["working"]}
            if method == "thread/read":
                return {"thread": {"status": {"type": "active"}}}
            if method == "account/login/start":
                return {"type": "chatgptAuthTokens"}
            if method == "account/rateLimits/read":
                return {"accountId": "personal"}
            raise AssertionError(method)
        self.runtime.client.request.side_effect = request

        changed = self.runtime.select("personal", force=True)

        self.assertTrue(changed)
        self.assertEqual(self.runtime.active, "personal")

    def test_failed_manual_switch_restores_the_previous_account(self):
        """수동 전환에서도 다른 계정이 확인되면 이전 인증으로 복구한다."""
        self.runtime.client.request.side_effect = [
            {}, {"accountId": "unexpected"}, {}, {"accountId": "company"},
        ]

        with self.assertRaises(UsageUnavailable):
            self.runtime.select("personal", force=True)

        self.assertEqual(self.runtime.active, "company")

    def test_closed_connection_is_replaced_without_logging_in_again(self):
        """감독 연결이 끊기면 같은 서버에 새로 붙는다. 계정이 그대로면 다시 로그인하지 않는다(로그인하면 모든 스레드의 MCP가 재시작된다)."""
        old = self.runtime.client
        old.closed = True
        with patch("runtime.Rpc") as rpc:
            rpc.return_value.request.return_value = {
                "account": {"type": "chatgpt"}, "workspaceRouting": {"chatgptAccountId": "company"}}

            changed = self.runtime.select("company")

        self.assertTrue(changed)
        self.assertEqual(self.runtime.client, rpc.return_value)
        old.close.assert_called_once_with()
        self.assertEqual([call.args[0] for call in rpc.return_value.request.call_args_list],
                         ["account/read"])

    def test_wrong_identity_rolls_back(self):
        self.runtime.client.request.side_effect = [
            {"data": []}, {}, {"accountId": "unexpected"}, {}, {"accountId": "company"},
        ]
        with self.assertRaises(UsageUnavailable):
            self.runtime.select("personal")
        self.assertEqual(self.runtime.active, "company")
        self.profiles["company"].tokens.assert_called_once()

    def test_failed_rollback_does_not_claim_an_unverified_active_account(self):
        self.runtime.client.request.side_effect = [
            {"data": []}, {}, {"accountId": "unexpected"}, UsageUnavailable("offline"),
        ]
        with self.assertRaises(UsageUnavailable):
            self.runtime.select("personal")
        self.assertIsNone(self.runtime.active)

    def test_token_refresh_cannot_select_an_unknown_workspace(self):
        with self.assertRaises(UsageUnavailable):
            self.runtime.refresh("account/chatgptAuthTokens/refresh", {"previousAccountId": "other"})
        for profile in self.profiles.values():
            profile.tokens.assert_not_called()

    def test_refresh_uses_original_profile_for_requested_identity(self):
        self.runtime.refresh("account/chatgptAuthTokens/refresh", {"previousAccountId": "company"})
        self.profiles["company"].tokens.assert_called_once_with(force=True)
        self.profiles["personal"].tokens.assert_not_called()


class MonitorTest(unittest.TestCase):
    def test_immediate_request_survives_failure_and_is_consumed_on_success(self):
        """즉시 전환은 일시 오류 뒤 재시도까지 유지하고 성공 뒤에는 자동 규칙으로 돌아온다."""
        clock, forces = [1000], []
        runtime = Mock(active='company')
        stop = Mock()
        stop.is_set.side_effect = lambda: clock[0] >= 1183
        stop.wait.side_effect = lambda _: clock.__setitem__(0, clock[0] + 61)

        def select(name, *, force=False):
            forces.append(force)
            if len(forces) == 1:
                raise UsageUnavailable('transient fixture failure')
            runtime.active = name
            return True

        runtime.select.side_effect = select
        fresh = {name: usage(10, 9999, 1000) for name in ('company', 'personal')}
        state = {}
        with patch('supervisor.time.time', side_effect=lambda: clock[0]), \
                patch('supervisor.collect', return_value=(fresh, {})), patch('supervisor.save'), \
                patch('supervisor.preference', return_value={
                    'preferred': 'personal', 'immediate': True, 'requested_at': 999}):
            monitor(runtime, {}, stop, state)

        self.assertEqual(forces, [True, True, False])
        self.assertEqual(state['active'], 'personal')

    def test_busy_switch_checks_back_off_and_manual_request_runs_immediately(self):
        """유휴 확인 실패는 간격을 늘리고 새 수동 요청은 대기 간격을 초기화한다."""
        for manual in (False, True):
            with self.subTest(manual=manual):
                clock, selected = [1000], []
                stop = Mock()
                stop.is_set.side_effect = lambda: clock[0] > 1060
                stop.wait.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
                runtime = Mock(active='company')
                runtime.select.side_effect = lambda *args, **kwargs: selected.append(clock[0]) or False
                fresh = {'company': usage(95, 9999, 1000), 'personal': usage(10, 9999, 1000)}
                state = {}
                with patch('supervisor.time.time', side_effect=lambda: clock[0]), \
                        patch('supervisor.collect', return_value=(fresh, {})), patch('supervisor.save'), \
                        patch('supervisor.preference', side_effect=lambda: (
                            {'preferred': 'personal', 'requested_at': 1010, 'immediate': True}
                            if manual and clock[0] >= 1010 else {})):
                    monitor(runtime, {}, stop, state)
                self.assertLessEqual(len(selected), 10)
                self.assertEqual(state['status'], 'waiting_for_idle')
                if manual:
                    self.assertIn(1010, selected)
                else:
                    self.assertEqual(selected, [1000, 1002, 1006, 1014, 1030, 1060])

    def test_account_observation_runs_only_with_usage_polling(self):
        """2초마다 도는 대기 루프에서는 조회하지 않고 사용량 조회 주기에 계정도 확인한다."""
        clock = [1000]
        stop = Mock()
        stop.is_set.side_effect = lambda: clock[0] > 1122
        stop.wait.side_effect = lambda _: clock.__setitem__(0, clock[0] + 2)
        runtime = Mock(active="company")
        runtime.select.return_value = True
        observed_at, polled_at = [], []
        runtime.observe_account.side_effect = lambda: observed_at.append(clock[0])
        fresh = {"company": usage(80, 9999, 1000), "personal": usage(0, 9999, 1000)}

        def collect(_):
            polled_at.append(clock[0])
            return fresh, {}

        with patch("supervisor.time.time", side_effect=lambda: clock[0]), \
             patch("supervisor.collect", side_effect=collect), patch("supervisor.save"), \
             patch("supervisor.preference", return_value={}):
            monitor(runtime, {}, stop, {})

        self.assertEqual(polled_at, [1000, 1120])
        self.assertEqual(observed_at, polled_at)

    def test_dashboard_preference_changes_the_running_monitor(self):
        """대시보드의 개인 계정 선택은 사용량을 다시 확인하고 기존 전환 경로를 쓴다."""
        fresh = {"company": usage(20, 9999, 1000), "personal": usage(10, 9999, 1000)}
        selected, state = self.run_monitor([(fresh, {})],
            requested={"preferred": "personal", "requested_at": 999})
        self.assertEqual(selected, ["personal"])
        self.assertEqual(state["preference_at"], 999)

    def test_immediate_preference_bypasses_idle_only_for_the_requested_account(self):
        """수동 선택 계정에 여유가 있으면 즉시 전환하고, 한도 대체 계정에는 자동 규칙을 쓴다."""
        for percent, target, force in ((10, "personal", True), (95, "company", False)):
            with self.subTest(percent=percent):
                fresh = {"company": usage(20, 9999, 1000), "personal": usage(percent, 9999, 1000)}

                selected, state = self.run_monitor([(fresh, {})],
                    requested={"preferred": "personal", "requested_at": 999, "immediate": True})

                self.assertEqual(selected, [target])
                self.runtime.select.assert_called_once_with(target, force=force)
                self.assertEqual(state["active"], target)

    def observe_external_login(self, response, fresh, errors):
        runtime = Runtime({name: Mock(account_id=name) for name in ("company", "personal")})
        runtime.active = "company"
        runtime.client = Mock(closed=False)

        def request(method, params=None, **kwargs):
            if method == "account/read":
                if isinstance(response, Exception):
                    raise response
                return response
            if method == "thread/loaded/list":
                return {"data": []}
            raise AssertionError(method)

        runtime.client.request.side_effect = request
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        state = {"preferred": "company", "switch_count": 3}
        with patch.object(runtime, "running", return_value=True), \
             patch.object(runtime, "release_subscriptions"), \
             patch.object(runtime, "continue_limited") as continued, \
             patch("supervisor.collect", return_value=(fresh, errors)), \
             patch("supervisor.time.time", return_value=1000), patch("supervisor.save"), \
             patch("supervisor.preference", return_value={}):
            monitor(runtime, {}, stop, state)
        return state, runtime.client, continued

    def test_external_login_updates_state_without_redundant_login(self):
        """다른 연결에서 개인으로 바꿨으면 실제 계정을 기록하고 다시 로그인하지 않는다."""
        response = {"account": {"type": "chatgpt"}, "workspaceRouting": {"chatgptAccountId": "personal"}}
        fresh = {"company": usage(95, 9999, 1000), "personal": usage(0, 9999, 1000)}

        state, client, continued = self.observe_external_login(response, fresh, {})

        self.assertEqual(state["active"], "personal")
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["account_observed_at"], 1000)
        self.assertEqual(state["next_check_at"], 1540)
        self.assertEqual(state["last_external_change"],
                         {"from": "company", "to": "personal", "observed_at": 1000})
        self.assertEqual(state["switch_count"], 3)
        self.assertNotIn("account/login/start", [call.args[0] for call in client.request.call_args_list])
        continued.assert_called_once_with()

    def test_external_login_is_observed_even_when_usage_queries_fail(self):
        """사용량을 몰라 자동 전환을 못 해도 외부에서 바뀐 현재 계정은 기록한다."""
        response = {"account": {"type": "chatgpt"}, "workspaceRouting": {"chatgptAccountId": "personal"}}

        state, client, _ = self.observe_external_login(response, {}, {"company": "Timeout"})

        self.assertEqual(state["active"], "personal")
        self.assertEqual(state["account_observed_at"], 1000)
        self.assertEqual(state["status"], "degraded")
        self.assertEqual([call.args[0] for call in client.request.call_args_list], ["account/read"])

    def test_external_logout_clears_the_recorded_account(self):
        """로그아웃을 확인하면 사용량 조회 실패 중에도 이전 계정을 현재로 남기지 않는다."""
        state, client, _ = self.observe_external_login({"account": None}, {}, {"company": "Timeout"})

        self.assertIsNone(state["active"])
        self.assertEqual(state["account_observed_at"], 1000)
        self.assertEqual(state["last_external_change"]["to"], None)
        self.assertNotIn("account_error", state)
        self.assertEqual([call.args[0] for call in client.request.call_args_list], ["account/read"])

    def test_unregistered_external_account_is_not_overwritten(self):
        """등록되지 않은 계정이면 이전 계정으로 표시하거나 자동 로그인을 덮어쓰지 않는다."""
        response = {"account": {"type": "chatgpt"}, "workspaceRouting": {"chatgptAccountId": "other"}}
        fresh = {"company": usage(0, 9999, 1000), "personal": usage(0, 9999, 1000)}

        state, client, _ = self.observe_external_login(response, fresh, {})

        self.assertIsNone(state["active"])
        self.assertEqual(state["status"], "degraded")
        self.assertEqual(state["account_error"], "UsageUnavailable")
        self.assertEqual([call.args[0] for call in client.request.call_args_list], ["account/read"])

    def test_failed_identity_read_does_not_report_the_previous_account_as_current(self):
        """현재 계정 조회가 실패하면 캐시를 현재 계정으로 단정하지 않고 전환을 보류한다."""
        fresh = {"company": usage(0, 9999, 1000), "personal": usage(0, 9999, 1000)}

        state, client, _ = self.observe_external_login(UsageUnavailable("unavailable"), fresh, {})

        self.assertIsNone(state["active"])
        self.assertEqual(state["status"], "degraded")
        self.assertNotIn("account_observed_at", state)
        self.assertEqual([call.args[0] for call in client.request.call_args_list], ["account/read"])

    def test_observer_cleanup_runs_even_when_usage_is_unavailable(self):
        """계정을 고를 수 없어도 감독 구독의 정리는 계속한다."""
        self.run_monitor([({}, {"company": "Timeout"})])

        self.runtime.release_subscriptions.assert_called_once_with()
        self.runtime.select.assert_not_called()

    def test_unchanged_status_writes_heartbeat_but_preference_is_saved_immediately(self):
        """변화가 없으면 30초마다 저장하고 수동 선택은 다음 2초 주기에 바로 기록한다."""
        clock = [1000]
        stop = Mock()
        stop.is_set.side_effect = lambda: clock[0] > 1060
        stop.wait.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        runtime = Mock(active='company')
        runtime.select.return_value = True
        fresh = {'company': usage(10, 9999, 1000), 'personal': usage(10, 9999, 1000)}
        written = []
        with patch('supervisor.time.time', side_effect=lambda: clock[0]), \
             patch('supervisor.collect', return_value=(fresh, {})), \
             patch('supervisor.save', side_effect=lambda state: written.append(state['updated_at'])), \
             patch('supervisor.preference', side_effect=lambda: (
                 {'preferred': 'personal', 'requested_at': 1010} if clock[0] >= 1010 else {})):

            monitor(runtime, {}, stop, {})

        self.assertEqual(written, [1000, 1010, 1040])

    def run_monitor(self, batches, preferred="company", requested=None):
        clock = [1000]
        stop = Mock()
        stop.is_set.side_effect = lambda: clock[0] >= 1000 + len(batches) * 61
        stop.wait.side_effect = lambda _: clock.__setitem__(0, clock[0] + 61)
        runtime = Mock(active=None)
        runtime.process.poll.return_value = None
        selected = []

        def select(name, *, force=False):
            selected.append(name)
            runtime.active = name
            return True

        runtime.select.side_effect = select
        state = {"preferred": preferred}
        with patch("supervisor.time.time", side_effect=lambda: clock[0]), \
             patch("supervisor.collect", side_effect=batches), patch("supervisor.save"), \
             patch("supervisor.preference", return_value=requested or {}):
            monitor(runtime, {}, stop, state)
        self.runtime = runtime
        return selected, state

    def test_personal_preference_is_used_by_the_running_monitor(self):
        """두 계정 모두 여유가 있으면 저장한 개인 우선 설정을 적용한다."""
        fresh = {"company": usage(76, 9999, 1000), "personal": usage(0, 9999, 1000)}

        selected, state = self.run_monitor([(fresh, {})], preferred="personal")

        self.assertEqual(selected, ["personal"])
        self.assertEqual(state["preferred"], "personal")

    def test_running_monitor_applies_fallback_and_both_high_policy(self):
        batches = [({"company": usage(company, 9999, 1000),
                     "personal": usage(personal, 9999, 1000)}, {})
                   for company, personal in ((5, 20), (95, 20), (95, 95), (0, 95))]
        selected, state = self.run_monitor(batches)
        self.assertEqual(selected, ["company", "personal", "personal", "company"])
        self.assertEqual(state["active"], "company")

    def test_limit_stopped_work_continues_only_on_an_account_below_the_threshold(self):
        batches = [({"company": usage(company, 9999, 1000),
                     "personal": usage(personal, 9999, 1000)}, {})
                   for company, personal in ((95, 20), (95, 95))]
        selected, _ = self.run_monitor(batches)
        self.assertEqual(selected, ["personal", "personal"])
        self.runtime.continue_limited.assert_called_once_with()

    def test_lookup_failure_keeps_current_account_and_old_reset_record(self):
        first = {"company": usage(5, 9999, 1000), "personal": usage(20, 9999, 1000)}
        selected, state = self.run_monitor([(first, {}), ({}, {"company": "Timeout"})])
        self.assertEqual(selected, ["company"])
        self.assertEqual(state["active"], "company")
        self.assertEqual(state["status"], "degraded")
        self.assertEqual(state["accounts"]["company"]["windows"]["primary"]["resets_at"], 9999)


if __name__ == "__main__":
    unittest.main()
