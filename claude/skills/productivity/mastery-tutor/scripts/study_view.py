"""Public study views. Never send answer keys or unpublished questions to the browser."""

import math


def questions(batch):
    if isinstance(batch, list):
        return batch
    if isinstance(batch, dict):
        return batch.get('questions', batch.get('items', []))
    return []


def all_questions(state):
    result = list(questions(state.get('pending_batch')))
    for batch in state.get('batch_history', []):
        result.extend(questions(batch))
    return result


def submitted_answer(question):
    return question.get('submitted_answer', question.get('answer'))


def count_progress(value):
    passed = value.get('passed', value.get('verified_items'))
    total = value.get('total', value.get('planned_items'))
    if not isinstance(passed, (int, float)) or not isinstance(total, (int, float)):
        return {'passed': None, 'total': None, 'percent': None}
    if total <= 0 or passed < 0 or passed > total:
        return {'passed': None, 'total': None, 'percent': None}
    return {'passed': passed, 'total': total, 'percent': math.floor(passed / total * 100)}


def public_question(question):
    return {
        'id': question['id'], 'number': question.get('number', question.get('order', '?')),
        'prompt': question.get('prompt', question.get('text', '')),
        'choices': question.get('choices') or question.get('options') or [],
        'status': question.get('status', 'pending'), 'answer': submitted_answer(question),
        'images': question.get('submitted_images', []),
    }


def concept_definitions(learning_map):
    concepts = learning_map.get('concepts', {})
    if isinstance(concepts, list):
        return {concept['id']: concept for concept in concepts}
    return concepts


def criterion_status(value):
    if isinstance(value, dict):
        return value.get('status', 'not_assessed')
    return value or 'not_assessed'


def concept_view(concept_id, state, definitions, cards):
    definition = definitions.get(concept_id, {})
    card = cards.get(concept_id, {})
    evidence = state.get('concept_evidence', {}).get(concept_id, {})
    evidence = evidence.get('criteria', evidence)
    criteria = {key: criterion_status(evidence.get(key))
                for key in ('basic', 'explain', 'apply', 'boundary')}
    if 'review' in evidence:
        criteria['review'] = criterion_status(evidence['review'])
    progress = {'passed': sum(value == 'passed' for value in criteria.values()), 'total': len(criteria)}
    return {
        'id': concept_id, 'title': definition.get('title') or card.get('title') or concept_id,
        'criteria': criteria, 'progress': count_progress(progress),
        'summary': card.get('summary_markdown', ''),
    }


def block_views(state, cards):
    learning_map = state.get('learning_map', {})
    definitions = concept_definitions(learning_map)
    progress = state.get('progress_display', {}).get('per_block', {})
    result = []
    blocks = list(learning_map.get('blocks', []))
    final = learning_map.get('final', learning_map.get('final_verification'))
    if final and not any(block['id'] == 'final' for block in blocks):
        blocks.append({**final, 'id': 'final', 'title': '종합 검증'})
    for block in blocks:
        concept_ids = block.get('concepts', block.get('concept_ids', []))
        concepts = [concept_view(key, state, definitions, cards) for key in concept_ids]
        result.append({
            'id': block['id'], 'title': block.get('title', block['id']),
            'status': block.get('status', '대기'),
            'progress': block_progress(block, state, concepts, progress.get(block['id'], {})),
            'concepts': concepts,
        })
    return result


def block_progress(block, state, concepts, stored):
    progress = count_progress(stored)
    if progress['percent'] is not None or not concepts:
        return progress
    objective = state.get('objective_progress', {}).get(block['id'], block.get('objective_gate', {}))
    if isinstance(objective, dict):
        objective = objective.get('status', objective.get('gate'))
    if objective != 'waived_by_user_preference':
        return progress
    return count_progress({'passed': sum(c['progress']['passed'] for c in concepts),
                           'total': sum(c['progress']['total'] for c in concepts)})


def session_summary(record):
    state = record['state']
    pending = questions(state.get('pending_batch'))
    return {
        'id': record['id'], 'topic': record['topic'], 'status': record['status'],
        'revision': record['revision'], 'saved_at': record.get('saved_at'),
        'progress': count_progress(state.get('progress_display', {})),
        'pending_count': sum(q.get('status', 'pending') == 'pending' for q in pending),
        'grading_count': len(state.get('grading_queue', [])), 'phase': state.get('phase', ''),
    }


def session_detail(record, cards):
    state = record['state']
    learning_map = state.get('learning_map', {})
    pending = [public_question(q) for q in questions(state.get('pending_batch'))
               if q.get('status') not in ('void', 'withdrawn', 'retired')]
    return {
        **session_summary(record), 'blocks': block_views(state, cards), 'questions': pending,
        'current_block': state.get('current_block'), 'notes': record.get('summary_markdown', ''),
        'scope': learning_map.get('scope') or learning_map.get('goal') or learning_map.get('scope_note', ''),
        'reply': state.get('web_reply', ''), 'web_owned': record.get('holder') == 'web:study',
        'reply_provider': state.get('web_reply_provider', 'codex'),
        'reply_model': state.get('web_reply_model', ''),
        'review_count': sum(r.get('status', 'open') not in ('closed', 'passed', 'resolved')
                            for r in state.get('review_queue', [])),
    }
