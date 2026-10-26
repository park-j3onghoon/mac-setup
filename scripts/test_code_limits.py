import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "code_limits", Path(__file__).resolve().parent.parent / "claude/hooks/code-limits.py"
)
code_limits = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(code_limits)

RULES_TEXT = (
    "- Length: when its body passes 3 lines.\n"
    "- Inline an expression while its line stays within 20 characters.\n"
)
LONG_LINE = "x = 'aaaaaaaaaaaaaaaaaaaa'\n"
LONG_FUNCTION = "def run():\n    a = 1\n    b = 2\n    c = 3\n    return a\n"


class CodeLimitsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        rules = self.root / "functions.md"
        rules.write_text(RULES_TEXT)
        self.addCleanup(setattr, code_limits, "RULES_PATH", code_limits.RULES_PATH)
        code_limits.RULES_PATH = rules
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def write(self, name, text):
        path = self.repo / name
        path.write_text(text)
        return path

    def commit(self, name, text):
        path = self.write(name, text)
        self.git("add", name)
        self.git("commit", "-q", "-m", "base")
        return path

    def check(self, path):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = code_limits.check_file(path)
        return exit_code, stderr.getvalue()

    def test_reports_changed_line_over_limit(self):
        """바뀐 줄이 기준 글자 수를 넘으면 알린다."""
        # given: 커밋된 짧은 줄을 긴 줄로 바꾼다
        path = self.commit("app.py", "x = 1\n")
        self.write("app.py", LONG_LINE)
        # when
        exit_code, report = self.check(path)
        # then
        self.assertEqual(exit_code, code_limits.VIOLATION_EXIT_CODE)
        self.assertIn("1행 26자", report)

    def test_ignores_unchanged_line_over_limit(self):
        """HEAD에 이미 있던 긴 줄은 바꾸지 않았으면 알리지 않는다."""
        # given: 긴 줄은 그대로 두고 다른 줄만 더한다
        path = self.commit("app.py", LONG_LINE)
        self.write("app.py", LONG_LINE + "y = 2\n")
        # when
        exit_code, _ = self.check(path)
        # then
        self.assertEqual(exit_code, 0)

    def test_ignores_comment_line_over_limit(self):
        """주석 줄은 길어도 알리지 않는다."""
        # given
        path = self.commit("app.py", "x = 1\n")
        self.write("app.py", "# aaaaaaaaaaaaaaaaaaaaaaaaa\nx = 1\n")
        # when
        exit_code, _ = self.check(path)
        # then
        self.assertEqual(exit_code, 0)

    def test_checks_every_line_of_file_missing_in_head(self):
        """HEAD에 없는 새 파일은 모든 줄을 바뀐 줄로 본다."""
        # given
        self.commit("app.py", "x = 1\n")
        path = self.write("new.py", LONG_LINE)
        # when
        exit_code, _ = self.check(path)
        # then
        self.assertEqual(exit_code, code_limits.VIOLATION_EXIT_CODE)

    def test_reports_new_function_over_body_limit(self):
        """새 함수 본문이 기준 줄 수를 넘으면 알린다."""
        # given
        path = self.commit("app.py", "x = 1\n")
        self.write("app.py", LONG_FUNCTION)
        # when
        exit_code, report = self.check(path)
        # then
        self.assertEqual(exit_code, code_limits.VIOLATION_EXIT_CODE)
        self.assertIn("run(1행) 본문 4줄", report)

    def test_ignores_function_already_over_limit_in_head(self):
        """HEAD에서 이미 기준을 넘던 함수는 고쳐도 알리지 않는다."""
        # given
        path = self.commit("app.py", LONG_FUNCTION)
        self.write("app.py", LONG_FUNCTION.replace("c = 3", "c = 4"))
        # when
        exit_code, _ = self.check(path)
        # then
        self.assertEqual(exit_code, 0)

    def test_ignores_single_statement_body(self):
        """단순 문장 하나뿐인 본문은 길어도 통째로 둔다."""
        # given: 생성자 호출 하나가 여러 줄에 걸친다
        path = self.commit("app.py", "x = 1\n")
        single_statement = "def build():\n    return dict(\n        a=1,\n        b=2,\n        c=3,\n    )\n"
        self.write("app.py", single_statement)
        # when
        exit_code, _ = self.check(path)
        # then
        self.assertEqual(exit_code, 0)

    def test_does_not_count_docstring_and_comment_lines(self):
        """docstring과 주석만 있는 줄은 본문 줄 수에 넣지 않는다."""
        # given: 코드 줄은 셋이고 docstring·주석 줄이 하나씩 있다
        path = self.commit("app.py", "x = 1\n")
        self.write("app.py", 'def run():\n    """설명"""\n    # 단계\n    a = 1\n    b = 2\n    return a\n')
        # when
        exit_code, _ = self.check(path)
        # then
        self.assertEqual(exit_code, 0)

    def test_check_rules_fails_when_sentence_is_missing(self):
        """functions.md에서 기준 문장을 못 찾으면 규칙 오류로 끝난다."""
        # given
        code_limits.RULES_PATH.write_text("- Length: keep functions short.\n")
        # when
        with contextlib.redirect_stderr(io.StringIO()):
            exit_code = code_limits.check_rules()
        # then
        self.assertEqual(exit_code, code_limits.RULES_ERROR_EXIT_CODE)

    def test_skips_non_code_file(self):
        """코드가 아닌 파일은 검사하지 않는다."""
        # given
        path = self.write("README.md", "a" * 50 + "\n")
        # when
        checked = code_limits.is_checked(path)
        # then
        self.assertFalse(checked)


if __name__ == "__main__":
    unittest.main()
