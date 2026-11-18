"""A source test must not silently exercise an installed or ambient package."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import comuvia
from package_context import python_cli, python_code


class PackageContext(unittest.TestCase):
    def test_child_uses_same_package_and_ignores_ambient_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "comuvia.py").write_text("raise RuntimeError('wrong package')\n", encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=folder)
            code = ("import json, sys, comuvia\n"
                    "print(json.dumps([comuvia.__file__, sys.flags.isolated, sys.argv[1:]]))\n")
            result = subprocess.run(python_code(code, "argument with spaces"), cwd=folder,
                                    env=env, capture_output=True, text=True, timeout=30, check=True)
            module, isolated, args = json.loads(result.stdout)
            self.assertEqual(Path(module).resolve(), Path(comuvia.__file__).resolve())
            self.assertEqual(isolated, 1)
            self.assertEqual(args, ["argument with spaces"])

    def test_cli_runs_outside_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(python_cli("--help"), cwd=folder, capture_output=True,
                                    text=True, timeout=30, check=True)
            self.assertIn("store", result.stdout)
