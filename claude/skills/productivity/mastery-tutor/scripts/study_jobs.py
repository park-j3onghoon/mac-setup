"""Durable submissions with revision checks, per-session ownership and bounded jobs."""

from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timedelta, timezone
import threading
import time

from learning_store import Store, StoreError
from study_tutor import apply_result, run_tutor
from study_view import questions, all_questions, submitted_answer
from study_runner import provider_name, RetryableProviderError
from study_cancel import cancel_submission, cancellable, check_cancelled, cancellation_path, restore_point
from study_images import decode_images, save_images, attach_to_questions

ACTIVE_STATUSES = ('preparing', 'queued', 'running', 'responding', 'saving', 'retry_wait', 'cancelling')


def now():
    return datetime.now(timezone.utc).isoformat()


def save_answers(record, answers, image_targets=()):
    pending = {q['id']: q for q in questions(record['state'].get('pending_batch'))}
    for question_id, answer in answers.items():
        question = pending.get(question_id)
        if not question or question.get('status', 'pending') != 'pending':
            raise StoreError('문제가 바뀌었거나 이미 제출됐습니다. 최신 내용을 확인해 주세요.')
        if not isinstance(answer, str) or len(answer) > 20000:
            raise StoreError('답안을 1~20,000자 안에서 입력해 주세요.')
        if not answer.strip() and question_id not in image_targets:
            raise StoreError('답안을 1~20,000자 안에서 입력해 주세요.')
        answer_key = 'submitted_answer' if 'submitted_answer' in question else 'answer'
        time_key = 'submitted_at' if 'submitted_at' in question else 'answered_at'
        question.update({answer_key: answer, time_key: now(), 'status': 'answer_saved'})
        queue = record['state'].setdefault('grading_queue', [])
        if question_id not in queue:
            queue.append(question_id)


def retry_resolutions(jobs):
    resolved = {}
    completed_answers = {}
    for job in reversed(jobs):
        request = job.get('request', {})
        answer_ids = request.get('answer_ids', [])
        key = (tuple(sorted(answer_ids)), request.get('message', '')) if answer_ids else None
        successor = job['id'] if job['status'] == 'complete' else resolved.get(job['id'])
        if not successor and job['status'] == 'failed' and key:
            successor = completed_answers.get(key)
        if not successor:
            continue
        if job['status'] == 'failed':
            resolved[job['id']] = successor
        if job.get('retry_of'):
            resolved[job['retry_of']] = successor
        if key and job['status'] == 'complete':
            completed_answers.setdefault(key, successor)
    return resolved


def answer_snapshot(record, answer_ids):
    if not record:
        return []
    indexed = {question['id']: question for question in all_questions(record['state'])}
    return [{'id': key, 'number': indexed[key].get('number', indexed[key].get('order', '?')),
             'answer': submitted_answer(indexed[key]),
             **({'images': indexed[key]['submitted_images']} if indexed[key].get('submitted_images') else {})}
            for key in answer_ids if key in indexed and submitted_answer(indexed[key]) is not None]


class Jobs:
    def __init__(self, root, runner=run_tutor, retry_delays=(5, 15)):
        self.store = Store(root, holder='web:study')
        self.directory = self.store.root / 'web/jobs'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.runner = runner
        self.retry_delays = retry_delays
        self.lock = threading.Lock()
        self.condition = threading.Condition()
        self.versions = {}
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.recover()

    def recover(self):
        for path in self.directory.glob('*/job.json'):
            job = self.store.read_json(path)
            if job and cancellation_path(path.parent).exists() and job['status'] in ACTIVE_STATUSES:
                job.update(status='cancelled', finished_at=now())
                self.store.atomic_json(path, job)
                continue
            if job and job['status'] in ACTIVE_STATUSES:
                job.update(status='failed', error='실행기가 중단됐습니다. 저장된 답에서 다시 이어가세요.')
                self.store.atomic_json(path, job)

    def history(self, session_id):
        jobs = []
        for path in self.directory.glob('*/job.json'):
            job = self.store.read_json(path)
            if job and job['session_id'] == session_id:
                jobs.append(job)
        return sorted(jobs, key=lambda job: (job['created_at'], job['id']))

    def public_job(self, job):
        keys = ('id', 'status', 'created_at', 'finished_at', 'error', 'reply', 'reply_preview', 'model',
                'attempt', 'max_attempts', 'retry_at', 'retry_of', 'last_activity_at', 'activity_count',
                'cancelled_by')
        public = {key: job[key] for key in keys if key in job}
        request = job.get('request', {})
        answers = request.get('submitted_answers')
        if answers is None and request.get('answer_ids'):
            record = self.store.read('sessions', job['session_id'])
            answers = answer_snapshot(record, request['answer_ids'])
        public.update(provider=job.get('provider', 'codex'), message=request.get('message', ''),
                      answer_count=len(request.get('answer_ids', [])),
                      answer_ids=request.get('answer_ids', []), submitted_answers=answers or [])
        public['images'] = request.get('images', [])
        return public

    def latest(self, session_id):
        jobs = self.history(session_id)
        if not jobs:
            return None
        record = self.store.read('sessions', session_id)
        return {**self.public_job(jobs[-1]), 'can_cancel': self.can_cancel(jobs[-1], record)}

    def can_cancel(self, job, record):
        if not cancellable(job, record):
            return False
        try:
            restore_point(self, job)
            return True
        except StoreError:
            return False

    def conversation_page(self, jobs, before=None, limit=1):
        end = len(jobs)
        if before:
            indices = [index for index, job in enumerate(jobs) if job['id'] == before]
            if not indices:
                raise StoreError('이전 대화의 위치를 찾지 못했습니다. 다시 불러와 주세요.')
            end = indices[0]
        start = 0 if limit is None else max(0, end - limit)
        resolved = retry_resolutions(jobs)
        conversation = [{**self.public_job(job), 'resolved_by': resolved.get(job['id'])}
                        for job in jobs[start:end]]
        return {'conversation': conversation, 'older_before': jobs[start]['id'] if start else None}

    def session_history(self, session_id, question_ids):
        jobs = self.history(session_id)
        page = self.conversation_page(jobs, limit=1)
        if jobs:
            record = self.store.read('sessions', session_id)
            page['conversation'][-1]['can_cancel'] = self.can_cancel(jobs[-1], record)
        related = {}
        resolved = retry_resolutions(jobs)
        for job in reversed(jobs):
            ids = set(job.get('request', {}).get('answer_ids', [])) & set(question_ids) - related.keys()
            if not ids:
                continue
            public = self.public_job(job)
            public.pop('submitted_answers', None)
            public.pop('reply', None)
            public['resolved_by'] = resolved.get(job['id'])
            related.update({question_id: public for question_id in ids})
        return {**page, 'job': page['conversation'][-1] if jobs else None,
                'question_jobs': related, 'resolved_jobs': resolved}

    def publish(self, job):
        with self.condition:
            self.store.atomic_json(self.directory / job['id'] / 'job.json', job)
            session_id = job['session_id']
            self.versions[session_id] = self.versions.get(session_id, 0) + 1
            self.condition.notify_all()

    def snapshot(self, session_id):
        with self.condition:
            return self.latest(session_id), self.versions.get(session_id, 0)

    def wait_for_update(self, session_id, version):
        with self.condition:
            self.condition.wait_for(lambda: self.versions.get(session_id, 0) != version, timeout=15)

    def submit(self, payload):
        with self.lock:
            job_id = Store.valid_id(payload.get('request_id'))
            path = self.directory / job_id / 'job.json'
            existing = self.store.read_json(path)
            if existing:
                return {'id': existing['id'], 'status': existing['status']}
            decoded = decode_images(self.store, payload)
            record = self.prepare_record(payload, {image['target'] for image in decoded})
            images = save_images(self.directory / job_id, decoded)
            attach_to_questions(record, images)
            job = self.prepare_job(job_id, record, payload)
            if images:
                job['request']['images'] = images
            self.publish(job)
            try:
                saved = self.store.write('sessions', record, take_over=payload.get('take_over') is True)
            except StoreError as error:
                job.update(status='failed', error=str(error), finished_at=now())
                self.publish(job)
                raise
            job.update(status='queued', revision=saved['revision'])
            self.publish(job)
            self.pool.submit(self.execute, job, saved)
            return {'id': job_id, 'status': job['status']}

    def prepare_record(self, payload, image_targets=()):
        record = self.store.read('sessions', Store.valid_id(payload.get('session_id')))
        if not record or record['revision'] != payload.get('revision'):
            raise StoreError('다른 곳에서 기록이 갱신됐습니다. 새로고침 후 다시 제출해 주세요.')
        latest = self.latest(record['id'])
        if latest and latest['status'] in ACTIVE_STATUSES:
            raise StoreError('이 공부의 답을 처리하고 있습니다. 잠시 기다려 주세요.')
        if record['status'] == 'complete':
            raise StoreError('완료한 회차입니다. 복습은 새 회차에서 시작해 주세요.')
        if self.store.is_active_elsewhere(record) and payload.get('take_over') is not True:
            raise StoreError('이 화면에서 이어가기를 먼저 선택해 주세요.')
        record = copy.deepcopy(record)
        save_answers(record, payload.get('answers', {}), image_targets)
        record['status'] = 'active'
        return record

    def prepare_job(self, job_id, record, payload):
        provider = payload.get('provider', 'codex')
        provider_name(provider)
        message = payload.get('message', '')
        if not isinstance(message, str) or len(message) > 20000:
            raise StoreError('질문은 20,000자 이내로 입력해 주세요.')
        request = {'message': message, 'answer_ids': list(payload.get('answers', {}))}
        if payload.get('retry_job_id'):
            previous_id = Store.valid_id(payload['retry_job_id'])
            previous = self.store.read_json(self.directory / previous_id / 'job.json')
            if not previous or previous['session_id'] != record['id'] or previous['status'] != 'failed':
                raise StoreError('다시 처리할 요청을 찾지 못했습니다.')
            if previous.get('cancelled_by'):
                raise StoreError('취소한 답변입니다. 수정한 답을 새로 보내 주세요.')
            request = dict(previous['request'])
        request['provider'] = provider
        request.setdefault('submitted_answers', answer_snapshot(record, request.get('answer_ids', [])))
        return {
            'id': job_id, 'session_id': record['id'], 'created_at': now(), 'status': 'preparing',
            'request': request, 'provider': provider, 'attempt': 1,
            'max_attempts': len(self.retry_delays) + 1,
            'retry_of': payload.get('retry_job_id'),
        }

    def execute(self, job, record):
        try:
            for attempt in range(1, len(self.retry_delays) + 2):
                try:
                    self.run_attempt(job, record, attempt)
                    return
                except RetryableProviderError as error:
                    if not self.wait_to_retry(job, error, attempt):
                        raise
        except Exception as error:
            with self.lock:
                if cancellation_path(self.directory / job['id']).exists():
                    job = self.store.read_json(self.directory / job['id'] / 'job.json')
                    job.update(status='cancelled', finished_at=now())
                else:
                    job.update(status='failed', error=str(error), finished_at=now())
                self.publish(job)

    def cancel(self, payload):
        return cancel_submission(self, payload)

    def run_attempt(self, job, record, attempt):
        directory = self.directory / job['id']
        with self.lock:
            check_cancelled(directory)
            latest = self.store.read('sessions', record['id'])
            if not latest or latest['revision'] != record['revision'] or latest.get('holder') != 'web:study':
                raise StoreError('학습 기록이 바뀌어 요청을 중단했습니다. 최신 기록에서 이어가세요.')
            if attempt > 1:
                directory = directory / f'attempt-{attempt}'
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            for key in ('error', 'retry_at', 'reply_preview', 'model', 'last_activity_at', 'activity_count'):
                job.pop(key, None)
            job.update(status='running', attempt=attempt, activity_count=0)
            self.publish(job)
        result = self.runner(record, job['request'], directory, self.progress_callback(job))
        self.commit_result(job, record, result)

    def commit_result(self, job, record, result):
        with self.lock:
            check_cancelled(self.directory / job['id'])
            job.update(status='saving', reply_preview=result['reply'])
            self.publish(job)
            updated = apply_result(record, result)
            updated['state']['web_reply_provider'] = job['provider']
            updated['state']['web_reply_model'] = job.get('model', '')
            saved = self.store.write('sessions', updated)
            job.update(status='complete', reply=result['reply'], finished_at=now(),
                       applied_revision=saved['revision'])
            self.publish(job)

    def wait_to_retry(self, job, error, attempt):
        check_cancelled(self.directory / job['id'])
        if not isinstance(error, RetryableProviderError) or attempt > len(self.retry_delays):
            return False
        delay = self.retry_delays[attempt - 1]
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        job.setdefault('attempt_errors', []).append({'attempt': attempt, 'error': str(error), 'at': now()})
        with self.lock:
            check_cancelled(self.directory / job['id'])
            job.update(status='retry_wait', error=str(error), retry_at=retry_at.isoformat())
            self.publish(job)
        deadline = time.monotonic() + delay
        while True:
            check_cancelled(self.directory / job['id'])
            remaining = max(0, deadline - time.monotonic())
            time.sleep(min(0.1, remaining))
            if remaining <= 0.1:
                break
        return True

    def progress_callback(self, job):
        last_published = 0

        def update(progress):
            nonlocal last_published
            with self.lock:
                if cancellation_path(self.directory / job['id']).exists():
                    return
                allowed = {key: value for key, value in progress.items()
                           if key in ('status', 'reply_preview', 'model',
                                      'last_activity_at', 'activity_count')}
                job.update(allowed)
                current = time.monotonic()
                if current - last_published >= 0.08:
                    self.publish(job)
                    last_published = current
        return update
