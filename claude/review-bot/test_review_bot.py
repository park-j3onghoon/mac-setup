import contextlib
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location('review_bot', Path(__file__).with_name('review_bot.py'))
review_bot = importlib.util.module_from_spec(SPEC)
# dataclass가 문자열 타입 표기를 풀 때 sys.modules에서 모듈을 찾는다.
sys.modules['review_bot'] = review_bot
SPEC.loader.exec_module(review_bot)

REPO = 'acme/widgets'
POSTED = 'APPROVE · CRITICAL 0 · INFO 1 · https://github.com/acme/widgets/pull/7#pullrequestreview-11'


def pull_request(number=7, head='a' * 40):
    return {'number': number, 'headRefOid': head, 'url': f'https://github.com/{REPO}/pull/{number}'}


def claude_run(final_text=POSTED, exit_code=0):
    return review_bot.ClaudeRun(exit_code, final_text, ())


class ReviewBotTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.state_dir = root / 'state'
        for name in ('lib', 'skills'):
            (root / 'claude' / name).mkdir(parents=True)
        self.patch('CLAUDE_HOME', root / 'claude')
        self.requests = []
        self.my_reviews = set()
        self.patch('list_review_requests', lambda repo: list(self.requests))
        self.patch('current_login', lambda: 'me')
        self.patch('has_review_on', lambda repo, number, head, login: (number, head) in self.my_reviews)
        self.patch('view_pull_request', lambda repo, number: pull_request(number))
        self.run_claude = self.patch('run_claude', mock.Mock(return_value=claude_run()))
        self.notify = self.patch('notify', mock.Mock())
        self.register = self.patch('register_launch_agent', mock.Mock())

    def patch(self, name, value):
        patcher = mock.patch.object(review_bot, name, value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def bot(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return review_bot.main(['--state-dir', str(self.state_dir), *args])

    def entry(self, number=7):
        return json.loads((self.state_dir / 'state.json').read_text())['prs'][f'{REPO}#{number}']

    def posting_rules(self, call):
        settings = json.loads(Path(call.args[1]).read_text())
        return [rule for rule in settings['permissions']['allow'] if 'gh api -X POST' in rule]

    def test_reviews_a_new_request_once_and_records_the_posted_review(self):
        """나에게 새로 온 리뷰 요청을 한 번 리뷰하고, 올린 결과를 상태와 알림에 남긴다."""
        self.requests = [pull_request()]

        self.bot('run', '--repo', REPO)

        self.assertEqual(self.run_claude.call_count, 1)
        entry = self.entry()
        self.assertEqual((entry['sha'], entry['status'], entry['note']), ('a' * 40, 'posted', POSTED))
        self.notify.assert_called_once_with(f'widgets#7 {POSTED}')

    def test_same_commit_request_after_my_review_notifies_once_without_reviewing_again(self):
        """내 리뷰가 있는 커밋으로 다시 요청되면 다시 리뷰하지 않고, 몇 번을 돌아도 한 번만 알린다."""
        self.requests = [pull_request()]
        self.bot('run', '--repo', REPO)
        self.my_reviews.add((7, 'a' * 40))
        self.notify.reset_mock()

        self.bot('run', '--repo', REPO)
        self.bot('run', '--repo', REPO)

        self.assertEqual(self.run_claude.call_count, 1)
        self.notify.assert_called_once()
        self.assertEqual(self.entry()['status'], 'skipped')

    def test_failed_review_is_retried_up_to_the_limit_and_again_on_a_new_commit(self):
        """실패한 리뷰는 같은 커밋에서 정한 횟수까지만 다시 하고, 새 커밋이 올라오면 다시 한다."""
        self.requests = [pull_request()]
        self.run_claude.return_value = claude_run('', exit_code=1)

        for _ in range(review_bot.MAX_ATTEMPTS + 1):
            self.bot('run', '--repo', REPO)
        calls_on_first_commit = self.run_claude.call_count
        self.requests = [pull_request(head='b' * 40)]
        self.bot('run', '--repo', REPO)

        self.assertEqual(calls_on_first_commit, review_bot.MAX_ATTEMPTS)
        self.assertEqual(self.run_claude.call_count, review_bot.MAX_ATTEMPTS + 1)
        entry = self.entry()
        self.assertEqual((entry['sha'], entry['status'], entry['attempts']), ('b' * 40, 'failed', 1))

    def test_install_skips_requests_waiting_before_install_until_their_commit_changes(self):
        """설치 전부터 기다리던 요청은 리뷰하지 않고, 그 PR에 새 커밋이 올라오면 리뷰한다."""
        self.requests = [pull_request()]
        self.bot('install', '--repo', REPO)

        self.bot('run', '--repo', REPO)
        self.requests = [pull_request(head='b' * 40)]
        self.bot('run', '--repo', REPO)

        self.assertEqual(self.run_claude.call_count, 1)
        self.register.assert_called_once()

    def test_run_reviews_nothing_while_another_run_holds_the_lock(self):
        """다른 실행이 잠금을 잡고 있으면 리뷰하지 않고 끝난다."""
        self.requests = [pull_request()]
        self.state_dir.mkdir(parents=True)

        with (self.state_dir / 'lock').open('w') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.bot('run', '--repo', REPO)

        self.run_claude.assert_not_called()

    def test_review_sandbox_allows_posting_only_to_the_reviewed_pull_request(self):
        """리뷰 권한은 리뷰하는 PR 한 건에만 올리게 하고, 시험 실행에서는 올리지 못하게 한다."""
        self.bot('review', '--repo', REPO, '7')
        self.bot('review', '--repo', REPO, '8', '--dry-run')

        real, dry = (self.posting_rules(call) for call in self.run_claude.call_args_list)
        self.assertTrue(real)
        self.assertTrue(all(f'repos/{REPO}/pulls/7/reviews' in rule for rule in real))
        self.assertEqual(dry, [])

    def test_notifies_once_when_github_lookups_keep_failing(self):
        """GitHub 조회가 연속으로 실패하면 정한 횟수째에 한 번만 알린다."""
        error = subprocess.CalledProcessError(1, ['gh'], stderr='HTTP 401: Bad credentials')
        self.patch('list_review_requests', mock.Mock(side_effect=error))

        for _ in range(review_bot.POLL_FAILURES_TO_NOTIFY + 1):
            self.bot('run', '--repo', REPO)

        self.notify.assert_called_once()


if __name__ == '__main__':
    unittest.main()
