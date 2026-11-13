"""Provider streams keep hidden checkpoint fields out of the learner's live reply."""

import json
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

from study_runner import ProviderStream, provider_command, reply_prefix


class ReplyStreamTests(unittest.TestCase):
    def test_partial_reply_is_unescaped_without_checkpoint_leaks(self):
        self.assertEqual(reply_prefix('{"reply":"안녕\\n세상'), '안녕\n세상')
        self.assertEqual(reply_prefix('{"reply":"안녕\\'), '안녕')
        self.assertEqual(reply_prefix('{"reply":"안녕\\u'), '안녕')
        self.assertEqual(reply_prefix('{"reply":"공개","state_json":"SECRET"}'), '공개')
        nested = {'state_json': json.dumps({'reply': 'PRIVATE'}), 'reply': '공개'}
        self.assertEqual(reply_prefix(json.dumps(nested)), '공개')

    def test_codex_reasoning_and_private_state_are_not_published(self):
        updates = []
        stream = ProviderStream('codex', updates.append)
        stream.consume({'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'PRIVATE'}})
        self.assertEqual(set(updates[0]), {'last_activity_at', 'activity_count'})
        self.assertEqual(updates[0]['activity_count'], 1)
        self.assertNotIn('PRIVATE', json.dumps(updates))
        message = json.dumps({'reply': '공개 답변', 'state_json': 'SECRET-RUBRIC'})
        stream.consume({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': message}})
        self.assertEqual(updates[-1]['reply_preview'], '공개 답변')
        self.assertNotIn('SECRET', json.dumps(updates))

    def test_activity_is_received_event_metadata_not_a_fake_heartbeat(self):
        updates = []
        stream = ProviderStream('codex', updates.append)
        self.assertEqual(updates, [])
        stream.consume({'type': 'thread.started', 'thread_id': 'PRIVATE-ID'})
        stream.consume({'type': 'turn.started'})
        self.assertEqual([item['activity_count'] for item in updates], [1, 2])
        self.assertNotIn('PRIVATE-ID', json.dumps(updates))

    def test_claude_structured_deltas_publish_before_result(self):
        updates = []
        stream = ProviderStream('claude', updates.append)
        stream.consume_claude_delta({'type': 'content_block_start', 'index': 0,
                                    'content_block': {'type': 'tool_use', 'name': 'StructuredOutput'}})
        for text in ('{"reply":"안녕', '하세요.","state_json":"SECRET"}'):
            stream.consume_claude_delta({'type': 'content_block_delta', 'index': 0,
                                        'delta': {'type': 'input_json_delta', 'partial_json': text}})
        self.assertIsNone(stream.result)
        self.assertEqual(updates[0]['reply_preview'], '안녕')
        self.assertEqual(updates[-1]['reply_preview'], '안녕하세요.')
        self.assertNotIn('SECRET', json.dumps(updates))

    def test_claude_thinking_and_other_tool_input_are_not_published(self):
        updates = []
        stream = ProviderStream('claude', updates.append)
        stream.consume_claude_delta({'type': 'content_block_start', 'index': 0,
                                    'content_block': {'type': 'thinking'}})
        stream.consume_claude_delta({'type': 'content_block_delta', 'index': 0,
                                    'delta': {'type': 'thinking_delta', 'thinking': 'PRIVATE'}})
        stream.consume_claude_delta({'type': 'content_block_start', 'index': 1,
                                    'content_block': {'type': 'tool_use', 'name': 'Bash'}})
        stream.consume_claude_delta({'type': 'content_block_delta', 'index': 1,
                                    'delta': {'type': 'input_json_delta',
                                              'partial_json': '{"reply":"PRIVATE"}'}})
        self.assertEqual(updates, [])

    @patch('study_runner.shutil.which', side_effect=lambda name: '/bin/' + name)
    def test_provider_commands_are_noninteractive_and_restrict_tools(self, which):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            codex = provider_command('codex', directory, {})
            claude = provider_command('claude', directory, {})
        self.assertIn('--json', codex)
        self.assertEqual(codex[codex.index('--model') + 1], 'gpt-6.1-sol')
        self.assertIn('model_reasoning_effort="xhigh"', codex)
        self.assertIn('service_tier="default"', codex)
        self.assertIn('--ignore-user-config', codex)
        self.assertIn('read-only', codex)
        self.assertIn('--include-partial-messages', claude)
        self.assertIn('--safe-mode', claude)
        self.assertEqual(claude[claude.index('--tools') + 1], '')
        self.assertNotIn('--dangerously-skip-permissions', claude)


if __name__ == '__main__':
    unittest.main()
