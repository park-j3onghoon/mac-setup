import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from learning_store import Store, StoreError
from study_cancel import cancellation_path, CancelledSubmission
from study_images import decode_images, image_path
from study_jobs import Jobs
from study_runner import execute_stream, image_prompt, provider_command, ProviderStream
from study_tutor import apply_result
from test_study_app import checkpoint, model_result

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/'
                       'x8AAwMCAO+jS1kAAAAASUVORK5CYII=')


class ImageSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root, holder='web:study')
        self.record = self.store.write('sessions', checkpoint())
        self.jobs = Jobs(self.root, runner=lambda record, request, directory, emit: model_result(record))

    def tearDown(self):
        self.jobs.pool.shutdown(wait=True)
        self.temporary.cleanup()

    def payload(self):
        return {'request_id': 'image-answer', 'session_id': 'study-test', 'revision': 1,
                'answers': {'q1': ''}, 'images': [{'target': 'q1', 'name': '스크린샷.png',
                'mime_type': 'image/png', 'data_base64': base64.b64encode(PNG).decode()}]}

    def test_image_only_answer_is_saved_and_public_without_hidden_rubrics(self):
        self.jobs.submit(self.payload())
        self.jobs.pool.shutdown(wait=True)
        record = self.store.read('sessions', 'study-test')
        question = record['state']['pending_batch']['items'][0]
        self.assertEqual(question['answer'], '')
        metadata = question['submitted_images'][0]
        self.assertEqual(image_path(self.jobs.directory, metadata).read_bytes(), PNG)
        public = self.jobs.latest('study-test')
        self.assertEqual(public['submitted_answers'][0]['images'], [metadata])
        self.assertNotIn('data_base64', json.dumps(public))
        self.assertNotIn('SECRET-RUBRIC', json.dumps(public))

    def test_wrong_mime_invalid_target_and_oversized_image_are_rejected(self):
        for changes in [{'mime_type': 'image/svg+xml'}, {'target': 'unrelated'},
                        {'data_base64': base64.b64encode(PNG + b'x' * (6 * 1024 * 1024)).decode()}]:
            with self.subTest(changes=list(changes)):
                payload = self.payload()
                payload['images'][0].update(changes)
                with self.assertRaises(StoreError):
                    decode_images(self.store, payload)

    def test_cancel_returns_images_for_editing_and_reusing_the_same_answer(self):
        self.jobs.submit(self.payload())
        self.jobs.pool.shutdown(wait=True)
        record = self.store.read('sessions', 'study-test')
        result = self.jobs.cancel({'session_id': 'study-test', 'job_id': 'image-answer',
                                  'revision': record['revision']})
        image = result['submitted_answers'][0]['images'][0]
        restored = self.store.read('sessions', 'study-test')
        self.assertNotIn('submitted_images', restored['state']['pending_batch']['items'][0])
        payload = {'session_id': 'study-test', 'answers': {'q1': '수정한 설명'},
                   'images': [{'target': 'q1', 'existing': image}]}
        self.assertEqual(decode_images(self.store, payload)[0]['data'], PNG)

    def test_model_cannot_remove_original_image_evidence(self):
        self.jobs.submit(self.payload())
        self.jobs.pool.shutdown(wait=True)
        record = self.store.read('sessions', 'study-test')
        modified = copy.deepcopy(record)
        del modified['state']['pending_batch']['items'][0]['submitted_images']
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))


class ImageProviderTests(unittest.TestCase):
    @patch('study_runner.shutil.which', side_effect=lambda provider: '/bin/' + provider)
    def test_both_providers_receive_actual_image_content(self, which):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / 'fixture.png'
            image.write_bytes(PNG)
            codex = provider_command('codex', directory, {}, [image])
            claude = provider_command('claude', directory, {}, [image])
            self.assertEqual(codex[codex.index('--image') + 1], str(image))
            self.assertEqual(claude[claude.index('--input-format') + 1], 'stream-json')
            content = json.loads(image_prompt('원문', [image]))['message']['content']
            self.assertEqual(content[0]['text'], '원문')
            self.assertEqual(base64.b64decode(content[1]['source']['data']), PNG)

    def test_quiet_provider_process_is_terminated_when_cancelled(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            timer = threading.Timer(0.1, lambda: cancellation_path(directory).write_text('cancel'))
            timer.start()
            started = time.monotonic()
            stream = ProviderStream('codex', lambda event: None)
            with self.assertRaises(CancelledSubmission):
                execute_stream([sys.executable, '-c', 'import time; time.sleep(10)'], '', directory, stream)
            timer.join()
            self.assertLess(time.monotonic() - started, 3)

    def test_provider_that_closed_stdout_is_still_cancellable(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            timer = threading.Timer(0.1, lambda: cancellation_path(directory).write_text('cancel'))
            timer.start()
            started = time.monotonic()
            stream = ProviderStream('codex', lambda event: None)
            command = [sys.executable, '-c', 'import os,time; os.close(1); time.sleep(10)']
            with self.assertRaises(CancelledSubmission):
                execute_stream(command, '', directory, stream)
            timer.join()
            self.assertLess(time.monotonic() - started, 2)
