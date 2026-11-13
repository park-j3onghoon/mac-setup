"""Retries reuse durable answers, stop at a fixed bound, and respect newer checkpoints."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from learning_store import Store, StoreError
from study_jobs import Jobs, retry_resolutions
from study_runner import RetryableProviderError, provider_failure
from study_tutor import apply_result
from test_study_app import checkpoint, model_result


class ResultShapeTests(unittest.TestCase):
    def test_same_session_wrapper_is_unwrapped_without_trusting_outer_metadata(self):
        record = checkpoint()
        wrapped = copy.deepcopy(record)
        wrapped.update(revision=999, holder='untrusted-holder')
        result = model_result(record)
        result['state_json'] = json.dumps(wrapped)
        saved = apply_result(record, result)
        self.assertEqual(saved['revision'], record['revision'])
        self.assertNotIn('holder', saved)
        self.assertEqual(saved['state']['pending_batch'], record['state']['pending_batch'])

    def test_wrapper_does_not_bypass_session_or_answer_validation(self):
        record = checkpoint()
        for change in ('session', 'answer'):
            with self.subTest(change=change):
                wrapped = copy.deepcopy(record)
                if change == 'session':
                    wrapped['id'] = 'different-session'
                else:
                    wrapped['state']['pending_batch']['items'][0]['answer'] = '가짜 답'
                result = model_result(record)
                result['state_json'] = json.dumps(wrapped)
                with self.assertRaises(StoreError):
                    apply_result(record, result)

    def test_transient_provider_errors_exclude_auth_quota_and_unknown_errors(self):
        transient = ['HTTP 429 rate limit', '503 service unavailable', 'stream disconnected',
                     'Connection reset by peer', 'request timed out']
        for message in transient:
            self.assertIsInstance(provider_failure(message), RetryableProviderError)
        for message in ('401 unauthorized', '429 quota exceeded', 'usage limit reached',
                        'billing limit', 'permission denied', 'unexpected program error'):
            self.assertNotIsInstance(provider_failure(message), RetryableProviderError)


class RetryHistoryTests(unittest.TestCase):
    def job(self, job_id, status, answers=None, message='답 제출', retry_of=None):
        return {'id': job_id, 'status': status, 'retry_of': retry_of,
                'request': {'answer_ids': answers or [], 'message': message}}

    def test_legacy_failed_answer_is_resolved_only_by_same_request_success(self):
        failed = self.job('failed', 'failed', ['q1'])
        success = self.job('success', 'complete', ['q1'])
        self.assertEqual(retry_resolutions([failed, success]), {'failed': 'success'})
        self.assertEqual(failed['status'], 'failed')

    def test_unrelated_or_unfinished_requests_do_not_resolve_failure(self):
        failed = self.job('failed', 'failed', ['q1'])
        others = [self.job('other', 'complete', ['q2']), self.job('other', 'running', ['q1']),
                  self.job('other', 'failed', ['q1']), self.job('other', 'complete', ['q1'], '다른 요청')]
        for other in others:
            with self.subTest(other=other):
                self.assertEqual(retry_resolutions([failed, other]), {})
        first = self.job('first', 'failed', message='일반 질문')
        repeated = self.job('second', 'complete', message='일반 질문')
        self.assertEqual(retry_resolutions([first, repeated]), {})

    def test_explicit_retry_chain_resolves_a_general_question(self):
        jobs = [self.job('first', 'failed'), self.job('second', 'failed', retry_of='first'),
                self.job('third', 'complete', retry_of='second')]
        self.assertEqual(retry_resolutions(jobs), {'first': 'third', 'second': 'third'})


class RetryJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root, holder='codex:original')
        self.record = self.store.write('sessions', checkpoint())
        self.calls = []
        self.behavior = lambda record: model_result(record)
        self.jobs = Jobs(self.root, runner=self.run_tutor, retry_delays=(0, 0))

    def tearDown(self):
        self.jobs.pool.shutdown(wait=True)
        self.temporary.cleanup()

    def run_tutor(self, record, request, directory, emit):
        self.calls.append((copy.deepcopy(record), copy.deepcopy(request), directory))
        return self.behavior(record)

    def payload(self):
        return {'request_id': 'retry-test', 'session_id': self.record['id'], 'revision': 1,
                'answers': {'q1': '  저장한 원답\n  '}, 'message': '답 제출', 'take_over': True}

    def finish(self):
        self.jobs.submit(self.payload())
        self.jobs.pool.shutdown(wait=True)
        return self.jobs.latest(self.record['id'])

    def test_transient_retry_succeeds_once_without_resubmitting_answer(self):
        def behavior(record):
            if len(self.calls) == 1:
                raise RetryableProviderError('network error')
            return model_result(record)
        self.behavior = behavior
        job = self.finish()
        self.assertEqual((job['status'], job['attempt']), ('complete', 2))
        self.assertEqual(job['answer_ids'], ['q1'])
        self.assertEqual(len(self.jobs.history(self.record['id'])), 1)
        self.assertEqual(self.calls[0][0], self.calls[1][0])
        self.assertEqual(self.calls[1][2].name, 'attempt-2')
        saved = self.store.read('sessions', self.record['id'])
        self.assertEqual(saved['revision'], 3)
        self.assertEqual(saved['state']['pending_batch']['items'][0]['answer'], '  저장한 원답\n  ')

    def test_public_original_answer_survives_archiving_and_legacy_request_recovery(self):
        def archive(record):
            modified = copy.deepcopy(record)
            modified['state']['batch_history'].append(modified['state']['pending_batch'])
            modified['state']['pending_batch'] = None
            return model_result(modified)
        self.behavior = archive
        job = self.finish()
        expected = [{'id': 'q1', 'number': 1, 'answer': '  저장한 원답\n  '}]
        self.assertEqual(job['submitted_answers'], expected)
        original = self.jobs.history(self.record['id'])[0]
        del original['request']['submitted_answers']
        self.assertEqual(self.jobs.public_job(original)['submitted_answers'], expected)
        self.assertNotIn('SECRET-RUBRIC', json.dumps(self.jobs.public_job(original)))

    def test_repeated_transient_failure_stops_after_three_attempts(self):
        def fail(record):
            raise RetryableProviderError('temporary failure')
        self.behavior = fail
        job = self.finish()
        self.assertEqual((job['status'], job['attempt'], job['max_attempts']), ('failed', 3, 3))
        self.assertEqual(len(self.calls), 3)
        saved = self.store.read('sessions', self.record['id'])
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(saved['state']['grading_queue'], ['q1'])

    def test_validation_failure_does_not_repeat_inference(self):
        def invalid(record):
            result = model_result(record)
            result['state_json'] = '{}'
            return result
        self.behavior = invalid
        self.assertEqual(self.finish()['status'], 'failed')
        self.assertEqual(len(self.calls), 1)

    def test_auth_failure_does_not_repeat_inference(self):
        def denied(record):
            raise provider_failure('401 authentication required')
        self.behavior = denied
        self.assertEqual(self.finish()['status'], 'failed')
        self.assertEqual(len(self.calls), 1)

    def test_retry_rechecks_revision_before_any_new_provider_call(self):
        def fail(record):
            raise RetryableProviderError('timeout')
        def change_record(delay):
            record = self.store.read('sessions', self.record['id'])
            record['summary_markdown'] = '다른 대화의 최신 기록'
            self.store.write('sessions', record, take_over=True)
        self.behavior = fail
        with patch('study_jobs.time.sleep', side_effect=change_record):
            job = self.finish()
        self.assertEqual(job['status'], 'failed')
        self.assertIn('기록이 바뀌어', job['error'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.store.read('sessions', self.record['id'])['holder'], 'codex:original')

    def test_retry_wait_is_public_and_blocks_duplicate_submission(self):
        observations = []
        def fail_once(record):
            if len(self.calls) == 1:
                raise RetryableProviderError('connection reset')
            return model_result(record)
        def while_waiting(delay):
            job = self.jobs.latest(self.record['id'])
            observations.append(job)
            payload = self.payload()
            payload.update(request_id='duplicate', revision=2, answers={})
            with self.assertRaises(StoreError):
                self.jobs.submit(payload)
        self.behavior = fail_once
        with patch('study_jobs.time.sleep', side_effect=while_waiting):
            job = self.finish()
        self.assertEqual(job['status'], 'complete')
        self.assertEqual(observations[0]['status'], 'retry_wait')
        self.assertIn('retry_at', observations[0])
        self.assertEqual(observations[0]['answer_ids'], ['q1'])


if __name__ == '__main__':
    unittest.main()
