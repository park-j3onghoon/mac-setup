import contextlib
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import re
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
HEAD = 'a' * 40
NEW_HEAD = 'b' * 40
REVIEW_URL = 'https://github.com/acme/widgets/pull/7#pullrequestreview-11'


class Crash(Exception):
    """봇 프로세스가 그 자리에서 죽은 것처럼 실행을 끊는다."""


def pull_request(number=7, head=HEAD, state='OPEN'):
    return {'number': number, 'headRefOid': head, 'url': f'https://github.com/{REPO}/pull/{number}', 'state': state}


class ReviewBotTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.state_dir = root / 'state'
        for name in ('lib', 'skills'):
            (root / 'claude' / name).mkdir(parents=True)
        self.patch('CLAUDE_HOME', root / 'claude')
        self.url_log = root / 'ai-review-urls.txt'
        self.patch('URL_LOG', self.url_log)
        self.pulls = {7: pull_request()}
        self.requested = [7]
        self.draft = {'event': 'APPROVE', 'body': 'LGTM!',
                      'comments': [{'path': 'app.py', 'line': 3, 'side': 'RIGHT', 'body': '이름을 바꾸면 좋겠습니다.'}]}
        self.result_line = '초안 · APPROVE · CRITICAL 0 · INFO 1'
        self.writes_draft = True
        self.heads_after_review = []
        self.my_reviews = {}
        self.send_failures = []
        self.crashes_after_post = False
        self.sent = []
        self.patch('list_review_requests', lambda repo: [dict(self.pulls[number]) for number in self.requested])
        self.patch('view_pull_request', lambda repo, number: dict(self.pulls[number]))
        self.patch('current_login', lambda: 'me')
        self.patch('review_url_on', lambda repo, number, sha, login: self.my_reviews.get((number, sha)))
        self.patch('send_review', self.send_review)
        self.run_claude = self.patch('run_claude', mock.Mock(side_effect=self.claude))
        self.notify = self.patch('notify', mock.Mock())
        self.register = self.patch('register_launch_agent', mock.Mock())

    def patch(self, name, value):
        patcher = mock.patch.object(review_bot, name, value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def claude(self, prompt, settings, run_dir, session):
        """ai-review --draft처럼 리뷰할 때의 head로 review.json을 쓰고 결과 줄을 낸다."""
        number = int(re.search(r'/pull/(\d+) ', prompt).group(1))
        if self.writes_draft:
            draft = {'commit_id': self.pulls[number]['headRefOid'], **self.draft}
            (run_dir / 'review.json').write_text(json.dumps(draft, ensure_ascii=False))
        if self.heads_after_review:
            self.pulls[number]['headRefOid'] = self.heads_after_review.pop(0)
        return review_bot.ClaudeRun(0, f'초안 전문\n\n{self.result_line}', ())

    def send_review(self, repo, number, review):
        self.sent.append(review)
        if self.send_failures:
            raise self.send_failures.pop(0)
        self.my_reviews[(number, review['commit_id'])] = REVIEW_URL
        if self.crashes_after_post:
            self.crashes_after_post = False
            raise Crash()
        return REVIEW_URL

    def bot(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return review_bot.main(['--state-dir', str(self.state_dir), *args])

    def run_bot(self, auto=False):
        return self.bot('run', '--repo', REPO, *(('--auto-repo', REPO) if auto else ()))

    def state(self):
        return json.loads((self.state_dir / 'state.json').read_text())

    def entry(self, number=7):
        return self.state()['prs'][f'{REPO}#{number}']

    def test_draft_repo_request_becomes_a_draft_without_writing_to_github(self):
        """초안 레포 요청은 GitHub에 아무것도 올리지 않고, 초안 결과와 이어 받을 세션을 기록한다."""
        self.run_bot()

        prompt, _, _, session = self.run_claude.call_args.args
        entry = self.entry()
        self.assertEqual(self.sent, [])
        self.assertIn(f'{REPO}/pull/7 --draft', prompt)
        self.assertEqual((entry['status'], entry['mode'], entry['sha'], entry['event'], entry['critical'], entry['info']),
                         ('draft', 'draft', HEAD, 'APPROVE', 0, 1))
        self.assertEqual(entry['session'], session)
        self.assertIsNone(self.state()['running'])
        self.assertIn('세션으로 가기', self.notify.call_args.args[0])

    def test_auto_repo_request_is_posted_once_after_checks(self):
        """자동 레포 요청은 초안을 확인한 뒤 리뷰 한 건만 올리고, 리뷰 주소를 기록과 URL 기록에 남긴다."""
        self.run_bot(auto=True)

        entry = self.entry()
        self.assertEqual([review['commit_id'] for review in self.sent], [HEAD])
        self.assertEqual((entry['status'], entry['reviewUrl']), ('posted', REVIEW_URL))
        self.assertEqual(self.url_log.read_text(), REVIEW_URL + '\n')

    def test_review_session_writes_only_its_run_folder_and_has_no_github_write_command(self):
        """모델 세션은 정한 경로만 읽고, 리뷰 폴더 아래에만 쓰고, GitHub에 쓰는 명령을 받지 못한다."""
        self.run_bot(auto=True)

        _, settings, run_dir, _ = self.run_claude.call_args.args
        allow = json.loads(settings.read_text())['permissions']['allow']
        readable = [review_bot.rule_path(path) for path in
                    (review_bot.HOME / 'acme/widgets', run_dir, review_bot.SIMPLE_DESIGN, review_bot.CLAUDE_HOME)]
        reads = [rule for rule in allow if rule.startswith('Read(')]
        self.assertEqual([rule for rule in allow if rule.startswith(('Edit(', 'Write('))],
                         [f'Edit({review_bot.rule_path(run_dir)}/**)'])
        self.assertEqual([rule for rule in reads if not rule[len('Read('):].startswith(tuple(readable))], [])
        self.assertEqual([rule for rule in allow if rule.startswith('Bash(gh ')
                          and any(f' {option}' in rule for option in review_bot.GH_WRITE_OPTIONS)], [])

    def test_closed_pull_request_is_recorded_without_posting(self):
        """리뷰하는 사이 PR이 닫히면 올리지 않고 closed로 적는다."""
        self.pulls[7]['state'] = 'MERGED'

        self.run_bot(auto=True)

        self.assertEqual(self.sent, [])
        self.assertEqual(self.entry()['status'], 'closed')

    def test_new_commit_before_posting_is_reviewed_once_more_and_posted(self):
        """올리기 직전에 head가 바뀌었으면 새 head로 한 번 다시 리뷰해 그 초안을 올린다."""
        self.heads_after_review = [NEW_HEAD]

        self.run_bot(auto=True)

        self.assertEqual(self.run_claude.call_count, 2)
        self.assertEqual([review['commit_id'] for review in self.sent], [NEW_HEAD])
        self.assertEqual(self.entry()['status'], 'posted')

    def test_commits_arriving_again_after_the_second_review_leave_a_draft_for_the_user(self):
        """다시 리뷰한 뒤에도 head가 또 바뀌면 올리지 않고 사람이 세션에서 볼 초안으로 남긴다."""
        self.heads_after_review = [NEW_HEAD, 'c' * 40]

        self.run_bot(auto=True)

        entry = self.entry()
        self.assertEqual(self.sent, [])
        self.assertEqual((entry['status'], entry['mode'], entry['sha']), ('draft', 'draft', NEW_HEAD))
        self.assertIn('세션으로 가기', self.notify.call_args.args[0])

    def test_draft_with_a_secret_is_not_posted(self):
        """초안에 토큰 꼴 문자열이 있으면 올리지 않고 실패로 알린다."""
        self.draft['body'] = '키가 보입니다 AKIA' + 'A' * 16

        self.run_bot(auto=True)

        self.assertEqual(self.sent, [])
        self.assertEqual(self.entry()['status'], 'failed')
        self.assertIn('비밀값', self.notify.call_args.args[0])

    def test_line_not_found_rejection_moves_line_comments_into_the_body(self):
        """줄을 찾지 못했다는 422면 줄 코멘트를 본문 끝으로 옮겨 한 번 더 보내 올린다."""
        self.send_failures = [review_bot.ReviewRejected(422, '{"errors":["Line could not be resolved"]}')]

        self.run_bot(auto=True)

        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[1]['comments'], [])
        self.assertIn('`app.py:3` 이름을 바꾸면 좋겠습니다.', self.sent[1]['body'])
        self.assertEqual(self.entry()['status'], 'posted')

    def test_other_rejection_is_recorded_as_a_failure_with_its_message(self):
        """그 밖의 게시 거절은 응답 메시지와 함께 실패로 적고 알린다."""
        self.send_failures = [review_bot.ReviewRejected(403, '{"message":"Resource not accessible"}')]

        self.run_bot(auto=True)

        entry = self.entry()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(entry['status'], 'failed')
        self.assertIn('Resource not accessible', entry['note'])
        self.assertIn('리뷰 실패', self.notify.call_args.args[0])

    def test_review_fails_when_its_result_does_not_match_a_valid_draft(self):
        """결과 줄이 없거나, review.json이 없거나 꼴이 다르거나, 둘의 event가 다르면 그 리뷰는 실패다."""
        left_side = [{'path': 'app.py', 'line': 3, 'side': 'LEFT', 'body': '왼쪽 줄'}]
        cases = {
            '결과 줄 없음': {'result_line': '리뷰를 마쳤습니다'},
            'review.json 없음': {'writes_draft': False},
            'review.json 꼴이 다름': {'draft': {**self.draft, 'comments': left_side}},
            'event가 다름': {'result_line': '초안 · COMMENT · CRITICAL 1 · INFO 0'},
        }
        for name, change in cases.items():
            with self.subTest(name), mock.patch.multiple(self, **change):
                self.bot('review', '--repo', REPO, '7')

                self.assertEqual(self.entry()['status'], 'failed')

    def test_run_that_died_after_posting_is_recorded_as_posted_by_the_next_run(self):
        """올린 뒤 기록하기 전에 죽은 실행은 다음 실행이 GitHub의 내 리뷰로 posted와 리뷰 주소를 채운다."""
        self.crashes_after_post = True
        with self.assertRaises(Crash):
            self.run_bot(auto=True)
        self.requested = []

        self.run_bot(auto=True)

        entry = self.entry()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual((entry['status'], entry['reviewUrl']), ('posted', REVIEW_URL))
        self.assertEqual(self.url_log.read_text(), REVIEW_URL + '\n')
        self.assertIsNone(self.state()['running'])

    def test_auto_draft_left_before_posting_is_posted_by_the_next_run_without_reviewing_again(self):
        """올리기 전에 죽어 남은 자동 레포 초안은 다음 실행이 다시 리뷰하지 않고 올리기만 한다."""
        self.send_failures = [Crash()]
        with self.assertRaises(Crash):
            self.run_bot(auto=True)

        self.run_bot(auto=True)

        self.assertEqual(self.run_claude.call_count, 1)
        self.assertEqual(list(self.my_reviews), [(7, HEAD)])
        self.assertEqual(self.entry()['status'], 'posted')

    def test_same_commit_request_after_my_review_notifies_once_without_reviewing_again(self):
        """내 리뷰가 있는 커밋으로 다시 요청되면 다시 리뷰하지 않고, 몇 번을 돌아도 한 번만 알린다."""
        self.run_bot(auto=True)
        self.notify.reset_mock()

        self.run_bot(auto=True)
        self.run_bot(auto=True)

        self.assertEqual(self.run_claude.call_count, 1)
        self.notify.assert_called_once()
        self.assertEqual(self.entry()['status'], 'skipped')

    def test_failed_review_is_retried_up_to_the_limit_and_again_on_a_new_commit(self):
        """실패한 리뷰는 같은 커밋에서 정한 횟수까지만 다시 하고, 새 커밋이 올라오면 다시 한다."""
        self.writes_draft = False

        for _ in range(review_bot.MAX_ATTEMPTS + 1):
            self.run_bot()
        calls_on_first_commit = self.run_claude.call_count
        self.pulls[7]['headRefOid'] = NEW_HEAD
        self.run_bot()

        entry = self.entry()
        self.assertEqual(calls_on_first_commit, review_bot.MAX_ATTEMPTS)
        self.assertEqual(self.run_claude.call_count, review_bot.MAX_ATTEMPTS + 1)
        self.assertEqual((entry['head'], entry['status'], entry['attempts']), (NEW_HEAD, 'failed', 1))

    def test_install_skips_requests_waiting_before_install_until_their_commit_changes(self):
        """설치 전부터 기다리던 요청은 리뷰하지 않고, 그 PR에 새 커밋이 올라오면 리뷰한다."""
        self.bot('install', '--repo', REPO)

        self.run_bot()
        self.pulls[7]['headRefOid'] = NEW_HEAD
        self.run_bot()

        self.assertEqual(self.run_claude.call_count, 1)
        self.register.assert_called_once()

    def test_run_reviews_nothing_while_another_run_holds_the_lock(self):
        """다른 실행이 잠금을 잡고 있으면 리뷰하지 않고 끝난다."""
        self.state_dir.mkdir(parents=True)

        with (self.state_dir / 'lock').open('w') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.run_bot()

        self.run_claude.assert_not_called()

    def test_notifies_once_when_github_lookups_keep_failing(self):
        """GitHub 조회가 연속으로 실패하면 정한 횟수째에 한 번만 알린다."""
        error = subprocess.CalledProcessError(1, ['gh'], stderr='HTTP 401: Bad credentials')
        self.patch('list_review_requests', mock.Mock(side_effect=error))

        for _ in range(review_bot.POLL_FAILURES_TO_NOTIFY + 1):
            self.run_bot()

        self.notify.assert_called_once()


if __name__ == '__main__':
    unittest.main()
