"""Undo is revision guarded and late model output cannot restore a cancelled answer."""

import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from learning_store import Store, StoreError
from study_jobs import Jobs
from test_study_app import checkpoint, model_result


class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name, holder='web:study')
        self.original = self.store.write('sessions', checkpoint())
        self.release = threading.Event()
        self.started = threading.Event()
        self.jobs = Jobs(self.temporary.name, runner=self.run_model)

    def tearDown(self):
        self.release.set()
        self.jobs.pool.shutdown(wait=True)
        self.temporary.cleanup()

    def run_model(self, record, request, directory, emit):
        self.started.set()
        self.release.wait(timeout=5)
        return model_result(record)

    def submit(self):
        self.jobs.submit({'request_id': 'answer-1', 'session_id': 'study-test', 'revision': 1,
                          'answers': {'q1': '  원래 보낸 답\n수정 필요  '}})
        self.assertTrue(self.started.wait(timeout=2))

    def cancel(self):
        record = self.store.read('sessions', 'study-test')
        return self.jobs.cancel({'job_id': 'answer-1', 'session_id': 'study-test',
                                 'revision': record['revision']})

    def test_running_cancel_restores_answer_and_blocks_late_results(self):
        self.submit()
        result = self.cancel()
        self.assertEqual(result['status'], 'cancelling')
        self.assertEqual(result['submitted_answers'][0]['answer'], '  원래 보낸 답\n수정 필요  ')
        saved = self.store.read('sessions', 'study-test')
        self.assertEqual(saved['state']['pending_batch']['items'][0]['status'], 'pending')
        self.assertIsNone(saved['state']['pending_batch']['items'][0]['answer'])
        self.assertEqual(saved['state']['grading_queue'], [])
        revision = saved['revision']
        self.release.set()
        self.jobs.pool.shutdown(wait=True)
        self.assertEqual(self.jobs.latest('study-test')['status'], 'cancelled')
        self.assertEqual(self.store.read('sessions', 'study-test')['revision'], revision)

    def test_completed_latest_cancel_restores_progress_and_keeps_audit(self):
        self.release.set()
        self.submit()
        self.jobs.pool.shutdown(wait=True)
        self.assertTrue(self.jobs.latest('study-test')['can_cancel'])
        result = self.cancel()
        self.assertEqual(result['status'], 'cancelled')
        saved = self.store.read('sessions', 'study-test')
        self.assertEqual(saved['state']['progress_display'], self.original['state']['progress_display'])
        self.assertIn('submission_cancellations', saved['state'])
        self.assertEqual(self.jobs.history('study-test')[0]['request']['answer_ids'], ['q1'])

    def test_general_message_can_be_cancelled_and_returns_its_original_text(self):
        self.release.set()
        self.jobs.submit({'request_id': 'answer-1', 'session_id': 'study-test', 'revision': 1,
                          'answers': {}, 'message': '일반 입력\n수정할 내용'})
        self.jobs.pool.shutdown(wait=True)
        self.assertTrue(self.jobs.latest('study-test')['can_cancel'])
        result = self.cancel()
        self.assertEqual(result['message'], '일반 입력\n수정할 내용')
        self.assertEqual(result['answer_ids'], [])
        self.assertNotIn('web_reply', self.store.read('sessions', 'study-test')['state'])

    def test_external_update_or_takeover_prevents_cancellation(self):
        self.submit()
        current = self.store.read('sessions', 'study-test')
        current['summary_markdown'] = '다른 곳의 변경'
        self.store.write('sessions', current)
        with self.assertRaises(StoreError):
            self.cancel()
        self.assertEqual(self.store.read('sessions', 'study-test')['summary_markdown'], '다른 곳의 변경')

    def test_legacy_completed_job_uses_history_and_recovers_its_answer(self):
        self.release.set()
        self.submit()
        self.jobs.pool.shutdown(wait=True)
        path = self.jobs.directory / 'answer-1/job.json'
        job = json.loads(path.read_text())
        job.pop('applied_revision')
        job['request'].pop('submitted_answers')
        self.store.atomic_json(path, job)
        result = self.cancel()
        self.assertEqual(result['submitted_answers'][0]['answer'], '  원래 보낸 답\n수정 필요  ')

    def test_queued_cancel_never_calls_the_model(self):
        blocker = threading.Event()
        self.jobs.pool.submit(blocker.wait, 2)
        self.jobs.submit({'request_id': 'answer-1', 'session_id': 'study-test', 'revision': 1,
                          'answers': {'q1': '취소할 답'}})
        self.assertEqual(self.cancel()['status'], 'cancelled')
        blocker.set()
        self.jobs.pool.shutdown(wait=True)
        self.assertFalse(self.started.is_set())

    def test_retry_after_other_changes_cannot_revert_that_work(self):
        def fail(record, request, directory, emit):
            raise StoreError('permanent failure')
        self.jobs.runner = fail
        self.jobs.submit({'request_id': 'answer-1', 'session_id': 'study-test', 'revision': 1,
                          'answers': {'q1': '원래 답'}})
        self.jobs.pool.shutdown(wait=True)
        record = self.store.read('sessions', 'study-test')
        record['summary_markdown'] = '보존해야 하는 후속 학습'
        record = self.store.write('sessions', record)
        self.jobs = Jobs(self.temporary.name, runner=lambda r, q, d, e: model_result(r))
        self.jobs.submit({'request_id': 'retry-2', 'session_id': 'study-test',
                          'revision': record['revision'], 'answers': {}, 'retry_job_id': 'answer-1'})
        self.jobs.pool.shutdown(wait=True)
        latest = self.jobs.latest('study-test')
        self.assertFalse(latest['can_cancel'])
        current = self.store.read('sessions', 'study-test')
        with self.assertRaises(StoreError):
            self.jobs.cancel({'session_id': 'study-test', 'job_id': 'retry-2',
                              'revision': current['revision']})
        self.assertEqual(self.store.read('sessions', 'study-test')['summary_markdown'], '보존해야 하는 후속 학습')

    def test_contiguous_retry_can_be_cancelled_and_its_failed_ancestor_cannot_run_again(self):
        def fail(record, request, directory, emit):
            raise StoreError('permanent failure')
        self.jobs.runner = fail
        self.jobs.submit({'request_id': 'answer-1', 'session_id': 'study-test', 'revision': 1,
                          'answers': {'q1': '원래 답'}})
        self.jobs.pool.shutdown(wait=True)
        record = self.store.read('sessions', 'study-test')
        self.jobs = Jobs(self.temporary.name, runner=lambda r, q, d, e: model_result(r))
        self.jobs.submit({'request_id': 'retry-2', 'session_id': 'study-test',
                          'revision': record['revision'], 'answers': {}, 'retry_job_id': 'answer-1'})
        self.jobs.pool.shutdown(wait=True)
        record = self.store.read('sessions', 'study-test')
        result = self.jobs.cancel({'session_id': 'study-test', 'job_id': 'retry-2',
                                  'revision': record['revision']})
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.jobs.history('study-test')[0]['cancelled_by'], 'retry-2')
        restored = self.store.read('sessions', 'study-test')
        self.assertIsNone(restored['state']['pending_batch']['items'][0]['answer'])
        with self.assertRaises(StoreError):
            self.jobs.submit({'request_id': 'stale-retry', 'session_id': 'study-test',
                              'revision': restored['revision'], 'answers': {}, 'retry_job_id': 'answer-1'})
