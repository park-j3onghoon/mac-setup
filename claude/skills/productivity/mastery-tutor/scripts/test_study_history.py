"""History pagination must preserve every job and per-question recovery controls."""

import json
import tempfile
import unittest

from learning_store import StoreError
from study_jobs import Jobs


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.jobs = Jobs(self.temporary.name)
        for index in range(23):
            self.jobs.publish({'id': f'job-{index:02}', 'session_id': 'study-test',
                               'created_at': '2026-11-06', 'status': 'complete', 'reply': str(index),
                               'request': {'submitted_answers': [], 'answer_ids': []}})

    def tearDown(self):
        self.jobs.pool.shutdown(wait=True)
        self.temporary.cleanup()

    def test_latest_one_then_five_at_a_time_reaches_first_record(self):
        page = self.jobs.session_history('study-test', [])
        self.assertEqual([job['id'] for job in page['conversation']], ['job-22'])
        seen = ['job-22']
        jobs = self.jobs.history('study-test')
        while page['older_before']:
            page = self.jobs.conversation_page(jobs, before=page['older_before'])
            self.assertLessEqual(len(page['conversation']), 5)
            seen = [job['id'] for job in page['conversation']] + seen
        self.assertEqual(seen, [f'job-{index:02}' for index in range(23)])

    def test_unknown_cursor_is_rejected_and_empty_history_is_empty(self):
        with self.assertRaises(StoreError):
            self.jobs.conversation_page(self.jobs.history('study-test'), before='other-session-job')
        self.assertEqual(self.jobs.session_history('empty', [])['conversation'], [])

    def test_hidden_failure_keeps_question_retry_without_loading_old_replies(self):
        job = self.jobs.history('study-test')[0]
        job.update(status='failed', reply='OLD-REPLY', error='network error')
        job['request'] = {'answer_ids': ['q1'], 'submitted_answers': [], 'rubric': 'SECRET-RUBRIC'}
        self.jobs.publish(job)
        page = self.jobs.session_history('study-test', ['q1'])
        self.assertEqual(page['question_jobs']['q1']['id'], 'job-00')
        self.assertEqual(page['question_jobs']['q1']['status'], 'failed')
        self.assertNotIn('OLD-REPLY', json.dumps(page))
        self.assertNotIn('SECRET-RUBRIC', json.dumps(page))

    def test_new_job_does_not_shift_an_existing_cursor(self):
        jobs = self.jobs.history('study-test')
        expected = self.jobs.conversation_page(jobs, before='job-22')
        self.jobs.publish({**jobs[-1], 'id': 'job-23'})
        self.assertEqual(self.jobs.conversation_page(self.jobs.history('study-test'), before='job-22'),
                         expected)
