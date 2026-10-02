"""Offline tests for tools/export_public.py on small synthetic repositories.

Run from the repository root: python -m unittest discover -s tools/tests
Needs git on PATH; makes no network request.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_public as ep  # noqa: E402

PUBLIC = ["README.md", "docs", "release/9.9.9", "packages/demo"]
IDENTITY = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.org",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.org",
            "GIT_AUTHOR_DATE": "1700000000 +0000", "GIT_COMMITTER_DATE": "1700000000 +0000"}
LATER = "2026-01-02T03:04:05Z"


def run_git(*args: str, cwd: Path) -> str:
    env = dict(os.environ, **IDENTITY)
    result = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, env=env,
                            capture_output=True, check=True)
    return result.stdout.decode().strip()


class ExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="export-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.source = self.root / "source"
        self.source.mkdir()
        template = self.root / "template"
        template.mkdir()
        run_git("init", "-q", f"--template={template}", "-b", "main", ".", cwd=self.source)
        run_git("config", "core.autocrlf", "false", cwd=self.source)
        self.write("README.md", "# Demo\n\nSee [the guide](docs/guide.md).\n")
        self.write("docs/guide.md", "A guide.\n")
        self.write("release/9.9.9/SHA256SUMS", "0" * 64 + "  demo-9.9.9.tar.gz\n")
        self.write("packages/demo/demo.py", "VALUE = 1\n")
        self.write("private/notes.md", "Internal only.\n")
        self.commit("initial")
        self.deny = self.root / "deny.txt"
        self.deny.write_text("forbidden-term\n", encoding="utf-8")
        self.counter = 0

    def write(self, path: str, text: str) -> None:
        target = self.source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def commit(self, message: str) -> str:
        run_git("add", "-A", cwd=self.source)
        run_git("commit", "-q", "--no-verify", "-m", message, cwd=self.source)
        return run_git("rev-parse", "HEAD", cwd=self.source)

    def new_dir(self) -> Path:
        self.counter += 1
        return self.root / f"out{self.counter}"

    def message(self, text: str = "Update the guide\n", data: bytes | None = None) -> Path:
        path = self.root / f"message{self.counter}.txt"
        path.write_bytes(data if data is not None else text.encode("utf-8"))
        return path

    def export(self, *argv: str, public: list[str] | None = None) -> dict:
        args = ep.build_parser().parse_args(["--out", str(self.new_dir()), "--deny-list", str(self.deny),
                                             "--ref", "HEAD", *argv])
        return ep.export(args, repo=self.source, public_paths=public or PUBLIC)

    def initial_parent(self) -> tuple[Path, str]:
        report = self.export()
        self.assertEqual(report["scan"], "clean", report)
        parent = self.root / f"out{self.counter}"
        return parent, report["export_commit"]

    def chained(self, parent: Path, commit: str, *argv: str, date: str = LATER, message: Path | None = None,
                public: list[str] | None = None) -> dict:
        message = message or self.message()
        return self.export("--parent-repo", str(parent), "--expect-parent", commit, "--date", date,
                           "--message-file", str(message), *argv, public=public)

    # Initial mode

    def test_initial_is_reproducible_and_parentless(self) -> None:
        first, second = self.export(), self.export()
        self.assertEqual(first["export_commit"], second["export_commit"])
        self.assertEqual(first["history"], "one commit, no parents")
        self.assertEqual(first["files"], 4)  # private/ is not public
        self.assertEqual(first["scan"], "clean", first)

    def test_initial_skips_and_reports_absent_paths(self) -> None:
        report = self.export(public=PUBLIC + ["docs/missing.md"])
        self.assertEqual(report["absent_public_paths"], ["docs/missing.md"])
        self.assertEqual(report["scan"], "clean", report)

    def test_freeze_needs_chained_mode(self) -> None:
        with self.assertRaises(SystemExit):
            self.export("--freeze", "README.md")

    # Chained mode

    def test_chained_is_reproducible_with_parent_and_real_date(self) -> None:
        parent, parent_commit = self.initial_parent()
        self.write("docs/guide.md", "A better guide.\n")
        self.commit("edit guide")
        first = self.chained(parent, parent_commit, "--freeze", "packages/demo")
        second = self.chained(parent, parent_commit, "--freeze", "packages/demo")
        self.assertEqual(first["scan"], "clean", first)
        self.assertEqual(first["export_commit"], second["export_commit"])
        self.assertEqual(first["parent"], parent_commit)
        self.assertEqual(first["history"], f"2 commits; parent {parent_commit}")
        self.assertEqual(first["changed"], [{"status": "M", "path": "docs/guide.md"}])
        self.assertEqual({f["path"]: f["unchanged"] for f in first["frozen"]},
                         {"packages/demo": True, "release/9.9.9/SHA256SUMS": True})
        out = self.root / f"out{self.counter}"
        epoch = ep.parse_date(LATER)
        self.assertEqual(run_git("log", "-1", "--format=%ct %at %P", cwd=out), f"{epoch} {epoch} {parent_commit}")
        self.assertEqual(run_git("log", "-1", "--format=%B", cwd=out), "Update the guide")
        self.assertFalse((out / ".git" / "FETCH_HEAD").exists())
        self.assertEqual(run_git("remote", cwd=out), "")

    def test_chained_refuses_a_wrong_parent(self) -> None:
        parent, _ = self.initial_parent()
        self.write("docs/guide.md", "Changed.\n")
        self.commit("edit")
        with self.assertRaises(SystemExit):
            self.chained(parent, "f" * 40)
        with self.assertRaises(SystemExit):
            self.chained(parent, "abc1234")  # not a full id

    def test_chained_refuses_a_dirty_parent(self) -> None:
        parent, commit = self.initial_parent()
        self.write("docs/guide.md", "Changed.\n")
        self.commit("edit")
        (parent / "stray.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.chained(parent, commit)

    def test_chained_refuses_an_unchanged_tree(self) -> None:
        parent, commit = self.initial_parent()
        self.write("private/notes.md", "Still internal.\n")  # not public, so the public tree is unchanged
        self.commit("internal edit")
        with self.assertRaises(SystemExit):
            self.chained(parent, commit)

    def test_chained_dates(self) -> None:
        parent, commit = self.initial_parent()
        self.write("docs/guide.md", "Changed.\n")
        self.commit("edit")
        for bad in ("2025-12-31T23:59:59Z", "2999-01-01T00:00:00Z", "2026-01-02 03:04:05", "2026-01-02T03:04:05+00:00"):
            with self.subTest(date=bad), self.assertRaises(SystemExit):
                self.chained(parent, commit, date=bad)

    def test_chained_messages(self) -> None:
        parent, commit = self.initial_parent()
        self.write("docs/guide.md", "Changed.\n")
        self.commit("edit")
        for bad in (b"No newline", b"Windows line\r\n", b"\nEmpty first line\n", b"\xff\xfe\n"):
            with self.subTest(message=bad), self.assertRaises(SystemExit):
                self.chained(parent, commit, message=self.message(data=bad))
        report = self.chained(parent, commit, message=self.message("Mentions forbidden-term\n"))
        self.assertEqual(report["scan"], "FAILED")
        self.assertIn("deny_list", {f["rule"] for f in report["findings"]})

    def test_chained_frozen_paths(self) -> None:
        parent, commit = self.initial_parent()
        self.write("release/9.9.9/SHA256SUMS", "1" * 64 + "  demo-9.9.9.tar.gz\n")
        self.commit("change approved digests")
        report = self.chained(parent, commit)
        self.assertEqual(report["scan"], "FAILED")
        self.assertIn({"where": "release/9.9.9/SHA256SUMS", "rule": "frozen_path_changed",
                       "text": "release/9.9.9/SHA256SUMS"}, report["findings"])

    def test_chained_explicit_freeze(self) -> None:
        parent, commit = self.initial_parent()
        self.write("packages/demo/demo.py", "VALUE = 2\n")
        self.commit("change package")
        report = self.chained(parent, commit, "--freeze", "packages/demo")
        self.assertEqual(report["scan"], "FAILED")
        self.assertEqual([f["path"] for f in report["frozen"] if not f["unchanged"]], ["packages/demo"])
        with self.assertRaises(SystemExit):
            self.chained(parent, commit, "--freeze", "packages/absent")

    def test_chained_needs_every_public_path(self) -> None:
        parent, commit = self.initial_parent()
        self.write("docs/new.md", "New page.\n")
        self.commit("add page")
        with self.assertRaises(SystemExit):
            self.chained(parent, commit, public=PUBLIC + ["docs/missing.md"])

    def test_chained_reports_added_and_deleted_paths(self) -> None:
        parent, commit = self.initial_parent()
        self.write("docs/new.md", "New page.\n")
        (self.source / "docs" / "guide.md").unlink()
        self.write("README.md", "# Demo\n\nSee [the new page](docs/new.md).\n")
        self.commit("replace guide")
        report = self.chained(parent, commit)
        self.assertEqual(report["scan"], "clean", report)
        self.assertEqual(sorted((c["status"], c["path"]) for c in report["changed"]),
                         [("A", "docs/new.md"), ("D", "docs/guide.md"), ("M", "README.md")])

    def test_chained_still_scans_links(self) -> None:
        parent, commit = self.initial_parent()
        self.write("docs/guide.md", "See [nothing](missing.md).\n")
        self.commit("dangling link")
        report = self.chained(parent, commit)
        self.assertEqual(report["scan"], "FAILED")
        self.assertIn("dangling_link", {f["rule"] for f in report["findings"]})

    def test_chained_arguments_go_together(self) -> None:
        parent, commit = self.initial_parent()
        with self.assertRaises(SystemExit):
            self.export("--parent-repo", str(parent), "--expect-parent", commit)


if __name__ == "__main__":
    unittest.main()
