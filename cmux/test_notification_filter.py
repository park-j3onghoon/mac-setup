import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

MODULE = runpy.run_path(str(Path(__file__).with_name('notification-filter.py')))


class CompletionFilterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.session_id = '1234-abcd'
        self.directory = self.root / '.codex/sessions/2026/11/06'
        self.directory.mkdir(parents=True)
        self.path = self.directory / f'rollout-test-{self.session_id}.jsonl'
        self.metadata = {'type': 'session_meta', 'payload': {'id': self.session_id,
                         'thread_source': 'user', 'timestamp': '2026-11-06'}}
        self.write([self.metadata, self.event('task_started')])
        self.registry(self.path)
        self.envelope = {'notification': {'title': 'Codex', 'subtitle': 'Completed in project',
                                         'surfaceId': 'SURFACE'}}

    def tearDown(self):
        self.temporary.cleanup()

    def event(self, kind):
        return {'type': 'event_msg', 'payload': {'type': kind}}

    def write(self, entries):
        self.path.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))

    def registry(self, transcript):
        directory = self.root / '.cmuxterm'
        directory.mkdir(exist_ok=True)
        value = {'sessions': {self.session_id: {'sessionId': self.session_id, 'surfaceId': 'surface',
                                              'transcriptPath': str(transcript)}}}
        (directory / 'codex-hook-sessions.json').write_text(json.dumps(value))

    def apply(self):
        return MODULE['filter_notification'](self.envelope, self.root)

    def test_legacy_completion_during_work_is_silent(self):
        self.assertFalse(self.apply()['effects']['desktop'])

    def test_final_completion_keeps_banner_without_needs_input(self):
        self.write([self.metadata, self.event('task_started'), self.event('task_complete')])
        self.assertEqual(self.apply(), {'effects': {'markUnread': False}})

    def test_wrong_child_path_does_not_override_the_parent_turn(self):
        child = self.directory / 'rollout-child-5678-abcd.jsonl'
        entries = [{'type': 'session_meta', 'payload': {'id': '5678-abcd', 'thread_source': 'subagent'}},
                   self.metadata, self.event('task_complete')]
        child.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
        self.registry(child)
        self.assertFalse(self.apply()['effects']['desktop'])

    def test_long_turn_is_found_and_embedded_event_text_is_not_a_terminal_event(self):
        huge = {'type': 'response_item', 'payload': {'type': 'message',
                'text': 'task_complete' + 'x' * 1_900_000}}
        self.write([self.metadata, self.event('task_started'), huge])
        self.assertEqual(MODULE['latest_turn_state'](self.path), 'task_started')

    def test_incomplete_terminal_line_does_not_finish_a_turn(self):
        with self.path.open('a') as stream:
            stream.write(json.dumps(self.event('task_complete')))
        self.assertEqual(MODULE['latest_turn_state'](self.path), 'task_started')

    def test_incomplete_line_larger_than_a_block_does_not_fail_open(self):
        with self.path.open('a') as stream:
            stream.write('{"type":"response_item","payload":{"text":"' + 'x' * 1_500_000)
        self.assertEqual(MODULE['latest_turn_state'](self.path), 'task_started')
        self.assertFalse(self.apply()['effects']['desktop'])

    def test_final_event_flush_delay_is_rechecked(self):
        with patch.dict(MODULE['legacy_codex_complete'].__globals__,
                        latest_turn_state=lambda path: next(states)):
            states = iter(['task_started', 'task_complete'])
            self.assertEqual(self.apply(), {'effects': {'markUnread': False}})

    def test_unknown_state_does_not_invent_completion(self):
        self.write([self.metadata])
        self.assertFalse(self.apply()['effects']['desktop'])

    def test_permissions_are_preserved_and_subagent_completions_are_silent(self):
        self.assertEqual(MODULE['filter_notification']({'agent': {'category': 'needs-permission'}}), {})
        result = MODULE['filter_notification']({'agent': {'category': 'turn-complete', 'isSubagent': True}})
        self.assertFalse(result['effects']['desktop'])
