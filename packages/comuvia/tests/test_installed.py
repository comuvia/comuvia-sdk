"""Checks against an installed comuvia distribution (standard library only)."""

import importlib.metadata
import types
import unittest

import comuvia
from package_context import INSTALLED


class InstalledSkeletonTest(unittest.TestCase):
    @unittest.skipUnless(INSTALLED, "comuvia is imported from source; metadata is checked on installed wheels")
    def test_version_matches_distribution_metadata(self):
        self.assertEqual(comuvia.__version__, importlib.metadata.version("comuvia"))

    @unittest.skipUnless(INSTALLED, "comuvia is imported from source; dependencies are checked on installed wheels")
    def test_no_runtime_dependencies(self):
        self.assertIsNone(importlib.metadata.requires("comuvia"))

    def test_exports_only_declared_api(self):
        modules = {name for name, value in vars(comuvia).items() if isinstance(value, types.ModuleType)}
        public = {name for name in vars(comuvia) if not name.startswith("_")} - modules
        self.assertEqual(public, set(comuvia.__all__))
        for name in ("score", "brier", "mean_loss", "skill", "update", "delete", "fetch"):
            self.assertFalse(hasattr(comuvia, name), name)


if __name__ == "__main__":
    unittest.main()
