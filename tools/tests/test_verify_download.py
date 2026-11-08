"""Offline tests for tools/verify_download.py: the index and file downloads are stubbed.

Run from the repository root: python -m unittest discover -s tools/tests
Makes no network request.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_download as vd  # noqa: E402

WHEEL, SDIST = b"synthetic wheel bytes", b"synthetic sdist bytes"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class VerifyDownloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="verify-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = self.root / "repo"
        self.out = self.root / "out"
        self.out.mkdir()
        (self.repo / "release" / "9.9.1").mkdir(parents=True)
        (self.repo / "release" / "9.9.1" / "SHA256SUMS").write_text(
            f"{sha(WHEEL)}  demo-9.9.1-py3-none-any.whl\n{sha(SDIST)}  demo-9.9.1.tar.gz\n", encoding="utf-8")
        self.files = {"demo-9.9.1-py3-none-any.whl": WHEEL, "demo-9.9.1.tar.gz": SDIST}
        self.declared = {name: sha(data) for name, data in self.files.items()}
        self.requested = []
        original = vd.fetch
        vd.fetch = self.fake_fetch
        self.addCleanup(setattr, vd, "fetch", original)

    def fake_fetch(self, url: str, version: str = vd.DEFAULT_VERSION) -> bytes:
        self.requested.append(url)
        if url.endswith("/json"):
            return json.dumps({"urls": [
                {"filename": name, "url": f"https://files.pythonhosted.org/packages/{name}",
                 "digests": {"sha256": self.declared[name]}, "yanked": False} for name in self.files]}).encode()
        return self.files[url.rsplit("/", 1)[1]]

    def test_approved_pair_is_read_for_the_requested_version(self) -> None:
        approved = vd.approved_for("demo", "9.9.1", self.repo)
        self.assertEqual(approved, {"demo-9.9.1-py3-none-any.whl": sha(WHEEL), "demo-9.9.1.tar.gz": sha(SDIST)})

    def test_a_version_without_approved_digests_is_refused(self) -> None:
        with self.assertRaisesRegex(vd.Refused, "release/9.9.2/SHA256SUMS is absent"):
            vd.approved_for("demo", "9.9.2", self.repo)

    def test_a_package_not_listed_for_that_version_is_refused(self) -> None:
        with self.assertRaisesRegex(vd.Refused, "other 9.9.1 was not released"):
            vd.approved_for("other", "9.9.1", self.repo)

    def test_a_malformed_version_is_refused_before_any_path_is_built(self) -> None:
        for bad in ("../0.1.0", "0.1", "0.1.1/../x", ""):
            with self.subTest(version=bad), self.assertRaisesRegex(vd.Refused, "not a release version"):
                vd.approved_for("demo", bad, self.repo)

    def test_matching_files_are_written_and_the_versioned_json_is_read(self) -> None:
        results = vd.verify("pypi", "demo", self.out, vd.approved_for("demo", "9.9.1", self.repo), "9.9.1")
        self.assertEqual(sorted(r["file"] for r in results), sorted(self.files))
        self.assertEqual((self.out / "demo-9.9.1-py3-none-any.whl").read_bytes(), WHEEL)
        self.assertEqual(self.requested[0], "https://pypi.org/pypi/demo/9.9.1/json")

    def test_a_digest_that_differs_from_the_approved_one_writes_nothing(self) -> None:
        approved = vd.approved_for("demo", "9.9.1", self.repo)
        approved["demo-9.9.1.tar.gz"] = "0" * 64
        with self.assertRaisesRegex(vd.Refused, "approved"):
            vd.verify("pypi", "demo", self.out, approved, "9.9.1")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_an_index_digest_that_differs_from_the_bytes_is_refused(self) -> None:
        self.declared["demo-9.9.1-py3-none-any.whl"] = "1" * 64
        with self.assertRaisesRegex(vd.Refused, "index declares"):
            vd.verify("pypi", "demo", self.out, vd.approved_for("demo", "9.9.1", self.repo), "9.9.1")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_the_released_directories_list_each_released_pair(self) -> None:
        self.assertEqual(len(vd.approved_for("comuvia", "0.1.0")), 2)
        self.assertEqual(len(vd.approved_for("foreglass", "0.1.0")), 2)
        self.assertEqual(len(vd.approved_for("comuvia", "0.1.1")), 2)
        with self.assertRaisesRegex(vd.Refused, "foreglass 0.1.1 was not released"):
            vd.approved_for("foreglass", "0.1.1")


if __name__ == "__main__":
    unittest.main()
