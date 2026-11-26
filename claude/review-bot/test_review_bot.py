import contextlib
import fcntl
import importlib.util
import io
import json
import datetime
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
REQUESTED_AT = '2026-11-25T01:00:00Z'
REQUESTED_AGAIN_AT = '2026-11-25T03:00:00Z'
NOW = datetime.datetime(2026, 11, 26, tzinfo=datetime.timezone.utc)


class Crash(Exception):
    """봇 프로세스가 그 자리에서 죽은 것처럼 실행을 끊는다."""


def pull_request(number=7, head=HEAD, state='OPEN'):
    return {'number': number, 'headRefOid': head, 'url': f'https://github.com/{REPO}/pull/{number}', 'state': state,
            'title': f'PR {number}'}


def search_node(pull, requester, requested_at, fork=False):
    """GraphQL 검색 결과의 PR 노드. 팀에 온 요청은 `... on User` 조각이 비어 login이 없다."""
    events = [{'createdAt': '2026-11-01T00:00:00Z', 'actor': {'login': requester}, 'requestedReviewer': {}},
              {'createdAt': requested_at, 'actor': {'login': requester}, 'requestedReviewer': {'login': 'me'}}]
    return {'number': pull['number'], 'title': pull['title'], 'url': pull['url'], 'headRefOid': pull['headRefOid'],
            'isCrossRepository': fork, 'repository': {'nameWithOwner': REPO}, 'timelineItems': {'nodes': events}}


class ReviewBotTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.state_dir = root / 'state'
        for name in ('lib', 'skills'):
            (root / 'claude' / name).mkdir(parents=True)
        self.patch('CLAUDE_HOME', root / 'claude')
        self.clone = root / 'clones/widgets'
        self.clone.mkdir(parents=True)
        self.patch('clone_path', lambda repo: self.clone)
        self.git_calls = []
        self.ancestor_code = 0
        self.patch('git', self.git)
        self.patch('clone_repo', lambda repo, clone: self.git_calls.append('clone'))
        self.switcher = root / 'switcher'
        self.switcher.mkdir()
        self.patch('SWITCHER_DIR', self.switcher)
        self.patch('pause', self.pause)
        self.weekly = [{'percent': 40}, {'percent': 30}]
        self.switcher_answers = True
        self.end_codex = self.patch('end_codex_session', mock.Mock())
        self.running_during_review = []
        self.url_log = root / 'ai-review-urls.txt'
        self.patch('URL_LOG', self.url_log)
        self.pulls = {7: pull_request()}
        self.requests = {7: {'requester': 'bob', 'requested_at': REQUESTED_AT}}
        self.page_size = 100
        self.now = NOW
        self.draft = {'event': 'APPROVE', 'body': 'LGTM!',
                      'comments': [{'path': 'app.py', 'line': 3, 'side': 'RIGHT', 'body': '이름을 바꾸면 좋겠습니다.'}]}
        self.result_line = '초안 · APPROVE · CRITICAL 0 · INFO 1'
        self.writes_draft = True
        self.heads_after_review = []
        self.my_reviews = {}
        self.send_failures = []
        self.crashes_after_post = False
        self.sent = []
        self.fetch_pages = self.patch('fetch_review_request_pages', mock.Mock(side_effect=self.search_pages))
        self.patch('last_review_commit', self.last_review_commit)
        self.patch('now', lambda: self.now)
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
        self.running_during_review.append(self.state()['running'])
        number = int(re.search(r'/pull/(\d+) ', prompt).group(1))
        if self.writes_draft:
            draft = {'commit_id': self.pulls[number]['headRefOid'], **self.draft}
            (run_dir / 'review.json').write_text(json.dumps(draft, ensure_ascii=False))
        if self.heads_after_review:
            self.pulls[number]['headRefOid'] = self.heads_after_review.pop(0)
        return review_bot.ClaudeRun(0, f'초안 전문\n\n{self.result_line}', ())

    def search_pages(self):
        nodes = [search_node(self.pulls[number], **request) for number, request in self.requests.items()]
        chunks = [nodes[start:start + self.page_size] for start in range(0, len(nodes), self.page_size)] or [[]]
        return [{'data': {'search': {'nodes': chunk}}} for chunk in chunks]

    def pause(self, seconds):
        """기다리는 동안 시계를 돌리고, 읽기 요청이 와 있으면 계정 전환기처럼 두 계정을 읽어 runtime.json에 쓴다."""
        self.now += datetime.timedelta(seconds=seconds)
        if self.switcher_answers and (self.switcher / 'usage_request.json').exists():
            self.answer_switcher()

    def answer_switcher(self, age=0):
        moment = self.now.timestamp() - age
        usage = {f'account{index}': self.switcher_reading(reading, moment) for index, reading in enumerate(self.weekly)}
        (self.switcher / 'runtime.json').write_text(json.dumps({'sampled_at': moment, 'usage': usage}))
        (self.switcher / 'usage_request.json').unlink(missing_ok=True)

    @staticmethod
    def switcher_reading(reading, moment):
        """전환기 runtime.json의 계정 한 건(usage.{계정}). age초 전에 읽었고, 주간 창은 resets_in초 뒤 초기화된다."""
        window = {'name': 'seven_day', 'percent': reading['percent'], 'resets_at': moment + reading.get('resets_in', 86400)}
        return {'checked_at': moment - reading.get('age', 0), 'stale': reading.get('stale', False), 'windows': [window]}

    def git(self, clone, *args, check=True):
        self.git_calls.append(args[0])
        code = self.ancestor_code if args[0] == 'merge-base' else 0
        return subprocess.CompletedProcess(['git', *args], code, '', '')

    def last_review_commit(self, repo, number, login):
        commits = [sha for reviewed, sha in self.my_reviews if reviewed == number]
        return commits[-1] if commits else None

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
        return self.bot('run', '--requester', 'bob', '--requester', 'alice', *(('--auto-repo', REPO) if auto else ()))

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
                    (self.clone, run_dir, review_bot.SIMPLE_DESIGN, review_bot.CLAUDE_HOME)]
        reads = [rule for rule in allow if rule.startswith('Read(')]
        self.assertEqual([rule for rule in allow if rule.startswith(('Edit(', 'Write('))],
                         [f'Edit({review_bot.rule_path(run_dir)}/**)'])
        self.assertEqual([rule for rule in reads if not rule[len('Read('):].startswith(tuple(readable))], [])
        self.assertEqual([rule for rule in allow if rule.startswith('Bash(gh ')
                          and any(f' {option}' in rule for option in review_bot.GH_WRITE_OPTIONS)], [])

    def test_incremental_diff_commands_are_allowed_in_the_review_session(self):
        """증분 diff 블록(~/.claude/lib/review/diff.md)이 쓰는 파이프 명령을 모델 세션 권한에 둔다."""
        self.run_bot()

        allow = json.loads(self.run_claude.call_args.args[1].read_text())['permissions']['allow']
        self.assertTrue({'Bash(sort -u)', 'Bash(grep -c .)', 'Bash(printf *)'} <= set(allow))

    def test_request_after_my_review_is_reviewed_from_my_last_reviewed_commit(self):
        """내가 리뷰한 PR에 다시 요청이 오면 클론을 최신화한 뒤 내 마지막 리뷰 커밋부터의 증분으로 리뷰한다."""
        self.my_reviews[(7, HEAD)] = REVIEW_URL
        self.pulls[7]['headRefOid'] = NEW_HEAD

        self.run_bot()

        prompt = self.run_claude.call_args.args[0]
        self.assertIn(f'--draft --since {HEAD}', prompt)
        self.assertEqual(self.git_calls, ['fetch', 'merge-base'])
        self.assertEqual(self.entry()['since'], HEAD)

    def test_force_pushed_pull_request_is_reviewed_in_full(self):
        """내 마지막 리뷰 커밋이 지금 head의 조상이 아니면(강제 push) 처음부터 전체를 리뷰한다."""
        self.my_reviews[(7, HEAD)] = REVIEW_URL
        self.pulls[7]['headRefOid'] = NEW_HEAD
        self.ancestor_code = 1

        self.run_bot()

        self.assertNotIn('--since', self.run_claude.call_args.args[0])
        self.assertIsNone(self.entry()['since'])

    def test_first_review_has_no_incremental_base(self):
        """내가 리뷰한 적 없는 PR은 증분 기준 없이 리뷰한다."""
        self.run_bot()

        self.assertNotIn('--since', self.run_claude.call_args.args[0])
        self.assertEqual(self.git_calls, ['fetch'])

    def test_missing_clone_is_cloned_before_the_review(self):
        """리뷰할 레포의 클론이 없으면 리뷰 전에 받아 둔다."""
        self.clone.rmdir()

        self.run_bot()

        self.assertEqual(self.git_calls, ['clone', 'fetch'])
        self.run_claude.assert_called_once()

    def test_clone_preparation_failure_fails_the_attempt_without_a_review(self):
        """클론을 받거나 최신화하지 못하면 리뷰하지 않고 그 시도를 실패로 적는다."""
        error = subprocess.CalledProcessError(128, ['git', 'fetch'], stderr='fatal: unable to access')
        self.patch('git', mock.Mock(side_effect=error))

        self.run_bot()

        entry = self.entry()
        self.run_claude.assert_not_called()
        self.assertEqual((entry['status'], entry['attempts']), ('failed', 1))
        self.assertIn('unable to access', entry['note'])

    def test_reviews_wait_while_every_account_is_at_the_weekly_limit(self):
        """두 계정을 새로 읽어 모두 주간 90% 이상이면 리뷰를 미루고 한도 대기를 적어 처음 한 번만 알린다."""
        self.weekly = [{'percent': 90}, {'percent': 97}]

        self.run_bot()
        self.run_bot()

        quota = self.state()['quota']
        self.run_claude.assert_not_called()
        self.assertEqual((quota['kind'], quota['since'], quota['notified']), ('full', '2026-11-26T00:00:00Z', True))
        self.notify.assert_called_once()
        self.assertNotIn(f'{REPO}#7', self.state()['prs'])

    def test_fresh_readings_decide_whether_a_review_may_start(self):
        """새로 읽은 계정 하나라도 여유가 있으면 리뷰하고, 여유를 확인하지 못하면 한도 확인 안 됨으로 미룬다."""
        cases = {
            '89%인 계정이 있으면 리뷰': ([{'percent': 89}, {'percent': 100}], None),
            '초기화 시각이 지난 주간 창은 여유': ([{'percent': 95, 'resets_in': -1}, {'percent': 100}], None),
            '한 계정만 읽혀도 90% 아래면 리뷰': ([{'percent': 50}, {'percent': 100, 'stale': True}], None),
            'stale 계정은 못 읽은 것': ([{'percent': 95}, {'percent': 50, 'stale': True}], 'unknown'),
            '요청보다 오래된 기록은 못 읽은 것': ([{'percent': 95}, {'percent': 50, 'age': 60}], 'unknown'),
            '계정 기록이 하나뿐': ([{'percent': 95}], 'unknown'),
        }
        for name, (weekly, kind) in cases.items():
            with self.subTest(name), mock.patch.object(self, 'weekly', weekly):
                self.run_claude.reset_mock()
                for leftover in (self.state_dir / 'state.json', self.switcher / 'runtime.json'):
                    leftover.unlink(missing_ok=True)

                self.run_bot()

                self.assertEqual(self.run_claude.called, kind is None)
                self.assertEqual((self.state()['quota'] or {}).get('kind'), kind)

    def test_reading_from_the_last_twenty_seconds_is_used_without_a_new_request(self):
        """전환기가 20초 안에 읽은 값이 있으면 읽기 요청 파일을 쓰지 않고 그 값으로 판단한다."""
        self.switcher_answers = False
        self.answer_switcher(age=5)

        self.run_bot()

        self.assertFalse((self.switcher / 'usage_request.json').exists())
        self.run_claude.assert_called_once()

    def test_switcher_that_does_not_answer_in_twenty_seconds_defers_the_review(self):
        """전환기가 20초 안에 답하지 않으면 리뷰를 미루고, 1시간 넘게 이어질 때 한 번만 알린다."""
        self.switcher_answers = False

        self.run_bot()
        self.now += datetime.timedelta(minutes=50)
        self.run_bot()
        notified_within_an_hour = self.notify.call_count
        self.now += datetime.timedelta(minutes=20)
        self.run_bot()
        self.run_bot()

        quota = self.state()['quota']
        self.run_claude.assert_not_called()
        self.assertEqual(notified_within_an_hour, 0)
        self.notify.assert_called_once()
        self.assertEqual((quota['kind'], quota['since']), ('unknown', '2026-11-26T00:00:20Z'))

    def test_halted_switcher_is_not_asked_and_defers_the_review(self):
        """계정 전환기가 멈춰 있으면(halt.json) 읽기를 요청하지 않고 리뷰를 미룬다."""
        (self.switcher / 'halt.json').write_text(json.dumps({'reason': 'keychain'}))

        self.run_bot()

        self.assertFalse((self.switcher / 'usage_request.json').exists())
        self.run_claude.assert_not_called()
        self.assertEqual(self.state()['quota']['kind'], 'unknown')

    def test_quota_kind_change_restarts_the_wait(self):
        """미루는 이유가 바뀌면(한도 대기에서 확인 안 됨으로) 그 시각부터 다시 센다."""
        self.weekly = [{'percent': 95}, {'percent': 99}]
        self.run_bot()
        self.now += datetime.timedelta(hours=2)
        self.switcher_answers = False

        self.run_bot()

        quota = self.state()['quota']
        self.assertEqual((quota['kind'], quota['since'], quota['notified']), ('unknown', '2026-11-26T02:00:20Z', False))

    def test_run_with_nothing_to_review_clears_the_wait(self):
        """미룰 리뷰가 없는 실행은 한도 기록을 지운다."""
        self.weekly = [{'percent': 95}, {'percent': 99}]
        self.run_bot()
        self.requests = {}

        self.run_bot()

        self.assertIsNone(self.state()['quota'])

    def test_manual_review_and_posting_again_do_not_ask_the_switcher(self):
        """손수 리뷰와 게시만 다시 하는 실행은 모델 한도를 쓰지 않거나 사람이 부른 것이라 읽기를 요청하지 않는다."""
        self.send_failures = [Crash()]
        with self.assertRaises(Crash):
            self.run_bot(auto=True)
        (self.switcher / 'runtime.json').unlink()
        self.switcher_answers = False

        self.run_bot(auto=True)
        self.bot('review', '--repo', REPO, '7')

        self.assertFalse((self.switcher / 'usage_request.json').exists())
        self.assertEqual(self.entry()['mode'], 'draft')
        self.assertEqual(self.run_claude.call_count, 2)

    def test_running_record_lives_while_reviewing_and_codex_is_cleaned_after_every_run(self):
        """리뷰 중에는 running이 있고 끝나면 지워지며, 성공과 실패와 시간 초과 모두 끝에 Codex를 정리한다."""
        results = [review_bot.ClaudeRun(None, '', ()), review_bot.ClaudeRun(1, '', ())]
        self.run_claude.side_effect = lambda *args: (self.running_during_review.append(self.state()['running'])
                                                     or results.pop(0))

        self.run_bot()
        self.run_bot()

        worktree = str(self.clone / '.claude/worktrees/review-7')
        self.assertEqual([running['worktree'] for running in self.running_during_review], [worktree, worktree])
        self.assertIsNone(self.state()['running'])
        self.assertEqual([call.args[0] for call in self.end_codex.call_args_list], [Path(worktree), Path(worktree)])

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
        self.requests = {}

        self.run_bot(auto=True)

        entry = self.entry()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual((entry['status'], entry['reviewUrl']), ('posted', REVIEW_URL))
        self.assertEqual(self.url_log.read_text(), REVIEW_URL + '\n')
        self.assertIsNone(self.state()['running'])
        self.assertEqual(self.end_codex.call_count, 2)

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
        self.requests[7]['requested_at'] = REQUESTED_AGAIN_AT

        self.run_bot(auto=True)
        self.run_bot(auto=True)

        self.assertEqual(self.run_claude.call_count, 1)
        self.notify.assert_called_once()
        self.assertEqual(self.entry()['status'], 'skipped')

    def test_failed_review_is_retried_up_to_the_limit_and_again_on_a_new_request(self):
        """실패한 리뷰는 같은 요청에서 정한 횟수까지만 다시 하고, 다시 요청이 오면 처음부터 다시 한다."""
        self.writes_draft = False

        for _ in range(review_bot.MAX_ATTEMPTS + 1):
            self.run_bot()
        calls_on_first_request = self.run_claude.call_count
        self.requests[7]['requested_at'] = REQUESTED_AGAIN_AT
        self.run_bot()

        entry = self.entry()
        self.assertEqual(calls_on_first_request, review_bot.MAX_ATTEMPTS)
        self.assertEqual(self.run_claude.call_count, review_bot.MAX_ATTEMPTS + 1)
        self.assertEqual((entry['request'], entry['status'], entry['attempts']), (REQUESTED_AGAIN_AT, 'failed', 1))

    def test_requests_from_other_people_are_neither_reviewed_nor_recorded(self):
        """Bob, Alice가 아닌 사람이 보낸 요청은 리뷰하지 않고 기록도 남기지 않는다."""
        self.requests[7]['requester'] = 'someone'

        self.run_bot()

        self.run_claude.assert_not_called()
        self.assertEqual(self.state()['prs'], {})

    def test_new_commit_on_the_same_request_only_updates_the_head(self):
        """같은 요청에 새 커밋만 오면 다시 리뷰하지 않고 head만 갱신해, 초안이 옛 커밋을 보았다는 것을 남긴다."""
        self.run_bot()
        self.pulls[7]['headRefOid'] = NEW_HEAD

        self.run_bot()

        entry = self.entry()
        self.assertEqual(self.run_claude.call_count, 1)
        self.assertEqual((entry['status'], entry['sha'], entry['head']), ('draft', HEAD, NEW_HEAD))

    def test_request_sent_again_is_reviewed_again(self):
        """같은 PR에 새 시각의 요청이 오면 다시 리뷰한다."""
        self.run_bot()
        self.pulls[7]['headRefOid'] = NEW_HEAD
        self.requests[7]['requested_at'] = REQUESTED_AGAIN_AT

        self.run_bot()

        entry = self.entry()
        self.assertEqual(self.run_claude.call_count, 2)
        self.assertEqual((entry['request'], entry['sha']), (REQUESTED_AGAIN_AT, NEW_HEAD))

    def test_fork_pull_request_is_left_for_a_manual_review(self):
        """fork PR은 리뷰 worktree에 head를 받을 수 없어 리뷰하지 않고 손수 리뷰하라고 한 번 알린다."""
        self.requests[7]['fork'] = True

        self.run_bot()
        self.run_bot()

        self.run_claude.assert_not_called()
        self.assertEqual(self.entry()['status'], 'skipped')
        self.notify.assert_called_once()
        self.assertIn('fork', self.notify.call_args.args[0])

    def test_requests_on_every_search_page_are_handled(self):
        """검색 결과가 여러 페이지로 나뉘어도 모든 페이지의 요청을 처리한다."""
        self.pulls[8] = pull_request(8)
        self.requests[8] = {'requester': 'alice', 'requested_at': REQUESTED_AT}
        self.page_size = 1

        self.run_bot()

        self.assertEqual(self.run_claude.call_count, 2)
        self.assertEqual(sorted(self.state()['prs']), [f'{REPO}#7', f'{REPO}#8'])

    def test_failed_request_lookup_leaves_the_records_unchanged(self):
        """요청 조회가 실패하면(응답의 errors 포함) 그 실행은 기록을 바꾸거나 지우지 않는다."""
        self.run_bot()
        before = self.state()['prs']
        self.now = NOW + datetime.timedelta(days=30)
        self.fetch_pages.side_effect = subprocess.CalledProcessError(1, ['gh'], stderr='gh: Something went wrong')

        self.run_bot()

        self.assertEqual(self.state()['prs'], before)
        self.assertEqual(self.state()['poll_failures'], 1)

    def test_records_gone_from_the_request_list_for_seven_days_are_removed(self):
        """요청 목록에 없고 마지막 기록이 7일 지난 기록은 지우고, 7일이 안 된 기록은 둔다."""
        self.run_bot()
        self.now = NOW + datetime.timedelta(days=3)
        self.pulls[8] = pull_request(8)
        self.requests = {8: {'requester': 'alice', 'requested_at': REQUESTED_AT}}
        self.run_bot()
        self.requests = {}
        self.now = NOW + datetime.timedelta(days=8)

        self.run_bot()

        self.assertEqual(list(self.state()['prs']), [f'{REPO}#8'])

    def test_first_install_skips_waiting_requests_and_reinstall_keeps_records(self):
        """처음 설치할 때 기다리던 요청은 리뷰하지 않고, 다시 설치하면 그사이 온 요청도 그대로 리뷰한다."""
        self.bot('install', '--requester', 'bob')
        self.run_bot()
        self.pulls[8] = pull_request(8)
        self.requests[8] = {'requester': 'bob', 'requested_at': REQUESTED_AGAIN_AT}
        self.bot('install', '--requester', 'bob')

        self.run_bot()

        self.assertEqual(self.entry(7)['status'], 'skipped')
        self.assertEqual(self.entry(8)['status'], 'draft')
        self.assertEqual(self.run_claude.call_count, 1)
        self.assertEqual(self.register.call_count, 2)

    def test_records_from_the_old_commit_based_bot_are_removed(self):
        """요청 시각이 없는 옛 꼴 기록은 지운다."""
        self.state_dir.mkdir(parents=True)
        old = {'prs': {f'{REPO}#1': {'sha': HEAD, 'status': 'skipped', 'attempts': 0, 'note': '설치 전부터 대기',
                                     'at': '2026-11-24T11:47:00'}}, 'poll_failures': 0}
        (self.state_dir / 'state.json').write_text(json.dumps(old))

        self.run_bot()

        self.assertNotIn(f'{REPO}#1', self.state()['prs'])

    def test_manual_review_settles_the_waiting_request(self):
        """손수 리뷰한 PR은 그때 기다리던 요청 시각을 적어, 다음 실행이 같은 요청을 다시 리뷰하지 않는다."""
        self.bot('review', '--repo', REPO, '7')

        self.run_bot()

        self.assertEqual(self.run_claude.call_count, 1)
        self.assertEqual(self.entry()['request'], REQUESTED_AT)

    def test_run_reviews_nothing_while_another_run_holds_the_lock(self):
        """다른 실행이 잠금을 잡고 있으면 리뷰하지 않고 끝난다."""
        self.state_dir.mkdir(parents=True)

        with (self.state_dir / 'lock').open('w') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.run_bot()

        self.run_claude.assert_not_called()

    def test_notifies_once_when_github_lookups_keep_failing(self):
        """GitHub 조회가 연속으로 실패하면 정한 횟수째에 한 번만 알린다."""
        self.fetch_pages.side_effect = subprocess.CalledProcessError(1, ['gh'], stderr='HTTP 401: Bad credentials')

        for _ in range(review_bot.POLL_FAILURES_TO_NOTIFY + 1):
            self.run_bot()

        self.notify.assert_called_once()


if __name__ == '__main__':
    unittest.main()
