import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location('refresh', Path(__file__).with_name('refresh.py'))
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)


def node(oid, at, *parents):
    return {'commit': {'oid': oid, 'committedDate': at, 'messageHeadline': oid,
                       'parents': {'nodes': [{'oid': parent} for parent in parents]}}}


def account(login, kind='User'):
    return {'login': login, '__typename': kind}


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_case_keeps_reviews_and_answers_on_the_branch_own_commits(self):
        pr = {
            'number': 7, 'title': 't', 'url': 'u', 'mergedAt': '2026-10-09T00:00:00Z', 'baseRefName': 'master',
            'headRefName': 'me/fix', 'headRefOid': 'd4', 'author': {'login': 'me'},
            'commits': {'nodes': [node('a1', '2026-10-01T00:00:00Z', 'z0'), node('b2', '2026-10-02T00:00:00Z', 'a1'),
                                  node('x9', '2026-10-03T00:00:00Z', 'z0'), node('m3', '2026-10-04T00:00:00Z', 'b2', 'x9'),
                                  node('d4', '2026-10-05T00:00:00Z', 'm3')]},
            'reviews': {'nodes': [{'author': account('coderabbitai', 'Bot'), 'url': 'u#r1', 'body': 'r', 'submittedAt': '2026-10-02T12:00:00Z',
                                   'commit': {'oid': 'b2'}, 'comments': {'nodes': [
                                       {'path': 'a.py', 'line': None, 'originalLine': 3, 'body': '합계가 음수가 된다'}]}},
                                  {'author': account('me'), 'url': 'u#r2', 'body': '셀프 리뷰했습니다.', 'submittedAt': '2026-10-04T13:00:00Z',
                                   'commit': {'oid': 'm3'}, 'comments': {'nodes': []}},
                                  {'author': account('me'), 'url': 'u#r3', 'body': '메모', 'submittedAt': '2026-10-04T14:00:00Z',
                                   'commit': {'oid': 'd4'}, 'comments': {'nodes': []}}]},
            'comments': {'nodes': [{'author': account('linear', 'Bot'), 'body': 'linked', 'createdAt': '2026-10-01T01:00:00Z'},
                                   {'author': account('helper'), 'body': '## Team Bot\n- 이름', 'createdAt': '2026-10-01T02:00:00Z'},
                                   {'author': account('me'), 'body': '답글', 'createdAt': '2026-10-03T00:00:00Z'}]},
            'timelineItems': {'nodes': [{'createdAt': '2026-10-04T12:00:00Z'}]},
        }
        log = [{'group': 'mine', 'source': 'review-log', 'author': 'me', 'commit': 'a1',
                'at': refresh.to_utc('2026-10-01T05:00:00Z'), 'findings': [], 'body': ''},
               {'group': 'mine', 'source': 'review-log', 'author': 'me', 'commit': 'other-repo',
                'at': refresh.to_utc('2026-10-01T06:00:00Z'), 'findings': [], 'body': ''}]
        case = refresh.build_case('acme/shop', pr, 'me', {'helper': 'Team Bot'}, {'u#r2'}, None, log, {'m3': '++ 충돌 해결'})
        self.assertEqual([(r['group'], r['author']) for r in case['reviews']],
                         [('bot', 'helper'), ('mine', 'me'), ('bot', 'coderabbitai'), ('mine', 'me')])
        self.assertEqual(case['skipped_bot_comments'], 1)
        self.assertEqual(case['post_commits'], {'0': ['b2', 'm3', 'd4'], '1': ['b2', 'm3', 'd4'], '2': ['m3', 'd4'], '3': ['d4']})
        self.assertEqual(case['miss_commits'], {'0': ['b2', 'm3'], '1': ['b2', 'm3'], '2': ['m3'], '3': ['d4']})
        self.assertEqual((case['first_external_commit'], case['unresolved_merges']), ('a1', []))
        self.assertEqual(case['reviews'][2]['findings'][0]['line'], 3)
        pr['comments']['nodes'] = pr['comments']['nodes'][:1]
        pr['reviews']['nodes'][0]['commit'] = {'oid': 'f0rce'}
        rewritten = refresh.build_case('acme/shop', pr, 'me', {}, set(), None, [], {})
        self.assertEqual((rewritten['first_external_commit'], rewritten['unresolved_merges']), ('f0rce', ['m3']))

    def test_merge_keeps_only_hand_resolved_lines(self):
        combined = '\n'.join(['diff --cc a.py', 'index 1,2..3', '--- a/a.py', '+++ b/a.py', '@@@ -1,2 -1,2 +1,2 @@@',
                               '  same', '+ from base', ' +from branch', '++hand fix', '--hand removal',
                               '@@@ -9,1 -9,1 +9,1 @@@', '+ only base', 'diff --cc b.py', '@@@ -1 -1 +1 @@@', ' +branch'])
        self.assertEqual(refresh.hand_resolved(combined).split('\n'),
                         ['diff --cc a.py', '@@@ -1,2 -1,2 +1,2 @@@', '++hand fix', '--hand removal'])
        self.assertEqual(refresh.hand_resolved('diff --cc a.py\n@@@ -1 -1 +1 @@@\n+ from base\n +from branch'), '')

    def test_tally_sums_groups_only_where_they_reviewed(self):
        judged = [
            {'groups': {'mine': {'caught': 2, 'missed': 1, 'false_positive': 0}, 'bot': {'caught': 0, 'missed': 3, 'false_positive': 2}},
             'my_misses': [{'class': '탐지 공백'}], 'my_caught': [{'criterion': 'code.md:2. 정확성'}, {'criterion': 'code.md:2. 정확성'}]},
            {'groups': {'bot': {'caught': 1, 'missed': 0, 'false_positive': 1}, 'human': {}}, 'my_misses': [], 'my_caught': []},
        ]
        self.assertEqual(refresh.tally_judged(judged).split('\n'), [
            'PR 2개', '| 묶음 | 리뷰한 PR | 잡은 것 | 놓친 것 | 헛짚은 것 |', '|---|---|---|---|---|',
            '| 내 리뷰 | 1 | 2 | 1 | 0 |', '| 리뷰봇 | 2 | 1 | 3 | 3 |', '| 사람 리뷰 | 0 | 0 | 0 | 0 |',
            '내가 놓친 것: 맥락 밖 0 · 찾고 버림 0 · 지식 공백 0 · 탐지 공백 1', '잡은 리뷰 기준: code.md:2. 정확성 2'])

    def test_reviews_split_into_mine_bot_and_human(self):
        markers = {'helper-account': 'Bot Review'}
        cases = [
            (account('coderabbitai', 'Bot'), 'summary', False, 'bot'),
            (account('helper-account'), 'Bot Review result', False, 'bot'),
            (account('helper-account'), 'looks good', False, 'human'),
            (account('writer'), 'self note', False, None),
            (account('writer'), '셀프 리뷰했습니다.', True, 'mine'),
            (account('me'), 'LGTM!', True, 'mine'),
            (account('me'), 'LGTM!', False, 'human'),
        ]
        for who, body, ai_review, group in cases:
            self.assertEqual(refresh.classify(who, body, 'writer', markers, ai_review), group, (who, ai_review))

    def test_my_review_records_are_read_from_logs_html_and_bot_table(self):
        self.write('plans/topic/notes/review-log.md', '\n'.join([
            '# 리뷰 기록', '', '## 2026-10-20 me/fix-total 전체 1111111..2222222', '끝 커밋: 3333333',
            '- AUTO-FIXED · app/total.py:12 · 합계가 음수일 때 0으로 바꿨다',
            '- 남김 · app/view.py:3 · 기존 꼴과 같다', '', '## 2026-10-21 다른 문서 검증', '- 남김 · x · y', '']))
        logs = refresh.read_review_logs(self.root / 'plans')
        self.assertEqual([(e['commit'], len(e['findings'])) for e in logs['me/fix-total']], [('2222222', 2)])
        self.assertEqual(logs['me/fix-total'][0]['findings'][0]['path'], 'app/total.py:12')
        self.write('pr_reviews/shop/pr-7/review.html', '<div class="eyebrow">PR 리뷰 리포트 · acme/shop</div>'
                   '<span class="pill">head <span class="mono">abcdef12</span></span>'
                   '<div class="issue issue--critical"><span class="loc mono">app/pay.py:9</span>'
                   '<div class="desc"><b>환불 합계가 <code>paid</code>를 넘는다.</b></div></div>')
        self.write('pr_reviews/shop/8/review.html', '<div class="eyebrow">PR 리뷰 리포트 · shop</div><section>'
                   '<div class="issue issue--info"><div class="top"><b>발견 1</b><span class="loc mono">app/a.py:1</span></div>'
                   '<div class="desc" style="margin:0">굵은 글씨 없는 설명</div></div>'
                   '<div class="issue issue--info"><span class="loc mono">app/b.py:2</span><div class="desc"><b>이름이 다르다</b></div></div>'
                   '</section><p><b>다른 절의 굵은 글씨</b></p>')
        self.write('pr_reviews/shop/9/review.html', '<div class="eyebrow">PR 리뷰 리포트 · acme/shop</div>'
                   '<footer>대상 커밋 <code>fe62d8e4</code></footer>')
        html_reviews = refresh.read_review_html(self.root / 'pr_reviews', {'shop': 'acme'})
        review = html_reviews[('acme/shop', 7)]
        self.assertEqual((review['commit'], review['findings']),
                         ('abcdef12', [{'severity': 'CRITICAL', 'path': 'app/pay.py:9', 'text': '환불 합계가 paid를 넘는다.'}]))
        self.assertEqual((html_reviews[('acme/shop', 8)]['commit'], [f['text'] for f in html_reviews[('acme/shop', 8)]['findings']]),
                         (None, ['굵은 글씨 없는 설명', '이름이 다르다']))
        self.assertEqual(html_reviews[('acme/shop', 9)]['commit'], 'fe62d8e4')
        self.write('pr_reviews/shop/10/review.html', '<div class="eyebrow">PR 리뷰 리포트 · acme/shop</div>'
                   '<p>다른 저장소 origin/HEAD 3f6d4aa3 기준</p><footer>2026-10-06 15:13 KST · head 8e1b902 · 외부 저장</footer>')
        self.assertEqual(refresh.read_review_html(self.root / 'pr_reviews', {})[('acme/shop', 10)]['commit'], '8e1b902')
        bots = self.write('bots.md', '## 봇\n\n## 봇 리뷰 판별\n\n| 계정 | 본문 표식 |\n|---|---|\n'
                          '| `one`, `two` | `Team Bot` |\n| `three` | `three-review` |\n\n## 다음\n| `x` | `y` |\n')
        self.assertEqual(refresh.read_bot_markers(bots),
                         {'one': 'Team Bot', 'two': 'Team Bot', 'three': 'three-review'})

    def test_metrics_count_rule_text_and_skip_secrets(self):
        repeated = '- 같은 규칙 문장이 두 파일에 그대로 있다.'
        self.write('claude/CLAUDE.md', f'# 제목\n\n{repeated}\n```\n- 코드 안 줄\n```\n')
        self.write('claude/lib/a.md', f'---\nname: a\n---\n## 절\n\n{repeated}\n| 칸 | 칸 |\n|---|---|\n| 값 | 값 |\n')
        self.write('claude/lib/run.sh', 'echo one\necho two\n')
        self.write('claude/lib/github_token.md', '- 비밀 값\n')
        self.write('private/claude/lib/tool/.env', 'TOKEN=secret\n')
        (self.root / 'codex').mkdir()
        (self.root / 'codex/AGENTS.md').symlink_to('../claude/CLAUDE.md')
        result = refresh.measure_rules(self.root)
        self.assertEqual({k: result['rules'][k] for k in ('files', 'sections', 'rules', 'duplicates')},
                         {'files': 2, 'sections': 2, 'rules': 4, 'duplicates': 1})
        self.assertEqual(result['code'], {'files': 1, 'lines': 2})

    def test_replay_check_reports_pinned_head_and_outside_reads_from_unterminated_and_cut_off_transcripts(self):
        source = self.root / 'source'
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        for name in ('one', 'two'):
            (source / name).write_text(name)
            subprocess.run(['git', '-C', str(source), 'add', name], check=True)
            subprocess.run(['git', '-C', str(source), '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', name],
                           check=True)
        head = refresh.git(source, 'rev-parse', 'HEAD~1').strip()
        out = self.root / 'plans/run'
        isolated = out / 'source'
        subprocess.run(['git', 'init', '-q', str(isolated)], check=True)
        refresh.git(isolated, 'fetch', '--quiet', '--no-tags', str(source), head)
        refresh.git(isolated, 'checkout', '--quiet', '--detach', head)
        home_plans = str(refresh.HOME / 'plans/topic/notes/review-log.md')
        events = [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 't1', 'name': 'Read', 'input': {'file_path': f'{refresh.HOME}/plans/run/source-7.diff'}},
                {'type': 'tool_use', 'id': 't2', 'name': 'Read', 'input': {'file_path': home_plans}},
                {'type': 'tool_use', 'id': 't3', 'name': 'Grep', 'input': {'pattern': 'x', 'path': '~/pr_reviews'}}]}},
            {'type': 'result', 'permission_denials': [
                {'tool_use_id': 't2', 'tool_name': 'Read', 'tool_input': {'file_path': home_plans}},
                {'tool_use_id': 's9', 'tool_name': 'WebFetch', 'tool_input': {'url': 'https://api.github.com/x'}}]},
        ]
        lines = '\n'.join(json.dumps(e) for e in events)
        transcript = self.write('transcript.jsonl', lines)
        check = refresh.check_replay(transcript, refresh.HOME / 'plans/run', isolated, head, source)
        self.assertEqual((check['head_pinned'], check['refs'], check['commits_outside_head'], check['clone_history_matches']),
                         (True, [], 0, True))
        self.assertEqual(sorted((a['tool'], a['blocked']) for a in check['forbidden_attempts']),
                         [('Grep', False), ('Read', True), ('WebFetch', True)])
        self.assertEqual(check['forbidden_succeeded'], 1)
        transcript.write_bytes((lines + '\n{"type": "assistant", "message": {"content": [{"text": "한').encode()[:-1])
        self.assertEqual(refresh.check_replay(transcript, refresh.HOME / 'plans/run', isolated, head, source), check)

    def test_headless_run_passes_the_wait_setting_and_stops_claude_at_the_time_limit(self):
        fake = self.write('claude', '#!/bin/sh\necho "wait=$CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"\n'
                                    '[ "$2" = slow ] && exec sleep 30\nexit 7\n')
        fake.chmod(0o755)
        transcript = self.root / 'transcript.jsonl'
        with mock.patch.object(refresh, 'CLAUDE', fake):
            self.assertEqual(refresh.run_headless('fast', 'Read', ['Agent'], ['WebFetch'], self.root, transcript), 7)
            self.assertEqual(transcript.read_text(), 'wait=0\n')
            with mock.patch.object(refresh, 'HEADLESS_TIMEOUT_HOURS', 0.0003):
                self.assertIsNone(refresh.run_headless('slow', 'Read', ['Agent'], ['WebFetch'], self.root, transcript))

    def test_periodic_run_that_crashes_still_notifies_and_leaves_an_exit_code(self):
        denied = PermissionError(1, 'Operation not permitted', '개발 방법론.md')
        with mock.patch.object(refresh, 'NOTES', self.root), mock.patch.object(refresh, 'git', return_value='abc\n'), \
                mock.patch.object(refresh, 'protected_digest', side_effect=denied), \
                mock.patch.object(refresh, 'notify') as notify, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(refresh.run_periodic(), 1)
        title, message = notify.call_args.args
        self.assertEqual(title, '규칙 갱신 종료 코드 1')
        self.assertIn('PermissionError', message)
        run_dir, = (self.root / 'runs').iterdir()
        self.assertEqual((run_dir / 'exit-code').read_text(), '1\n')


if __name__ == '__main__':
    unittest.main()
