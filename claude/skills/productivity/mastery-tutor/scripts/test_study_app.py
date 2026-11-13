"""Study-room invariants, using isolated records and a deterministic fake tutor."""

import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from learning_store import Store, StoreError
from study_jobs import Jobs, save_answers
from study_tutor import apply_result
from study_view import session_detail
from study_server import Handler, load_token, render_html


def checkpoint():
    return {
        'id': 'study-test', 'topic': '테스트용 비율', 'revision': 0, 'schema_version': 1,
        'status': 'active', 'summary_markdown': '시험 기록입니다.',
        'state': {
            'learning_map': {'blocks': [{'id': 'A', 'concept_ids': ['ratio'], 'status': '학습 중'}]},
            'concept_evidence': {'ratio': {'criteria': {'basic': {'status': 'passed'}}}},
            'pending_batch': {'id': 'batch-1', 'items': [
                {'id': 'q1', 'prompt': '전체 4개 중 2개는 얼마인가요?', 'rubric': 'SECRET-RUBRIC',
                 'answer': None, 'status': 'pending', 'number': 1}]},
            'batch_history': [], 'grading_queue': [], 'review_queue': [],
            'question_queue': [{'id': 'q2', 'prompt': 'UNPUBLISHED-QUESTION', 'rubric': 'HIDDEN'}],
            'progress_display': {'verified_items': 1, 'planned_items': 7},
        },
    }


def model_result(record):
    return {'state_json': json.dumps(record['state']), 'reply': '확인했습니다.',
            'summary_markdown': record['summary_markdown'], 'status': record['status']}


class StudyViewTests(unittest.TestCase):
    def test_legacy_shapes_and_secrets(self):
        detail = session_detail(checkpoint(), {})
        concept = detail['blocks'][0]['concepts'][0]
        self.assertEqual(concept['progress']['percent'], 25)
        self.assertEqual(detail['progress']['percent'], 14)
        self.assertEqual(detail['questions'][0]['prompt'], '전체 4개 중 2개는 얼마인가요?')
        serialized = json.dumps(detail)
        self.assertNotIn('SECRET-RUBRIC', serialized)
        self.assertNotIn('UNPUBLISHED-QUESTION', serialized)

    def test_saved_answer_preserves_text_and_does_not_grade(self):
        record = checkpoint()
        save_answers(record, {'q1': '  50%입니다.\n이유는 반이어서요.  '})
        question = record['state']['pending_batch']['items'][0]
        self.assertEqual(question['answer'], '  50%입니다.\n이유는 반이어서요.  ')
        self.assertEqual(question['status'], 'answer_saved')
        self.assertEqual(record['state']['grading_queue'], ['q1'])
        self.assertEqual(record['state']['progress_display']['verified_items'], 1)
        with self.assertRaises(StoreError):
            save_answers(record, {'q1': '두 번째 답'})

    def test_model_cannot_replace_answer_or_lose_history(self):
        record = checkpoint()
        save_answers(record, {'q1': '50%'})
        modified = copy.deepcopy(record)
        modified['state']['pending_batch']['items'][0]['answer'] = '100%'
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))
        modified['state']['pending_batch'] = None
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))

    def test_unanswered_cannot_be_graded(self):
        record = checkpoint()
        modified = copy.deepcopy(record)
        modified['state']['pending_batch']['items'][0]['status'] = 'graded'
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))

    def test_cached_100_does_not_complete_unverified_learning(self):
        record = checkpoint()
        modified = copy.deepcopy(record)
        modified['state']['progress_display'] = {'verified_items': 7, 'planned_items': 7}
        modified['status'] = 'complete'
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))

    def test_duplicate_ids_cannot_hide_fabricated_answer(self):
        record = checkpoint()
        modified = copy.deepcopy(record)
        modified['state']['batch_history'] = [copy.deepcopy(record['state']['pending_batch'])]
        question = modified['state']['pending_batch']['items'][0]
        question.update(answer='가짜 답', status='graded')
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))

    def test_model_cannot_delete_learning_map_evidence_or_review(self):
        record = checkpoint()
        record['state']['review_queue'] = [{'id': 'review-1', 'status': 'open'}]
        changes = [('learning_map', {}), ('concept_evidence', {}), ('review_queue', [])]
        for key, replacement in changes:
            with self.subTest(key=key):
                modified = copy.deepcopy(record)
                modified['state'][key] = replacement
                with self.assertRaises(StoreError):
                    apply_result(record, model_result(modified))


class StudyJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root, holder='codex:original')
        self.record = self.store.write('sessions', checkpoint())
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls = []
        self.jobs = Jobs(self.root, runner=self.fake_tutor)

    def tearDown(self):
        self.release.set()
        self.jobs.pool.shutdown(wait=True)
        self.temporary.cleanup()

    def fake_tutor(self, record, request, directory, emit):
        self.calls.append(request)
        self.started.set()
        self.release.wait(5)
        return model_result(record)

    def payload(self):
        return {'request_id': 'request-1', 'session_id': 'study-test', 'revision': self.record['revision'],
                'answers': {'q1': '50%'}, 'message': '이유를 알려 주세요.', 'take_over': True}

    def test_view_does_not_claim_and_takeover_is_explicit(self):
        session_detail(self.store.read('sessions', 'study-test'), {})
        self.assertEqual(self.store.read('sessions', 'study-test')['holder'], 'codex:original')
        payload = self.payload()
        payload['take_over'] = False
        with self.assertRaises(StoreError):
            self.jobs.submit(payload)

    def test_duplicate_submission_runs_once_and_saves_before_model(self):
        payload = self.payload()
        first = self.jobs.submit(payload)
        second = self.jobs.submit(payload)
        self.assertEqual(first['id'], second['id'])
        self.assertTrue(self.started.wait(2))
        saved = self.store.read('sessions', 'study-test')
        self.assertEqual(saved['state']['grading_queue'], ['q1'])
        self.assertEqual(saved['holder'], 'web:study')
        self.assertEqual(len(self.calls), 1)

    def test_stale_request_is_rejected(self):
        payload = self.payload()
        payload['revision'] = 0
        with self.assertRaises(StoreError):
            self.jobs.submit(payload)
        self.assertEqual(self.store.read('sessions', 'study-test')['revision'], 1)

    def test_concurrent_session_update_wins_over_model(self):
        self.jobs.submit(self.payload())
        self.assertTrue(self.started.wait(2))
        latest = self.store.read('sessions', 'study-test')
        latest['summary_markdown'] = '다른 대화에서 저장한 최신 내용'
        self.store.write('sessions', latest, take_over=True)
        self.release.set()
        self.jobs.pool.shutdown(wait=True)
        self.assertEqual(self.jobs.latest('study-test')['status'], 'failed')
        saved_summary = self.store.read('sessions', 'study-test')['summary_markdown']
        self.assertEqual(saved_summary, latest['summary_markdown'])

    def test_retry_keeps_failed_question(self):
        job = {'id': 'failed-1', 'session_id': 'study-test', 'status': 'failed', 'created_at': '2000',
               'request': {'message': '실패한 원래 질문', 'answer_ids': []}}
        self.store.atomic_json(self.jobs.directory / 'failed-1/job.json', job)
        payload = self.payload()
        payload.update(answers={}, message='', retry_job_id='failed-1')
        self.jobs.submit(payload)
        self.assertTrue(self.started.wait(2))
        self.assertEqual(self.calls[0]['message'], '실패한 원래 질문')
        self.assertEqual(self.jobs.latest('study-test')['retry_of'], 'failed-1')

    def test_selected_provider_is_passed_and_saved_with_reply(self):
        payload = self.payload()
        payload['provider'] = 'claude'
        self.jobs.submit(payload)
        self.release.set()
        self.jobs.pool.shutdown(wait=True)
        self.assertEqual(self.calls[0]['provider'], 'claude')
        self.assertEqual(self.jobs.latest('study-test')['provider'], 'claude')
        saved = self.store.read('sessions', 'study-test')
        self.assertEqual(saved['state']['web_reply_provider'], 'claude')

    def test_unknown_provider_does_not_change_checkpoint(self):
        payload = self.payload()
        payload['provider'] = 'unsupported'
        with self.assertRaises(StoreError):
            self.jobs.submit(payload)
        self.assertEqual(self.store.read('sessions', 'study-test')['revision'], 1)

    def test_progress_event_does_not_commit_unvalidated_checkpoint(self):
        self.jobs.submit(self.payload())
        self.assertTrue(self.started.wait(2))
        saved = self.store.read('sessions', 'study-test')
        job, version = self.jobs.snapshot('study-test')
        raw = self.store.read_json(self.jobs.directory / job['id'] / 'job.json')
        callback = self.jobs.progress_callback(raw)
        callback({'status': 'responding', 'reply_preview': '설명을 준비했습니다.'})
        update, new_version = self.jobs.snapshot('study-test')
        self.assertGreater(new_version, version)
        self.assertEqual(update['reply_preview'], '설명을 준비했습니다.')
        self.assertEqual(self.store.read('sessions', 'study-test')['revision'], saved['revision'])


class StudyHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name, holder='codex:test')
        self.record = self.store.write('sessions', checkpoint())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.store = self.store
        runner = lambda record, request, path, emit: model_result(record)
        self.server.jobs = Jobs(self.store.root, runner=runner)
        self.server.token = 'test-token'
        self.server.html = render_html(self.server.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.jobs.pool.shutdown(wait=True)
        self.thread.join()
        self.temporary.cleanup()

    def test_http_auth_origin_and_submission(self):
        path = self.url + '/api/sessions/study-test'
        with self.assertRaises(HTTPError) as failure:
            urlopen(path)
        self.assertEqual(failure.exception.code, 403)
        headers = {'X-Study-Token': 'test-token', 'Origin': 'https://example.com'}
        with self.assertRaises(HTTPError) as failure:
            urlopen(Request(path, headers=headers))
        self.assertEqual(failure.exception.code, 403)
        headers.pop('Origin')
        with urlopen(Request(path, headers=headers)) as response:
            detail = json.load(response)
        self.assertNotIn('SECRET-RUBRIC', json.dumps(detail))
        payload = {'request_id': 'http-1', 'session_id': 'study-test', 'revision': 1,
                   'take_over': True, 'answers': {'q1': '50%'}, 'message': '채점해 주세요.'}
        request = Request(self.url + '/api/submit', data=json.dumps(payload).encode(), headers=headers)
        with urlopen(request) as response:
            self.assertEqual(response.status, 202)
        self.server.jobs.pool.shutdown(wait=True)
        saved = self.store.read('sessions', 'study-test')
        self.assertEqual(saved['state']['pending_batch']['items'][0]['answer'], '50%')
        self.assertEqual(saved['state']['web_reply'], '확인했습니다.')

    def test_connection_recovers_token_only_for_local_origin(self):
        with urlopen(self.url + '/api/connection') as response:
            self.assertEqual(json.load(response)['token'], 'test-token')
        headers = {'Origin': 'https://example.com', 'Sec-Fetch-Site': 'cross-site'}
        request = Request(self.url + '/api/connection', headers=headers)
        with self.assertRaises(HTTPError) as failure:
            urlopen(request)
        self.assertEqual(failure.exception.code, 403)

    def test_conversation_endpoint_requires_auth_and_valid_session_cursor(self):
        job = {'id': 'first', 'session_id': 'study-test', 'created_at': '2000',
               'status': 'complete', 'reply': '첫 대화', 'request': {}}
        self.server.jobs.publish(job)
        self.server.jobs.publish({**job, 'id': 'latest', 'created_at': '2001'})
        path = self.url + '/api/conversations/study-test?before=latest'
        with self.assertRaises(HTTPError) as failure:
            urlopen(path)
        self.assertEqual(failure.exception.code, 403)
        headers = {'X-Study-Token': 'test-token'}
        with urlopen(Request(path, headers=headers)) as response:
            page = json.load(response)
        self.assertEqual([item['id'] for item in page['conversation']], ['first'])
        self.assertIsNone(page['older_before'])
        with self.assertRaises(HTTPError) as failure:
            urlopen(Request(path.replace('before=latest', 'before=unknown'), headers=headers))
        self.assertEqual(failure.exception.code, 400)

    def test_history_defaults_to_one_and_all_is_explicit(self):
        for number in range(4):
            self.server.jobs.publish({'id': f'job-{number}', 'session_id': 'study-test',
                'created_at': str(number), 'status': 'complete', 'request': {}})
        headers = {'X-Study-Token': 'test-token'}
        path = self.url + '/api/conversations/study-test?before=job-3'
        with urlopen(Request(path, headers=headers)) as response:
            self.assertEqual(len(json.load(response)['conversation']), 1)
        with urlopen(Request(path + '&all=1', headers=headers)) as response:
            self.assertEqual(len(json.load(response)['conversation']), 3)

    def test_cancel_and_image_reads_are_authenticated(self):
        from test_study_images import PNG
        import base64
        headers = {'X-Study-Token': 'test-token'}
        payload = {'request_id': 'image-http', 'session_id': 'study-test', 'revision': 1,
            'take_over': True, 'answers': {'q1': ''}, 'images': [{'target': 'q1', 'name': 'shot.png',
            'mime_type': 'image/png', 'data_base64': base64.b64encode(PNG).decode()}]}
        request = Request(self.url + '/api/submit', data=json.dumps(payload).encode(), headers=headers)
        with urlopen(request) as response:
            self.assertEqual(response.status, 202)
        self.server.jobs.pool.shutdown(wait=True)
        job = self.server.jobs.latest('study-test')
        image = job['images'][0]
        path = self.url + f'/api/images/{image["job_id"]}/{image["id"]}'
        with self.assertRaises(HTTPError):
            urlopen(path)
        with urlopen(Request(path, headers=headers)) as response:
            self.assertEqual(response.read(), PNG)
            self.assertEqual(response.headers['Content-Type'], 'image/png')
        record = self.store.read('sessions', 'study-test')
        cancel = {'session_id': 'study-test', 'job_id': 'image-http', 'revision': record['revision']}
        request = Request(self.url + '/api/cancel', data=json.dumps(cancel).encode(), headers=headers)
        with urlopen(request) as response:
            self.assertEqual(json.load(response)['status'], 'cancelled')

    def test_restart_keeps_existing_page_token(self):
        web = self.store.root / 'web'
        web.mkdir(exist_ok=True)
        token = 'a' * 43
        (web / 'index.html').write_text(render_html(token))
        self.assertEqual(load_token(web), token)
        (web / 'index.html').unlink()
        self.assertEqual(load_token(web), token)

    def test_event_stream_delivers_job_changes_without_polling(self):
        headers = {'X-Study-Token': 'test-token'}
        request = Request(self.url + '/api/events/study-test', headers=headers)
        with urlopen(request, timeout=2) as response:
            self.assertEqual(response.readline(), b'event: job\n')
            self.assertEqual(json.loads(response.readline()[6:]), {'job': None})
            response.readline()
            job = {'id': 'stream-1', 'session_id': 'study-test', 'created_at': '2000',
                   'status': 'responding', 'provider': 'claude', 'reply_preview': '안녕하세요.', 'request': {}}
            self.server.jobs.publish(job)
            self.assertEqual(response.readline(), b'event: job\n')
            update = json.loads(response.readline()[6:])['job']
            self.assertEqual(update['provider'], 'claude')
            self.assertEqual(update['reply_preview'], '안녕하세요.')


if __name__ == '__main__':
    unittest.main()
