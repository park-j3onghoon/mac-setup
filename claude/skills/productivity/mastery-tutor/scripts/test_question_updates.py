"""Partial submissions and adaptive question changes preserve learning evidence."""

import copy
import unittest

from learning_store import StoreError
from study_jobs import save_answers
from study_tutor import apply_result
from study_view import session_detail
from test_study_app import checkpoint, model_result


def partial_submission():
    record = checkpoint()
    record['state']['pending_batch']['items'].append({
        'id': 'public-q2', 'number': 2, 'prompt': '남은 질문',
        'rubric': '기존 기준', 'correct_answer': '고정 정답', 'status': 'pending', 'answer': None,
    })
    save_answers(record, {'q1': '사용자의 첫 답'})
    return record


def withdraw_question(record):
    modified = copy.deepcopy(record)
    question = modified['state']['pending_batch']['items'][1]
    question.update(status='withdrawn', change_reason='새 답으로 중복 확인이 불필요해졌습니다.')
    return modified, question


class QuestionUpdateTests(unittest.TestCase):
    def test_partial_answer_keeps_other_question_pending(self):
        record = partial_submission()
        detail = session_detail(record, {})
        self.assertEqual(record['state']['grading_queue'], ['q1'])
        self.assertEqual(detail['pending_count'], 1)
        self.assertIsNone(detail['questions'][1]['answer'])
        self.assertEqual(detail['questions'][1]['status'], 'pending')

    def test_withdrawal_hides_question_and_preserves_original_and_progress(self):
        record = partial_submission()
        modified, question = withdraw_question(record)
        modified['state']['question_queue'] = []
        saved = apply_result(record, model_result(modified))
        detail = session_detail(saved, {})
        self.assertEqual([q['id'] for q in detail['questions']], ['q1'])
        self.assertEqual(detail['pending_count'], 0)
        self.assertEqual(saved['state']['pending_batch']['items'][1]['prompt'], '남은 질문')
        self.assertEqual(saved['state']['progress_display'], record['state']['progress_display'])
        self.assertEqual(saved['state']['grading_queue'], ['q1'])
        with self.assertRaises(StoreError):
            save_answers(saved, {'public-q2': '오래된 화면에서 제출한 답'})

    def test_revision_uses_new_id_and_preserves_original_rubric(self):
        record = partial_submission()
        modified, question = withdraw_question(record)
        question['replaced_by'] = 'revised-q2'
        modified['state']['pending_batch']['items'].append({
            'id': 'revised-q2', 'replaces': 'public-q2', 'number': 3,
            'prompt': '조건을 보충한 질문', 'rubric': '수정한 기준', 'status': 'pending',
        })
        saved = apply_result(record, model_result(modified))
        detail = session_detail(saved, {})
        self.assertEqual([q['id'] for q in detail['questions']], ['q1', 'revised-q2'])
        self.assertEqual(saved['state']['pending_batch']['items'][1]['rubric'], '기존 기준')
        save_answers(saved, {'revised-q2': '수정 문항에 대한 답'})
        self.assertEqual(saved['state']['grading_queue'], ['q1', 'revised-q2'])

    def test_original_prompt_rubric_and_answer_key_cannot_change(self):
        record = partial_submission()
        for key in ('prompt', 'rubric', 'correct_answer'):
            with self.subTest(key=key):
                modified, question = withdraw_question(record)
                question[key] = '덮어쓴 내용'
                with self.assertRaises(StoreError):
                    apply_result(record, model_result(modified))

    def test_unambiguous_replacement_backlink_can_be_restored(self):
        record = partial_submission()
        modified, question = withdraw_question(record)
        question['replaced_by'] = 'revised-q2'
        replacement = {'id': 'revised-q2', 'prompt': '수정 질문', 'rubric': '새 기준', 'status': 'pending'}
        modified['state']['pending_batch']['items'].append(replacement)
        saved = apply_result(record, model_result(modified))
        self.assertEqual(saved['state']['pending_batch']['items'][-1]['replaces'], 'public-q2')
        replacement['replaces'] = 'unrelated-question'
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))

    def test_withdrawal_needs_reason_and_cannot_hide_submitted_answer(self):
        record = partial_submission()
        modified, question = withdraw_question(record)
        del question['change_reason']
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))
        modified = copy.deepcopy(record)
        modified['state']['pending_batch']['items'][0].update(
            status='withdrawn', change_reason='중복이라도 제출 답은 보존해야 합니다.')
        with self.assertRaises(StoreError):
            apply_result(record, model_result(modified))

    def test_replacement_link_must_point_to_new_question(self):
        record = partial_submission()
        for replacement_id in ('q1', 'missing'):
            with self.subTest(replacement_id=replacement_id):
                modified, question = withdraw_question(record)
                question['replaced_by'] = replacement_id
                with self.assertRaises(StoreError):
                    apply_result(record, model_result(modified))

    def test_flawed_question_can_be_void_after_answering_or_grading(self):
        for status in ('answer_saved', 'graded'):
            with self.subTest(status=status):
                record = partial_submission()
                question = record['state']['pending_batch']['items'][0]
                question['status'] = status
                record['state']['graded_attempts'] = [{'id': 'q1', 'result': 'incorrect'}]
                modified = copy.deepcopy(record)
                modified['state']['pending_batch']['items'][0].update(
                    status='void', change_reason='출제 조건이 빠져 정답을 정할 수 없었습니다.')
                modified['state']['grading_queue'] = []
                saved = apply_result(record, model_result(modified))
                self.assertEqual(saved['state']['pending_batch']['items'][0]['answer'], '사용자의 첫 답')
                self.assertEqual(saved['state']['graded_attempts'], record['state']['graded_attempts'])


if __name__ == '__main__':
    unittest.main()
