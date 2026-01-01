"""Checks against an installed foreglass distribution (standard library only)."""

import importlib.metadata
import re
import types
import unittest

import foreglass


class InstalledSkeletonTest(unittest.TestCase):
    def test_version_matches_distribution_metadata(self):
        self.assertEqual(foreglass.__version__, importlib.metadata.version("foreglass"))

    def test_depends_only_on_core(self):
        requires = importlib.metadata.requires("foreglass") or []
        self.assertEqual(len(requires), 1, requires)
        name, specifiers = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*(.*)", requires[0]).groups()
        self.assertEqual(name, "comuvia")
        self.assertEqual(sorted(specifiers.replace(" ", "").split(",")), ["<0.2", ">=0.1.0"])

    def test_exports_only_declared_api(self):
        modules = {name for name, value in vars(foreglass).items() if isinstance(value, types.ModuleType)}
        public = {name for name in vars(foreglass) if not name.startswith("_")} - modules
        self.assertEqual(public, set(foreglass.__all__))


if __name__ == "__main__":
    unittest.main()
