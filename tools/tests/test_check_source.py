"""The source-check command reports failed, empty and successful suites honestly."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "check_source.py"


class SourceCheckCommand(unittest.TestCase):
    def run_fixture(self, body):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "tools").mkdir()
            shutil.copyfile(TOOL, root / "tools/check_source.py")
            package = root / "packages/comuvia"
            (package / "src/comuvia").mkdir(parents=True)
            (package / "src/comuvia/__init__.py").write_text('__version__ = "test"\n', encoding="utf-8")
            (package / "tests").mkdir()
            (package / "tests/test_fixture.py").write_text(body, encoding="utf-8")
            result = subprocess.run([sys.executable, "-I", str(root / "tools/check_source.py"),
                                     "--package", "comuvia"], capture_output=True, text=True, timeout=30)
            report = json.loads(result.stdout)["results"][0]
            return result, report

    def test_reports_success_and_explicit_skips(self):
        result, report = self.run_fixture(
            'import unittest\nclass Example(unittest.TestCase):\n'
            ' def test_pass(self): self.assertEqual(2 + 2, 4)\n'
            ' @unittest.skip("explicit unavailable optional dependency")\n'
            ' def test_optional(self): pass\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["tests"], 2)
        self.assertEqual(len(report["skipped"]), 1)

    def test_failure_returns_nonzero_and_diagnostic(self):
        result, report = self.run_fixture(
            'import unittest\nclass Example(unittest.TestCase):\n'
            ' def test_failure(self): self.fail("deliberate regression")\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["ok"])
        self.assertEqual(report["failures"], 1)
        self.assertIn("deliberate regression", result.stderr)

    def test_empty_suite_cannot_pass(self):
        result, report = self.run_fixture('"""No tests."""\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["tests"], 0)


    def test_all_skipped_cannot_pass(self):
        result, report = self.run_fixture(
            'import unittest\nclass Example(unittest.TestCase):\n'
            ' @unittest.skip("unavailable")\n'
            ' def test_optional(self): pass\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["tests"], len(report["skipped"]))


if __name__ == "__main__":
    unittest.main()
