import json
import tempfile
import unittest
from unittest.mock import Mock

import refresh
from test_refresh import (SESSION, SWITCHED_AT, FakeRunner, SessionFixture,
                          limit_error, screen, user_text)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fixture = SessionFixture(tmp.name)
        self.runner = FakeRunner(self.fixture)
        self.restart = self.fixture.restart(self.runner)

    def test_duplicate_registrations_require_the_source_process(self):
        path = self.fixture.home / 'sessions' / '101.json'
        twin = json.loads(path.read_text())
        twin['pid'] = 202
        (path.parent / '202.json').write_text(json.dumps(twin))
        with self.assertRaises(refresh.SessionUnavailable):
            self.restart.session()
        self.restart.ancestors = (202, 1)
        self.assertEqual(self.restart.session()['pid'], 202)

    def test_initially_torn_registration_is_retryable(self):
        (self.fixture.home / 'sessions' / '101.json').write_bytes(b'{')
        with self.assertRaises(refresh.SessionUnavailable):
            self.restart.session()

    def test_shell_free_task_and_old_incomplete_agent_remain_busy(self):
        session = {'pid':101,'sessionId':SESSION}
        process = Mock(return_value=Mock(stdout='', returncode=0))
        self.assertTrue(refresh.background_work(session,{101:[(201,'python3')]},
                                               self.restart.projects, SWITCHED_AT, process))
        self.fixture.subagent({})
        self.assertTrue(refresh.background_work(session,{},self.restart.projects, SWITCHED_AT, process))

    def agent_busy(self, started_at=0):
        return refresh.background_work({'pid': 101, 'sessionId': SESSION, 'startedAt': started_at}, {},
                                       self.restart.projects, SWITCHED_AT, Mock())

    def test_agent_marked_finished_is_not_busy(self):
        self.fixture.subagent({'finished': True})
        self.assertFalse(self.agent_busy())

    def test_agent_resumed_after_an_earlier_completion_is_busy(self):
        notice = '<task-notification>\n<task-id>abc</task-id>\n<status>completed</status>\n</task-notification>'
        self.fixture.transcript({'type': 'queue-operation', 'operation': 'enqueue', 'content': notice})
        self.fixture.subagent({'agentType': 'general-purpose'})
        self.assertTrue(self.agent_busy())

    def test_agent_left_by_an_earlier_process_is_not_busy(self):
        self.fixture.subagent({}, written=SWITCHED_AT - 60)
        self.assertFalse(self.agent_busy(started_at=SWITCHED_AT * 1000))

    def test_real_user_text_with_command_tag_ends_limit_stop(self):
        self.fixture.transcript(limit_error(), user_text('<task-notification> My question'))
        self.assertFalse(self.restart.limited())

    def test_overlay_below_form_is_not_the_current_prompt(self):
        self.assertFalse(refresh.input_ready(screen() + '\nConfirm operation? [yes/no]'))

    def test_restart_seen_by_a_later_helper_is_continued_once(self):
        self.fixture.transcript(limit_error())
        refresh.record_switch(self.fixture.state, SWITCHED_AT)
        self.runner.restarts = False
        self.assertEqual(self.restart.run(), 'restart_unconfirmed')

        self.fixture.register('idle', self.fixture.clock())
        outcomes = [self.fixture.restart(self.runner).run() for _ in range(2)]

        self.assertEqual(outcomes, ['restarted_and_continued', 'no_switch'])
        self.assertEqual(self.runner.typed, ['/restart', 'enter', refresh.CONTINUE_PROMPT, 'enter'])
