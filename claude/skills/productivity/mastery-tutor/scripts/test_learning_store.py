import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from learning_store import Store, StoreError


class LearningStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root, holder='claude:tab-1')
        self.session = {
            'id': 'session-a', 'revision': 0, 'topic': '비율과 클릭률', 'status': 'active',
            'summary_markdown': '# 비율\n분자와 분모의 집합을 맞춘다.\n',
            'state': {
                'current_block': 'ratios', 'phase': 'subjective',
                'pending_batch': {'id': 'b2', 'items': [
                    {'id': 'q11', 'prompt': '클릭률 식을 쓰세요.', 'rubric': ['분자: 클릭', '분모: 노출'],
                     'answer': '클릭 수 / 노출 수 × 100', 'status': 'answer_saved', 'helped': False},
                    {'id': 'q12', 'prompt': '기간이 다르면?', 'rubric': ['같은 기간 필요'],
                     'answer': None, 'status': 'pending', 'helped': False},
                ]},
                'graded_attempts': [{'id': 'q10', 'result': 'correct'}],
                'progress_display': {'mode': 'every-n', 'n': 5, 'remainder': 2},
                'review_queue': [{'concept': 'ratio', 'status': 'open'}],
            },
        }

    def test_pause_resume_preserves_answers_rubrics_and_counters(self):
        saved = self.store.write('sessions', self.session)
        saved['status'] = 'paused'
        paused = self.store.write('sessions', saved)
        restored = self.store.resume()
        self.assertEqual(restored, paused)
        self.assertEqual(restored['state'], self.session['state'])
        self.assertEqual(restored['revision'], 2)
        self.assertEqual((self.root / 'sessions/session-a/notes.md').read_text(), self.session['summary_markdown'])

    def test_stale_writer_cannot_overwrite_newer_answers(self):
        first = self.store.write('sessions', self.session)
        second_writer = Store(self.root, holder='claude:tab-1')
        updated = copy.deepcopy(first)
        updated['state']['pending_batch']['items'][1]['answer'] = '同じ期間が必要'
        latest = self.store.write('sessions', updated)
        with self.assertRaisesRegex(StoreError, 'Revision conflict'):
                second_writer.write('sessions', first)
        self.assertEqual(self.store.read('sessions', 'session-a'), latest)

    def test_recovers_valid_history_after_damaged_or_missing_current_checkpoint(self):
        first = self.store.write('sessions', self.session)
        latest = self.store.write('sessions', first)
        directory = self.root / 'sessions/session-a'
        (directory / 'state.json').write_text('{incomplete')
        (directory / 'history/99999999.json').write_text('{incomplete')
        self.assertEqual(self.store.resume(), latest)
        (directory / 'state.json').unlink()
        self.assertEqual(self.store.resume(), latest)

    def test_interrupted_save_can_resume_from_committed_history(self):
        atomic_json = self.store.atomic_json

        def interrupted(path, payload):
            if path.name == 'state.json':
                raise OSError('simulated interruption')
            atomic_json(path, payload)

        with patch.object(self.store, 'atomic_json', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'simulated interruption'):
                self.store.write('sessions', self.session)
        recovered = self.store.resume()
        self.assertEqual(recovered['revision'], 1)
        self.assertEqual(recovered['state'], self.session['state'])

    def test_default_resume_uses_latest_unfinished_session(self):
        self.store.write('sessions', self.session)
        other = copy.deepcopy(self.session)
        other.update(id='session-b', status='paused')
        second = self.store.write('sessions', other)
        self.assertEqual(self.store.resume()['id'], 'session-b')
        second['status'] = 'complete'
        self.store.write('sessions', second)
        self.assertEqual(self.store.resume()['id'], 'session-a')

    def test_concept_notes_and_alias_search_preserve_error_history(self):
        concept = {'id': 'ratio', 'title': '비율', 'aliases': ['분자', '백분율'],
                   'summary_markdown': '# 비율\n대상 / 전체\n',
                   'weaknesses': [{'id': 'denominator', 'status': 'verified', 'recurrences': 2}]}
        first = self.store.write('concepts', concept)
        first['summary_markdown'] += '같은 기간과 집합을 사용한다.\n'
        saved = self.store.write('concepts', first)
        self.assertEqual(self.store.records('concepts', '백분율'), [saved])
        self.assertEqual(saved['weaknesses'], concept['weaknesses'])
        self.assertEqual((self.root / 'concepts/ratio.md').read_text(), saved['summary_markdown'])

    def test_init_is_idempotent_and_invalid_ids_are_rejected(self):
        saved = self.store.write('sessions', self.session)
        self.store.init()
        self.store.init()
        self.assertEqual(self.store.resume(), saved)
        with self.assertRaises(StoreError):
            self.store.read('concepts', '../escape')

    def test_session_without_state_is_rejected(self):
        del self.session['state']
        with self.assertRaisesRegex(StoreError, 'full state'):
            self.store.write('sessions', self.session)

    def test_read_only_lookup_does_not_create_a_store(self):
        missing = self.root / 'missing'
        self.assertIsNone(Store(missing).resume())
        self.assertEqual(Store(missing).records('concepts', '비율'), [])
        self.assertFalse(missing.exists())

    def test_cli_can_restore_an_answer_in_a_fresh_process(self):
        script = Path(__file__).with_name('learning_store.py')
        fixture = self.root / 'input.json'
        fixture.write_text(json.dumps(self.session, ensure_ascii=False))
        prefix = [sys.executable, '-B', str(script), '--root', str(self.root)]
        saved = subprocess.run(prefix + ['write', 'sessions', '--file', str(fixture)],
                               check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(saved.stdout)['revision'], 1)
        restored = subprocess.run(prefix + ['resume'], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(restored.stdout)['state'], self.session['state'])

    def test_rejects_session_write_from_another_conversation_while_active(self):
        """holder가 다른 대화인 active 회차는 최신 revision으로 저장해도 거부되고 저장된 기록이 그대로 남는다."""
        # given
        first = self.store.write('sessions', self.session)
        # when & then
        with self.assertRaisesRegex(StoreError, 'active in another conversation'):
            Store(self.root, holder='codex:tab-2').write('sessions', first)
        self.assertEqual(self.store.read('sessions', 'session-a'), first)

    def test_take_over_moves_active_session_to_this_conversation(self):
        """사용자가 옮기기로 한 active 회차는 take_over 저장으로 holder가 이 대화로 바뀐다."""
        # given
        first = self.store.write('sessions', self.session)
        # when
        Store(self.root, holder='codex:tab-2').write('sessions', first, take_over=True)
        # then
        self.assertEqual(self.store.read('sessions', 'session-a')['holder'], 'codex:tab-2')

    def test_paused_session_can_be_saved_by_another_conversation(self):
        """paused 회차는 holder가 다른 대화여도 take_over 없이 active로 이어서 저장된다."""
        # given
        self.session['status'] = 'paused'
        paused = self.store.write('sessions', self.session)
        paused['status'] = 'active'
        # when
        Store(self.root, holder='codex:tab-2').write('sessions', paused)
        # then
        self.assertEqual(self.store.read('sessions', 'session-a')['holder'], 'codex:tab-2')

    def test_default_resume_prefers_session_this_conversation_holds(self):
        """holder가 이 대화인 회차가 있으면 다른 대화가 더 나중에 저장한 회차 대신 그 회차를 이어 간다."""
        # given
        self.store.write('sessions', self.session)
        other = copy.deepcopy(self.session)
        other['id'] = 'session-b'
        Store(self.root, holder='codex:tab-2').write('sessions', other)
        # when
        resumed = self.store.resume()
        # then
        self.assertEqual(resumed['id'], 'session-a')

    def test_default_resume_fails_when_several_sessions_are_unfinished_and_none_is_held_here(self):
        """holder가 이 대화인 회차가 없고 미완료 회차가 여럿이면 가장 최근 회차를 고르지 않고 --id를 요구하며 실패한다."""
        # given
        self.store.write('sessions', self.session)
        other = copy.deepcopy(self.session)
        other.update(id='session-b', status='paused')
        Store(self.root, holder='codex:tab-2').write('sessions', other)
        # when & then
        with self.assertRaisesRegex(StoreError, '2 unfinished sessions'):
            Store(self.root, holder='claude:tab-3').resume()

    def test_codex_thread_is_the_holder_when_codex_runs_inside_a_claude_session(self):
        """Claude 세션 안에서 띄운 Codex가 저장하면 Claude 세션이 아니라 Codex 대화를 holder로 남긴다."""
        # given
        environment = {'CLAUDE_CODE_SESSION_ID': 'tab-1', 'CODEX_THREAD_ID': 'tab-2'}
        # when
        with patch.dict(os.environ, environment):
            saved = Store(self.root).write('sessions', self.session)
        # then
        self.assertEqual(saved['holder'], 'codex:tab-2')

    def test_cli_take_over_records_the_calling_conversation(self):
        """CLI의 --take-over 저장은 실행한 대화의 환경 변수로 holder를 남긴다."""
        # given
        first = self.store.write('sessions', self.session)
        fixture = self.root / 'input.json'
        fixture.write_text(json.dumps(first, ensure_ascii=False))
        # when
        self.run_cli('write', 'sessions', '--take-over', '--file', str(fixture), claude_session='tab-2')
        # then
        self.assertEqual(self.store.read('sessions', 'session-a')['holder'], 'claude:tab-2')

    def test_cli_list_marks_session_active_in_another_conversation(self):
        """holder가 다른 대화인 active 회차는 회차 목록에서 active_elsewhere가 true다."""
        # given
        self.store.write('sessions', self.session)
        # when
        listed = self.run_cli('list', 'sessions', claude_session='tab-2')
        # then
        self.assertTrue(json.loads(listed.stdout)[0]['active_elsewhere'])

    def run_cli(self, *arguments, claude_session):
        environment = {**os.environ, 'CLAUDE_CODE_SESSION_ID': claude_session}
        environment.pop('CODEX_THREAD_ID', None)
        script = Path(__file__).with_name('learning_store.py')
        return subprocess.run([sys.executable, '-B', str(script), '--root', str(self.root), *arguments],
                              check=True, capture_output=True, text=True, env=environment)


if __name__ == '__main__':
    unittest.main()
