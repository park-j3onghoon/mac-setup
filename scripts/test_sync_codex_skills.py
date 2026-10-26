import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("sync_skills", Path(__file__).with_name("sync-codex-skills.py"))
sync_skills = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_skills)


class SyncSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo with spaces"
        self.task_home = self.root / "user with spaces"
        self.project = self.root / "project with spaces"
        self.write(self.repo / "codex/AGENTS.md", "Read shared Codex guidance.\n")
        self.write(self.repo / "claude/lib/codex.md", "Shared tool mapping.\n")
        self.skill("claude/skills/engineering/grill")
        self.skill("private/claude/skills/research")

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def skill(self, path, explicit=True):
        source = self.repo / path
        flag = "disable-model-invocation: true\n" if explicit else ""
        self.write(source / "SKILL.md", f"---\nname: {source.name}\ndescription: Test workflow.\n{flag}---\n\nPerform the workflow.\n")
        return source

    def sync(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return sync_skills.sync(self.repo, self.task_home, [self.project], **kwargs)

    def test_shared_sources_propagate_edits_and_new_skills(self):
        self.sync()
        source = self.repo / "claude/skills/engineering/grill"
        for harness in (".claude", ".codex"):
            target = self.task_home / harness / "skills/grill"
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), source)
        self.write(source / "SKILL.md", (source / "SKILL.md").read_text() + "\nA new rule.\n")
        self.assertIn("A new rule.", (self.task_home / ".codex/skills/grill/SKILL.md").read_text())
        self.skill("claude/skills/productivity/new-skill")
        self.sync()
        self.assertTrue((self.task_home / ".codex/skills/new-skill/SKILL.md").is_file())

    def test_public_only_install_and_private_override(self):
        public = self.skill("claude/skills/engineering/research")
        private = self.repo / "private/claude/skills/research"
        self.sync()
        self.assertEqual((self.task_home / ".codex/skills/research").resolve(), private)
        other_repo = self.root / "public only"
        self.write(other_repo / "claude/skills/engineering/grill/SKILL.md", "---\nname: grill\n---\n")
        self.assertEqual(list(sync_skills.shared_skills(other_repo)), ["grill"])
        self.assertTrue(public.is_dir())

    def test_conflicting_files_are_backed_up_and_system_skills_survive(self):
        system = self.task_home / ".codex/skills/.system/system-skill/SKILL.md"
        self.write(system, "System skill.\n")
        personal = self.task_home / ".codex/skills/grill/SKILL.md"
        self.write(personal, "Personal customization.\n")
        project_copy = self.project / ".codex/skills/grill/SKILL.md"
        self.write(project_copy, "Old project workflow.\n")
        unique = self.project / ".codex/skills/review/SKILL.md"
        self.write(unique, "Project-specific review.\n")
        self.sync()
        self.assertEqual(system.read_text(), "System skill.\n")
        self.assertEqual(unique.read_text(), "Project-specific review.\n")
        self.assertFalse(project_copy.exists())
        saved = list((self.project / ".codex/skill-backups").rglob("SKILL.md"))
        self.assertEqual([p.read_text() for p in saved], ["Old project workflow.\n"])
        personal_saved = list((self.task_home / ".codex/skill-backups").rglob("SKILL.md"))
        self.assertEqual([p.read_text() for p in personal_saved], ["Personal customization.\n"])
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.sync(check=True), 0)

    def test_check_and_dry_run_leave_files_untouched(self):
        self.assertGreater(self.sync(check=True), 0)
        self.assertGreater(self.sync(dry_run=True), 0)
        self.assertFalse(self.task_home.exists())
        self.assertFalse((self.repo / "claude/skills/engineering/grill/agents").exists())

    def test_codex_policy_preserves_explicit_and_automatic_invocation(self):
        automatic = self.skill("claude/skills/productivity/tutor", explicit=False)
        custom = self.skill("claude/skills/engineering/custom")
        custom_policy = custom / "agents/openai.yaml"
        self.write(custom_policy, 'interface:\n  display_name: "Existing"\npolicy:\n  allow_implicit_invocation: false\n')
        before = custom_policy.read_text()
        self.sync()
        policy = self.repo / "claude/skills/engineering/grill/agents/openai.yaml"
        self.assertIn("allow_implicit_invocation: false", policy.read_text())
        self.assertIn("allow_implicit_invocation: true", (automatic / "agents/openai.yaml").read_text())
        self.assertEqual(custom_policy.read_text(), before)

    def test_existing_codex_policy_is_aligned_without_losing_interface(self):
        source = self.repo / "claude/skills/engineering/grill"
        policy = source / "agents/openai.yaml"
        self.write(policy, 'interface:\n  display_name: "Existing"\npolicy:\n  allow_implicit_invocation: true # Keep this comment\ndependencies:\n  tools: []\n')
        original = policy.read_text()
        self.assertGreater(self.sync(check=True), 0)
        self.assertEqual(policy.read_text(), original)
        self.sync()
        self.assertEqual(policy.read_text(), original.replace('invocation: true', 'invocation: false'))
        self.assertEqual(self.sync(check=True), 0)

    def test_uneditable_policy_fails_before_modifying_the_home(self):
        source = self.repo / "private/claude/skills/research"
        self.write(source / "agents/openai.yaml", 'policy: {allow_implicit_invocation: true}\n')
        with self.assertRaisesRegex(ValueError, "block-style"):
            self.sync()
        self.assertFalse(self.task_home.exists())

    def test_changing_claude_invocation_policy_updates_codex_in_both_directions(self):
        source = self.repo / "claude/skills/engineering/grill"
        manifest = source / "SKILL.md"
        self.sync()
        original = manifest.read_text()
        manifest.write_text(original.replace("disable-model-invocation: true\n", ""))
        self.assertGreater(self.sync(check=True), 0)
        self.sync()
        self.assertIn("allow_implicit_invocation: true", (source / "agents/openai.yaml").read_text())
        manifest.write_text(original)
        self.sync()
        self.assertIn("allow_implicit_invocation: false", (source / "agents/openai.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
