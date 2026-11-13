"""Undo the latest submission using revisioned checkpoints; preserve the original request."""

import copy
from pathlib import Path

from learning_store import Store, StoreError


class CancelledSubmission(StoreError):
    """The user withdrew this request; the runner must not save or retry it."""


def cancellation_path(directory):
    directory = Path(directory)
    root = directory.parent if directory.name.startswith('attempt-') else directory
    return root / 'cancel.requested'


def check_cancelled(directory):
    if cancellation_path(directory).exists():
        raise CancelledSubmission('사용자가 답변을 취소했습니다.')


def restore_point(jobs, job):
    source = job
    seen = set()
    while source.get('retry_of'):
        if source['id'] in seen:
            raise StoreError('재시도 연결이 올바르지 않아 취소할 수 없습니다.')
        seen.add(source['id'])
        previous = Store.valid_id(source['retry_of'])
        ancestor = jobs.store.read_json(jobs.directory / previous / 'job.json')
        if not ancestor or ancestor.get('session_id') != job['session_id']:
            raise StoreError('제출 이전 기록을 찾지 못했습니다.')
        if source.get('revision') != ancestor.get('revision', -2) + 1:
            raise StoreError('원래 제출 뒤 다른 학습이 진행되어 이전 답 전체를 취소할 수 없습니다.')
        source = ancestor
    revision = source.get('revision', 0) - 1
    path = jobs.store.root / 'sessions' / job['session_id'] / 'history' / f'{revision:08d}.json'
    before = jobs.store.read_json(path)
    if not before or not Store.valid_record(before, job['session_id']):
        raise StoreError('제출 이전 기록을 찾지 못했습니다.')
    return before


def mark_cancelled_ancestors(jobs, job):
    ancestor_id = job.get('retry_of')
    while ancestor_id:
        path = jobs.directory / ancestor_id / 'job.json'
        ancestor = jobs.store.read_json(path)
        ancestor['cancelled_by'] = job['id']
        jobs.store.atomic_json(path, ancestor)
        ancestor_id = ancestor.get('retry_of')


def cancellable(job, record):
    if not job or not record or not isinstance(job.get('request'), dict):
        return False
    if job['status'] not in ('queued', 'running', 'responding', 'saving', 'retry_wait', 'failed', 'complete'):
        return False
    expected = job.get('revision')
    if job['status'] == 'complete' and expected is not None:
        expected = job.get('applied_revision', expected + 1)
    return record.get('holder') == 'web:study' and record['revision'] == expected


def cancel_submission(jobs, payload):
    session_id = Store.valid_id(payload.get('session_id'))
    job_id = Store.valid_id(payload.get('job_id'))
    with jobs.lock:
        record = jobs.store.read('sessions', session_id)
        history = jobs.history(session_id)
        job = history[-1] if history else None
        if not record or record['revision'] != payload.get('revision'):
            raise StoreError('학습 기록이 바뀌었습니다. 최신 화면에서 다시 취소해 주세요.')
        if not job or job['id'] != job_id or not cancellable(job, record):
            raise StoreError('후속 학습이 진행되어 이 답변을 취소할 수 없습니다.')
        restored = copy.deepcopy(restore_point(jobs, job))
        answers = jobs.public_job(job)['submitted_answers']
        job['request'].setdefault('submitted_answers', answers)
        restored.update(revision=record['revision'], status='active')
        audit = restored['state'].setdefault('submission_cancellations', [])
        audit.append({'job_id': job_id, 'request': copy.deepcopy(job['request'])})
        # The revision check in Store.write prevents overwriting another writer.
        saved = jobs.store.write('sessions', restored)
        directory = jobs.directory / job_id
        jobs.store.atomic_text(cancellation_path(directory), 'cancelled\n')
        mark_cancelled_ancestors(jobs, job)
        was_running = job['status'] in ('running', 'responding', 'saving', 'retry_wait')
        job.update(status='cancelling' if was_running else 'cancelled', cancelled_revision=saved['revision'])
        jobs.publish(job)
        return {'id': job_id, 'status': job['status'], 'revision': saved['revision'],
                'submitted_answers': job['request'].get('submitted_answers', []),
                'answer_ids': job['request'].get('answer_ids', []),
                'message': job['request'].get('message', ''), 'images': job['request'].get('images', [])}
