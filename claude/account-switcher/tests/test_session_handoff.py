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
        folder = self.fixture.home / 'projects' / 'fixture' / SESSION / 'subagents'
        folder.mkdir(parents=True)
        session = {'pid':101,'sessionId':SESSION}
        process = Mock(return_value=Mock(stdout='', returncode=0))
        self.assertTrue(refresh.background_work(session,{101:[(201,'python3')]},
                                               self.restart.projects, SWITCHED_AT, process))
        (folder / 'agent-abc.jsonl').write_text(json.dumps(user_text('unfinished')))
        self.assertTrue(refresh.background_work(session,{},self.restart.projects, SWITCHED_AT, process))

    def test_real_user_text_with_command_tag_ends_limit_stop(self):
        self.fixture.transcript(limit_error(), user_text('<task-notification> My question'))
        self.assertFalse(self.restart.limited())

    def test_overlay_below_form_is_not_the_current_prompt(self):
        self.assertFalse(refresh.input_ready(screen() + '\nConfirm operation? [yes/no]'))

    def test_legacy_terminal_never_pastes_or_submits_even_on_an_empty_screen(self):
        self.fixture.transcript(limit_error())
        refresh.record_switch(self.fixture.state, SWITCHED_AT)
        self.restart.run()
        self.assertEqual(self.runner.typed, [])
        self.assertTrue(self.runner.notices)

    def test_manual_restart_after_two_minutes_offers_continuation_once(self):
        self.fixture.transcript(limit_error())
        refresh.record_switch(self.fixture.state, SWITCHED_AT)
        self.runner.restarts = False
        self.fixture.clock.at(self.fixture.clock()+240,
                              lambda: self.fixture.register('idle',self.fixture.clock()))
        self.assertEqual(self.restart.run(), 'continuation_offered')
        self.assertEqual(len(self.runner.notices),2)
        self.assertEqual(self.runner.typed,[])
