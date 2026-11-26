"""Regression tests for account changes, transcript rotation and monitoring boundaries."""
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from helpers import NOW, make_app
from macos import KeychainError, SavedCredentialError, Vault
import measurement
import monitoring
import refresh
import refresh_hook
from service import Switcher
from storage import SwitcherError
from switcher import enroll, measure_and_review, run_app_command, tick_once
from test_measurement import event, snapshot
from test_refresh import FakeRunner, SESSION, SessionFixture, limit_error, task_notification


def stdio(*pids, kind='PIPE'):
    """`lsof -Fft` output for processes whose fds 0 and 1 are of the given kind."""
    return ''.join(f'p{pid}\nf0\nt{kind}\nf1\nt{kind}\n' for pid in pids)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.app = make_app(self.root)
        self.state = self.app.state
        self.primary, self.fallback = self.app.accounts
        self.projects = Path(self.app.config['config_home']) / 'projects'
        self.projects.mkdir()
        self.meter = measurement.Measurement(self.state, self.projects)

    def append(self, path, payload, at):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            stream.write(json.dumps(payload) + '\n')
        os.utime(path, (at, at))

    def select_login(self, email):
        target = self.app.vault.read(email)
        self.app.live.write_account(target['account'])
        self.app.vault.active['claudeAiOauth'] = target['oauth']

    def test_native_login_emits_one_restart_even_after_a_dry_run(self):
        """외부 로그인을 먼저 읽은 것이 사전 확인인 경우에도 다음 적용에서 신호를 한 번 남긴다."""
        self.state.save('runtime', {'active': self.primary})
        self.select_login(self.fallback)

        self.app.tick(now=NOW)
        first = self.app.tick(apply=True, now=NOW + 1)
        second = self.app.tick(apply=True, now=NOW + 2)

        self.assertTrue(first['identity_changed'])
        self.assertFalse(second.get('identity_changed'))
        self.assertEqual(self.state.load('session_refresh')['since'], NOW + 1)

    def test_wrong_browser_login_restores_verified_backup_and_keeps_other_fields(self):
        """예상 밖 브라우저 로그인을 되돌릴 때 연결 설정과 제3 계정의 독립성을 보존한다."""
        def other_login(*args, **kwargs):
            self.app.live.write_account({'emailAddress': 'other@example.com'})
            self.app.vault.active.update(claudeAiOauth={'accessToken': 'other'}, separate='keep')
            return SimpleNamespace(returncode=0)

        with patch('switcher.subprocess.run', side_effect=other_login):
            with self.assertRaisesRegex(SwitcherError, 'restore-enrollment'):
                enroll(self.app, 'fallback')

        self.assertEqual(self.app.live.read()[1]['emailAddress'], 'other@example.com')
        run_app_command(SimpleNamespace(command='restore-enrollment'), self.state, self.app)
        blob, account = self.app.live.read()
        self.assertEqual(account['emailAddress'], self.primary)
        self.assertEqual(blob['claudeAiOauth'], self.app.vault.read(self.primary)['oauth'])
        self.assertEqual(blob['separate'], 'keep')
        self.assertIsNone(self.app.vault.read('other@example.com'))
        self.assertIsNone(self.app.vault.read('__transaction__'))

    def test_interrupted_enrollment_restore_finishes_without_overwriting_new_login(self):
        """복구 직전 다른 로그인 세대가 생긴 경우에는 그 로그인을 덮어쓰지 않는다."""
        target = self.app.vault.read(self.primary)
        self.select_login(self.fallback)
        unexpected = self.app.live.read()[1]
        self.app.vault.crash_after_write = True
        with self.assertRaises(KeyboardInterrupt):
            self.app.restore_enrollment(target, unexpected)
        self.app.vault.active['claudeAiOauth'] = {'accessToken': 'different-generation'}

        with self.assertRaisesRegex(SwitcherError, 'manual recovery'):
            self.app.recover()
        self.assertEqual(self.app.vault.active['claudeAiOauth']['accessToken'], 'different-generation')
        self.app.vault.active['claudeAiOauth'] = target['oauth']
        self.app.recover()
        self.assertEqual(self.app.live.read()[1], target['account'])
        self.assertIsNone(self.app.vault.read('__transaction__'))

    def test_poll_during_browser_login_defers_and_enrollment_completes(self):
        """브라우저가 B를 선택한 직후의 데몬 점검은 등록이 끝날 때까지 교체하지 않는다."""
        self.app.api.percent['token-personal'] = 10
        def login(*args, **kwargs):
            self.select_login(self.fallback)
            result = self.app.tick(apply=True, now=NOW)
            self.assertEqual(result['reason'], 'waiting_for_operation')
            return SimpleNamespace(returncode=0)

        with patch('switcher.subprocess.run', side_effect=login), redirect_stdout(io.StringIO()):
            enroll(self.app, 'fallback')

        self.assertEqual(self.app.live.read()[1]['emailAddress'], self.fallback)

    def test_restart_validates_native_layout_before_restoring_a_third_account(self):
        """브라우저의 제3 계정 상태에서 프로세스를 다시 시작해도 호환성 확인 뒤 A를 복원한다."""
        previous = self.app.vault.read(self.primary)
        foreign = {'emailAddress': 'other@example.com', 'accountUuid': 'other'}
        self.app.live.write_account(foreign)
        self.app.vault.active['claudeAiOauth'] = {'accessToken': 'third'}
        with patch.object(self.app.vault, 'write_active', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.app.restore_enrollment(previous, foreign)
        fresh = Switcher(self.app.config, self.state, self.app.live, self.app.vault, self.app.api)
        self.app.api.percent['token-personal'] = 10
        def accepts_current(executable, home, accounts, prior):
            self.assertIn(self.app.live.read()[1]['emailAddress'], accounts)
            return {}

        with patch('service.check_compatibility', side_effect=accepts_current) as guard:
            fresh.tick(apply=True, now=NOW)

        self.assertEqual(guard.call_count, 1)
        self.assertEqual(fresh.live.read()[1], previous['account'])
        self.assertIsNone(self.app.vault.read('__transaction__'))

    def test_manual_measurements_reconstruct_only_new_token_increments(self):
        """수동 측정 두 번 사이에 늘어난 스트리밍 카운터와 새 요청만 합산한다."""
        self.app.vault.read_active_for_measurement = self.app.vault.read_active
        path = self.projects / 'session.jsonl'
        self.append(path, event('a', NOW - 1, output=10), NOW)
        command = SimpleNamespace(command='measure-once')
        with patch('measurement.time.time', return_value=NOW), redirect_stdout(io.StringIO()):
            run_app_command(command, self.state, self.app)
        # Stream fragments may retain the timestamp of the original response.
        self.append(path, event('a', NOW - 1, output=13), NOW + 30)
        self.append(path, event('b', NOW + 50, output=2), NOW + 50)

        with patch('measurement.time.time', return_value=NOW + 60), redirect_stdout(io.StringIO()) as output:
            run_app_command(command, self.state, self.app)
        row = json.loads(output.getvalue())

        self.assertFalse(row['tokens']['baseline'])
        totals = row['tokens']['by_model']['claude-opus-5-5']
        self.assertEqual((totals['requests'], totals['output_tokens']), (1, 5))
        self.assertEqual(row['token_account_estimate'], self.primary)

    def test_clock_rollback_does_not_reopen_complete_plan(self):
        """완료한 계획은 벽시계를 종료 전으로 돌려도 기록하지 않는다."""
        self.state.save('monitoring', {'status': 'complete', 'ends_at': NOW})

        self.assertIsNone(self.meter.record(snapshot(NOW - 60, 10), NOW - 60))

    def test_delayed_and_ontime_daily_reports_keep_both_archives(self):
        """같은 날 실행한 지연 회차와 정시 회차를 개별 파일로 보존한다."""
        start = datetime(2026, 11, 1, 9, tzinfo=monitoring.KST).timestamp()
        monitoring.start(self.state, 5, start)
        due = start + 2 * monitoring.DAY

        late = monitoring.review_if_due(self.state, due - 3600)
        on_time = monitoring.review_if_due(self.state, due)

        first, second = (Path(p['last_report']).with_suffix('.json') for p in (late, on_time))
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(first.read_text())['generated_at'], due - 3600)
        self.assertEqual(json.loads(second.read_text())['generated_at'], due)

    def test_missing_reset_identity_excludes_increase_from_summary(self):
        """초기화 시각이 양쪽 모두 없으면 상승한 사용률도 검증 최대치에 포함하지 않는다."""
        self.meter.record(snapshot(NOW, 5, reset=None), NOW)
        row = self.meter.record(snapshot(NOW + 60, 9, reset=None), NOW + 60)

        self.assertFalse(row['quota_deltas'][0]['valid'])
        self.assertEqual(row['quota_deltas'][0]['reason'], 'unknown_reset')
        self.assertEqual(measurement.summarize(self.state)['windows'], [])

    def test_unwritten_switch_intervals_retain_counts_without_account_attribution(self):
        """상반된 미기록 전환 두 개의 카운트를 보존하고 계정 추정에서 제외한다."""
        self.meter.record(snapshot(NOW, 10), NOW)
        for i, email in enumerate((self.primary, self.fallback), 1):
            at = NOW + i * 40
            self.append(self.projects / 's.jsonl', event(str(i), at), at)
            with patch('measurement.os.open', side_effect=OSError('temporary')):
                with self.assertRaises(OSError):
                    self.meter.record(snapshot(at, 12, active=email, switched=True), at)

        at = NOW + 120
        self.append(self.projects / 's.jsonl', event('third', at), at)
        row = self.meter.record(snapshot(at, 13), at)

        self.assertEqual(row['tokens']['by_model']['claude-opus-5-5']['requests'], 3)
        self.assertIsNone(row['token_account_estimate'])

    def test_expired_append_checkpoint_does_not_block_next_plan(self):
        """동기화 실패 뒤 35일 보존 정리를 거친 새 계획에서 연속 두 행을 기록한다."""
        self.meter.record(snapshot(NOW, 10), NOW)
        with patch('measurement.os.fsync', side_effect=OSError('temporary')):
            with self.assertRaises(OSError):
                self.meter.record(snapshot(NOW + 60, 12), NOW + 60)
        self.state.save('monitoring', {'status': 'complete', 'ends_at': NOW + 90})
        future = NOW + 35 * 86400
        self.meter.record(snapshot(future, 10), future)
        monitoring.start(self.state, 1, future + 60)

        first = self.meter.record(snapshot(future + 90, 10), future + 90)
        second = self.meter.record(snapshot(future + 150, 11), future + 150)

        self.assertTrue(first['tokens']['baseline'])
        self.assertFalse(second['tokens']['baseline'])

    def test_private_backup_error_recovers_next_tick_without_global_halt(self):
        """활성 네이티브 항목이 정상인 동안 비활성 백업 읽기 한 번의 실패에서 자동 회복한다."""
        original = self.app.vault.read
        def read(email):
            if email == self.fallback:
                raise KeychainError('temporary private store failure')
            return original(email)

        with redirect_stdout(io.StringIO()), patch('switcher.time.time', return_value=NOW):
            with patch.object(self.app.vault, 'read', side_effect=read):
                first, delay, outcome = tick_once(self.app, True, None)
            second, _, _ = tick_once(self.app, True, outcome)

        self.assertEqual(first['errors'][self.fallback], 'saved_credential_unavailable')
        self.assertLessEqual(delay, 60)
        self.assertTrue(second['switched'])
        self.assertFalse(self.state.load('halt'))

    def test_notification_blocks_keep_limit_stop_but_real_user_blocks_end_it(self):
        """텍스트 배열로 쓴 시스템 알림과 같은 표현의 사용자 입력을 구분한다."""
        fix = SessionFixture(self.root / 'terminal')
        note = task_notification()
        note['message']['content'] = [{'type': 'text', 'text': note['message']['content']}]
        fix.transcript(limit_error(), note)
        projects = fix.home / 'projects'

        self.assertTrue(refresh.ended_with_limit_error(projects, SESSION))
        fix.transcript(limit_error(), {'type': 'user', 'message': note['message']})
        self.assertFalse(refresh.ended_with_limit_error(projects, SESSION))

    def test_private_item_failure_outside_candidate_read_remains_retryable(self):
        """전환 트랜잭션을 읽을 때의 전용 보관소 장애도 네이티브 인증 잠금으로 기록하지 않는다."""
        vault = Vault.__new__(Vault)
        vault.namespace = 'fixture'
        vault.keychain = Mock()
        vault.keychain.read.side_effect = KeychainError('temporary saved item error')
        with self.assertRaises(SavedCredentialError) as failure:
            vault.read('__transaction__')

        with patch.object(self.app.vault, 'read', side_effect=failure.exception), redirect_stdout(io.StringIO()):
            report, delay, _ = tick_once(self.app, True, None)

        self.assertIsNone(report)
        self.assertEqual(delay, 60)
        self.assertFalse(self.state.load('halt'))

    def test_stdio_mcp_shell_is_idle_but_task_output_or_unknown_pipe_stays_busy(self):
        """MCP 래퍼의 양방향 파이프를 확인하고 작업 출력이나 불명확한 셸은 보호한다."""
        tree = {101: [(102, 'sh')], 102: [(103, 'fixture-mcp-stdio')]}
        session = {'pid': 101, 'sessionId': SESSION}
        task = stdio(102) + 'p103\nf0\ntPIPE\nf1\ntREG\n'
        for descriptors, expected in ((stdio(102, 103), False), (task, True), ('', True)):
            with self.subTest(descriptors=descriptors):
                result = refresh.background_work(session, tree, self.projects, NOW,
                    runner=Mock(return_value=Mock(returncode=0, stdout=descriptors)))
                self.assertEqual(result, expected)

    def test_direct_stdio_mcp_servers_are_not_session_work(self):
        """Claude가 바로 띄운 stdio MCP 서버(`uv run …/mcp_server.py`와 그 python)는 입출력이 유닉스 소켓이면 작업으로 보지 않는다."""
        tree = {101: [(102, 'uv'), (103, 'caffeinate')], 102: [(104, 'python')]}
        runner = Mock(return_value=Mock(returncode=0, stdout=stdio(102, 104, kind='unix')))

        busy = refresh.background_work({'pid': 101, 'sessionId': SESSION}, tree, self.projects, NOW,
                                       runner=runner)

        self.assertFalse(busy)

    def test_metadata_only_copy_falls_back_to_older_transcript(self):
        """최근 사본에 시스템 메타데이터만 있으면 이전 대화 사본을 검사한다."""
        self.append(self.projects / 'old' / 'session.jsonl', limit_error(), NOW)
        self.append(self.projects / 'new' / 'session.jsonl', {'type': 'system'}, NOW + 5)

        self.assertTrue(refresh.ended_with_limit_error(self.projects, 'session'))

    def test_mcp_interpreter_is_identified_by_package_and_stdio(self):
        """node로 실행한 MCP 서버의 셸 래퍼도 작업이 없는 동안 재시작을 막지 않는다."""
        tree = {101: [(102, 'sh')], 102: [(103, 'node')]}
        runner = Mock(side_effect=[
            Mock(returncode=0, stdout='node /fixture/node_modules/example-mcp/server.js'),
            Mock(returncode=0, stdout=stdio(102, 103))])

        busy = refresh.background_work({'pid': 101, 'sessionId': SESSION}, tree,
                                       self.projects, NOW, runner=runner)

        self.assertFalse(busy)

    def test_optional_plan_read_failure_preserves_daemon_delay(self):
        """한 번 읽을 수 없는 측정 계획은 다음 전환 주기를 중단하지 않는다."""
        load = self.state.load
        def fail_plan(name, *args):
            if name == 'monitoring':
                raise PermissionError('temporary')
            return load(name, *args)

        with patch.object(self.state, 'load', side_effect=fail_plan), redirect_stdout(io.StringIO()):
            delay = measure_and_review(self.app, self.meter, None, 60)

        self.assertEqual(delay, 60)
        self.assertEqual(self.state.load('measurement_error')['type'], 'PermissionError')

    def test_transcript_reappearing_after_rotation_is_retried(self):
        """열기 직전에 이동된 실제 임시 대화가 다시 나타나면 도우미가 한도 응답을 확인한다."""
        fix = SessionFixture(self.root / 'terminal')
        fix.transcript(limit_error())
        helper = fix.restart(FakeRunner(fix))
        original = refresh.last_entry
        moved = []
        def rotate(path):
            if not moved:
                backup = path.with_suffix('.bak')
                path.rename(backup)
                moved.append(path)
                fix.clock.at(fix.clock() + 2, lambda: backup.rename(path))
            return original(path)

        with patch('refresh.last_entry', side_effect=rotate):
            self.assertTrue(helper.limited())

    def test_inactive_bundle_is_verified_before_its_usage_can_be_reported(self):
        """대상 키의 다른 이메일과 같은 이메일에 연결된 다른 소유자 토큰 모두 제외한다."""
        self.app.api.percent['token-personal'] = 10
        wrong = self.app.vault.read(self.primary)
        self.app.vault.write(self.fallback, wrong)
        for account in (wrong['account'], {'emailAddress': self.fallback, 'accountUuid': 'other'}):
            with self.subTest(account=account):
                self.app.vault.write(self.fallback, dict(wrong, account=account))
                result = self.app.tick(now=NOW)
                self.assertIn(self.fallback, result['errors'])
                self.assertNotIn(self.fallback, result['usage'])

    def test_restart_helper_distinguishes_invalid_state_from_another_owner(self):
        """상태 오류는 결과를 남기고 실제 중복 실행은 별도의 오류 결과를 남기지 않는다."""
        self.state.save('session_refresh', [])
        with patch('refresh_hook.state_dir', return_value=self.state.root), patch('refresh_hook.Path.home', return_value=self.root):
            with self.state.lock(refresh_hook.helper_lock('--helper', 'session', 'surface')):
                refresh_hook.helper('session', 'surface')
            log = self.state.root / refresh_hook.LOG
            self.assertFalse(log.exists())
            refresh_hook.helper('session', 'surface')

        self.assertEqual(json.loads(log.read_text())['outcome'], 'error:SwitcherError')

    def test_new_plan_begins_with_a_baseline_after_unobserved_gap(self):
        """두 주기 사이 교체한 측정 계획에 휴지기 요청을 귀속하지 않는다."""
        monitoring.start(self.state, 1, NOW - monitoring.DAY + 10)
        self.meter.record(snapshot(NOW, 10), NOW)
        self.append(self.projects / 's.jsonl', event('between', NOW + 25), NOW + 25)
        monitoring.start(self.state, 1, NOW + 40)

        row = self.meter.record(snapshot(NOW + 60, 15), NOW + 60)

        self.assertTrue(row['tokens']['baseline'])
        self.assertEqual(row['tokens']['by_model'], {})
        self.assertIsNone(row['token_interval_seconds'])

    def test_start_retries_missing_first_archive_without_extending_the_plan(self):
        """첫 리뷰 쓰기 실패 후 시작을 다시 요청하면 기존 기간의 보고서를 만든다."""
        with patch('monitoring.review_if_due', side_effect=OSError('temporary')):
            with self.assertRaises(OSError):
                monitoring.start(self.state, 2, NOW)

        result = monitoring.start(self.state, 2, NOW + 1)

        self.assertEqual(result['starts_at'], NOW)
        self.assertTrue(Path(result['last_report']).exists())

    def test_unchanged_log_reuses_checked_anchor_hash(self):
        """대화 파일이 그대로면 검증한 경계 해시를 한 번만 계산한다."""
        self.append(self.projects / 's.jsonl', event('a', NOW), NOW)
        tail = measurement.TokenTail(self.projects, NOW)
        tail.sample(NOW)

        with patch('measurement.hashlib.sha256', wraps=measurement.hashlib.sha256) as hashes:
            result = tail.sample(NOW + 60)

        self.assertEqual(result['by_model'], {})
        self.assertEqual(hashes.call_count, 1)

    def test_unchanged_requests_skip_retention_pass_but_still_expire(self):
        """최근 요청이 만료되기 전에는 보존 키 전체를 순회하지 않고 기한 뒤에는 회수한다."""
        self.append(self.projects / 's.jsonl', event('a', NOW), NOW)
        tail = measurement.TokenTail(self.projects, NOW)
        tail.sample(NOW)
        class Retained(dict):
            def items(self):
                raise AssertionError('unexpected full retention scan')
        tail.seen = Retained(tail.seen)

        tail.sample(NOW + 60)
        self.assertEqual(len(tail.seen), 1)
        tail.seen = dict(tail.seen)
        tail.sample(NOW + 3 * 3600)
        self.assertEqual(len(tail.seen), 0)
